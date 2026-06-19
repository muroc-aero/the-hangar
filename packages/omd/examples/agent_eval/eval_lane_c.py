#!/usr/bin/env python3
"""Lane C agent eval: blind agent vs Lane A reference, scored automatically.

Stage 2 of Lane C parity coverage (stage 1 is the scripted in-process
suite in examples/tests/test_parity_lane_c.py). This harness launches a
real agent through the Claude Agent SDK, hands it only the Lane C task
requirements, restricts it to the omd MCP tools (no filesystem, no
Bash, no repo access), and compares the metrics it reports against the
Lane A reference scripts.

Requires the claude-agent-sdk package and the Claude Code CLI:

    uv run --with claude-agent-sdk \
        packages/omd/examples/agent_eval/eval_lane_c.py paraboloid

    # all cases
    uv run --with claude-agent-sdk \
        packages/omd/examples/agent_eval/eval_lane_c.py all

The agent must end its run with a fenced JSON report; the harness
parses it, scores each metric against Lane A, and exits nonzero on any
required-metric failure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLES_DIR = HERE.parent
REPO_ROOT = EXAMPLES_DIR.parents[2]


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------


@dataclass
class Metric:
    key: str                # flat key the agent must report under "metrics"
    lane_a_module: str      # lane_a module whose run() provides the reference
    lane_a_key: str         # key in that run()'s return dict
    rtol: float
    required: bool = True   # False: missing value is a WARN, not a FAIL


@dataclass
class Case:
    example: str            # directory name under packages/omd/examples/
    prompt_file: str        # file under <example>/lane_c/
    metrics: list[Metric]
    # Extra requirements appended to the task (details the lane_c prompt
    # delegates to repo files a blind MCP-only agent cannot read).
    supplement: str = ""
    lane_a_modules: list[str] = field(init=False)

    def __post_init__(self):
        self.lane_a_modules = sorted({m.lane_a_module for m in self.metrics})


# Mission supplement mirrors ocp_oas_coupled/shared.py MISSION (the lane_c
# prompt points at the ocp_caravan_basic example for these, which a blind
# agent cannot read).
_COUPLED_MISSION_SUPPLEMENT = """
Mission profile (same as the baseline Caravan basic mission):
- Climb: 850 ft/min at 104 kn EAS
- Cruise: 129 kn EAS
- Descent: 400 ft/min at 100 kn EAS
- 11 integration nodes per phase
"""

CASES: dict[str, Case] = {
    "paraboloid": Case(
        example="paraboloid",
        prompt_file="all.prompt.md",
        metrics=[
            Metric("analysis_f_xy", "analysis", "f_xy", rtol=1e-6),
            Metric("opt_f_xy", "optimization", "f_xy", rtol=1e-4),
            # DV retrieval through the tool surface is a known gap
            # (FEATURE_BACKLOG); score but do not fail on these.
            Metric("opt_x", "optimization", "x", rtol=1e-3, required=False),
            Metric("opt_y", "optimization", "y", rtol=1e-3, required=False),
        ],
    ),
    "ocp_caravan_basic": Case(
        example="ocp_caravan_basic",
        prompt_file="basic_mission.prompt.md",
        metrics=[
            Metric("fuel_burn_kg", "basic_mission", "fuel_burn_kg", rtol=1e-3),
            Metric("OEW_kg", "basic_mission", "OEW_kg", rtol=1e-3),
            Metric("MTOW_kg", "basic_mission", "MTOW_kg", rtol=1e-6),
        ],
    ),
    "ocp_oas_coupled": Case(
        example="ocp_oas_coupled",
        prompt_file="coupled_mission.prompt.md",
        supplement=_COUPLED_MISSION_SUPPLEMENT,
        metrics=[
            Metric("fuel_burn_kg", "coupled_mission", "fuel_burn_kg", rtol=1e-3),
            Metric("OEW_kg", "coupled_mission", "OEW_kg", rtol=1e-3),
            Metric("MTOW_kg", "coupled_mission", "MTOW_kg", rtol=1e-6),
        ],
    ),
    # Open-ended evt sizing: the prompt (sizing_open) states the engineering
    # goal but names no factory, template, solver, or parameter keys -- the
    # agent must self-serve from omd://reference to land on evt/Sizing plus the
    # built-in archer_midnight template. Lane A loads that vehicle from its
    # JSON; the template is vendored from the same file, so a template-built
    # result matches the file-based reference to round-off.
    "evt_open_sizing": Case(
        example="evt_native_sizing",
        prompt_file="sizing_open.prompt.md",
        metrics=[
            Metric("sized_mtow_kg", "sizing", "sized_mtow_kg", rtol=1e-3),
            Metric("total_mission_energy_kw_hr", "sizing",
                   "total_mission_energy_kw_hr", rtol=1e-3),
            Metric("peak_power_kw", "sizing", "peak_power_kw", rtol=1e-3),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Lane A references (one subprocess per example: shared.py modules collide
# when different examples are imported into the same process)
# ---------------------------------------------------------------------------


def lane_a_reference(example: str, module: str) -> dict:
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(EXAMPLES_DIR)!r})\n"
        f"from {example}.lane_a.{module} import run\n"
        "print(json.dumps(run(), default=float))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Lane A reference {example}.lane_a.{module} failed:\n{proc.stderr}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

PREAMBLE = """\
You are an engineering analysis agent evaluating the omd MCP server.
Complete the task below using ONLY the omd MCP tools (mcp__omd__*).

HARD RULES:
- You have no filesystem, shell, or web access; author and run the plan
  entirely through the tool workspace (relative paths resolve server-side).
- References to `omd-cli` or skill files in the task text do not apply:
  use the equivalent MCP tools instead, and skip deliverables that only
  make sense for a filesystem client.
- If a tool call fails, adapt and retry with corrected inputs.

WORKFLOW (the server's required order):
start_session -> author plan (plan_init, plan_add_component, ...) ->
log_decision -> validate_plan -> review_plan -> run_plan ->
get_results / get_run_summary -> generate_plots -> record_conclusion ->
get_provenance -> export_session_graph.

--- TASK ---
"""

REPORT_FORMAT = """\

--- REPORT FORMAT ---
End your final message with exactly one fenced JSON block:

```json
{{
  "plan_id": "...",
  "run_id": "...",
  "status": "...",
  "metrics": {{{metric_keys}}},
  "friction": ["each tool error, confusing parameter, or workaround"]
}}
```

Report every metric at full precision (all digits the tools give you).
If a metric is not retrievable through the tools, set it to null and
explain in "friction". Do not round, do not omit keys.
"""


def build_prompt(case: Case) -> str:
    task = (EXAMPLES_DIR / case.example / "lane_c" / case.prompt_file).read_text()
    metric_keys = ", ".join(f'"{m.key}": <number>' for m in case.metrics)
    return (
        PREAMBLE + task + case.supplement
        + REPORT_FORMAT.format(metric_keys=metric_keys)
    )


# ---------------------------------------------------------------------------
# Agent run (Claude Agent SDK)
# ---------------------------------------------------------------------------


async def run_agent(prompt: str, data_root: Path, model: str | None,
                    max_turns: int, verbose: bool) -> tuple[str, float | None]:
    try:
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock,
            query,
        )
    except ImportError:
        sys.exit(
            "claude-agent-sdk is not installed. Run via:\n"
            "  uv run --with claude-agent-sdk "
            "packages/omd/examples/agent_eval/eval_lane_c.py <case>"
        )

    options = ClaudeAgentOptions(
        cwd=str(REPO_ROOT),
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        mcp_servers={
            "omd": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "hangar.omd.server"],
                "env": {
                    "OMD_DATA_ROOT": str(data_root / "omd_data"),
                    "OMD_DB_PATH": str(data_root / "analysis.db"),
                    "OMD_PLAN_STORE": str(data_root / "plans"),
                    "OMD_RECORDINGS_DIR": str(data_root / "recordings"),
                },
            },
        },
        allowed_tools=["mcp__omd"],
        disallowed_tools=[
            "Bash", "Read", "Write", "Edit", "Glob", "Grep",
            "WebFetch", "WebSearch", "Task", "NotebookEdit",
        ],
    )

    final_text, cost = "", None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    final_text = block.text
                    if verbose:
                        print(f"  [agent] {block.text[:200]}", flush=True)
        elif isinstance(message, ResultMessage):
            if message.result:
                final_text = message.result
            cost = message.total_cost_usd
    return final_text, cost


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def extract_report(text: str) -> dict:
    blocks = re.findall(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    for raw in reversed(blocks):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"No parseable JSON report in agent output:\n{text[-2000:]}")


def score_case(case: Case, report: dict, refs: dict[str, dict]) -> bool:
    metrics = report.get("metrics", {})
    print(f"\n  {'Metric':<16s} {'Lane A':>18s} {'Agent':>18s} "
          f"{'Rel err':>10s}  Verdict")
    print(f"  {'-' * 16} {'-' * 18} {'-' * 18} {'-' * 10}  {'-' * 7}")

    ok = True
    for m in case.metrics:
        ref = refs[m.lane_a_module][m.lane_a_key]
        got = metrics.get(m.key)
        if not isinstance(got, (int, float)):
            verdict = "FAIL" if m.required else "WARN"
            ok = ok and not m.required
            print(f"  {m.key:<16s} {ref:>18.10g} {str(got):>18s} "
                  f"{'n/a':>10s}  {verdict} (missing)")
            continue
        rel = abs(got - ref) / max(abs(ref), 1e-30)
        passed = rel <= m.rtol
        verdict = "PASS" if passed else ("FAIL" if m.required else "WARN")
        ok = ok and (passed or not m.required)
        print(f"  {m.key:<16s} {ref:>18.10g} {got:>18.10g} "
              f"{rel:>10.2e}  {verdict}")

    friction = report.get("friction") or []
    if friction:
        print("\n  Friction log:")
        for item in friction:
            print(f"    - {item}")
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "cases", nargs="+",
        choices=[*CASES, "all"],
        help="Lane C cases to evaluate ('all' runs every case)",
    )
    parser.add_argument("--model", default=None,
                        help="Model override passed to the agent")
    parser.add_argument("--max-turns", type=int, default=80)
    parser.add_argument("--keep-data", action="store_true",
                        help="Keep the temp omd data root for inspection")
    parser.add_argument("--verbose", action="store_true",
                        help="Stream agent text while it works")
    args = parser.parse_args()

    names = list(CASES) if "all" in args.cases else list(dict.fromkeys(args.cases))
    all_ok = True

    for name in names:
        case = CASES[name]
        print(f"\n{'=' * 70}\nLane C agent eval: {name}\n{'=' * 70}")

        print("  Computing Lane A references...")
        refs = {mod: lane_a_reference(case.example, mod)
                for mod in case.lane_a_modules}

        tmp = Path(tempfile.mkdtemp(prefix=f"lane_c_eval_{name}_"))
        print(f"  omd data root: {tmp}")
        print("  Running blind agent (omd MCP tools only)...")
        text, cost = await run_agent(
            build_prompt(case), tmp, args.model, args.max_turns, args.verbose,
        )
        if cost is not None:
            print(f"  Agent cost: ${cost:.4f}")

        try:
            report = extract_report(text)
        except ValueError as exc:
            print(f"  FAIL: {exc}")
            all_ok = False
            continue

        print(f"  plan_id={report.get('plan_id')}  "
              f"run_id={report.get('run_id')}  status={report.get('status')}")
        ok = score_case(case, report, refs)
        all_ok = all_ok and ok
        print(f"\n  Case result: {'PASS' if ok else 'FAIL'}")

        if not args.keep_data:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'=' * 70}\nOverall: {'PASS' if all_ok else 'FAIL'}\n{'=' * 70}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
