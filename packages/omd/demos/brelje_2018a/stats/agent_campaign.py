"""Agent-driven Brelje 2018a campaign: one blind agent MDO per grid cell.

Runs Lane C (agent) across the full Fig 5 / Fig 6 case set and records,
per cell, what the agent's *named run* actually produced -- graded by
effect, not by the agent's own report:

1. The agent gets ``lane_c/hybrid_mdo_cell_open.prompt.md`` rendered for
   the cell (engineering goal and physical inputs only; no expected
   values, no plan paths), wrapped in the omd MCP-only preamble and JSON
   report format from ``examples/agent_eval/eval_lane_c.py``. It runs
   against an isolated omd data root, so it cannot see other runs.
2. The run the agent names is read back from that data root's analysis
   DB (``omd-cli results --summary``): the ten design-variable values
   plus omd's own objective.
3. That design is **re-scored in the upstream truth model**
   (``lane_a_upstream.upstream_truth.rescore_design``: one run_model of
   OpenConcept's HybridTwin at those DVs). Feasibility, objective, DOC
   and the paper's electric-percent all come from the rescore.

Each cell writes ``results/agent_campaign/<arm>/seed<k>/fig<5|6>/<case>.json``
with flat metric keys ``stats/collect_stats.py`` reads directly:

    uv run python .../stats/collect_stats.py \\
        --agent opus=results/agent_campaign/opus/seed0/fig5 \\
        --agent opus=results/agent_campaign/opus/seed1/fig5 ...

(``collect`` below builds those flags for every seed of an arm.)

Subcommands:
    run      launch agents (resumable: cells with a JSON are skipped)
    grade    effect-grade one existing run_id for one cell (no agent) --
             for runs produced elsewhere, e.g. an interactive session
    status   execution statistics for an arm (lost, errors, cost, wall)
    collect  run collect_stats.py over every seed of the given arms

Requires ``claude-agent-sdk`` and an authenticated Claude Code CLI for
``run``:

    uv run --with claude-agent-sdk python .../stats/agent_campaign.py run \\
        --arm opus --seeds 3 --figure all --grid demo --workers 2
    uv run python .../stats/agent_campaign.py run --arm opus --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATS_DIR = Path(__file__).resolve().parent
DEMO_DIR = STATS_DIR.parent
REPO_ROOT = DEMO_DIR.parents[3]
CAMPAIGN_DIR = DEMO_DIR / "results" / "agent_campaign"
PROMPT = DEMO_DIR / "lane_c" / "hybrid_mdo_cell_open.prompt.md"
AGENT_EVAL = REPO_ROOT / "packages" / "omd" / "examples" / "agent_eval"

sys.path.insert(0, str(DEMO_DIR / "lane_a_upstream"))
sys.path.insert(0, str(AGENT_EVAL))

OBJECTIVE_TEXT = {
    "5": ("Minimize fuel burned plus one hundredth of MTOW (both in kg) -- "
          "Brelje & Martins' mixed fuel/weight objective."),
    "6": ("Minimize trip direct operating cost per nautical mile, using the "
          "paper's cost model: fuel $2.50/gal; electricity $36/MWh on 90 % "
          "of the battery's energy; airframe $277/kg of OEW excluding "
          "engine, motors and generator, engine $775/shp, motor and "
          "generator $100/shp, all with a 1.1 OEM premium and depreciated "
          "over 5 flights/day for 15 years; battery $50/kg over a "
          "1500-cycle life."),
}

REPORT_KEYS = ["objective", "MTOW_kg", "fuel_burn_kg", "W_battery_kg", "S_ref_m2",
               "cruise_hybridization", "climb_hybridization", "descent_hybridization"]

# omd summary 'final' keys (by suffix) for each upstream DV.
_FINAL_DV_KEYS = {
    "ac|weights|MTOW": "ac|weights|MTOW",
    "ac|geom|wing|S_ref": "ac|geom|wing|S_ref",
    "ac|propulsion|engine|rating": "ac|propulsion|engine|rating",
    "ac|propulsion|motor|rating": "ac|propulsion|motor|rating",
    "ac|propulsion|generator|rating": "ac|propulsion|generator|rating",
    "ac|weights|W_battery": "ac|weights|W_battery",
    "ac|weights|W_fuel_max": "ac|weights|W_fuel_max",
    "cruise.hybridization": "cruise.hybridization",
    "climb.hybridization": "climb.hybridization",
    "descent.hybridization": "descent.hybridization",
}


def grid_cells(grid: str) -> list[tuple[float, float]]:
    from upstream_truth import GRIDS
    ranges, energies = GRIDS[grid]
    return [(float(r), float(e)) for r in ranges for e in energies]


def case_id(fig: str, r: float, e: float) -> str:
    return f"fig{fig}-r{r:g}-e{e:g}"


def render_prompt(fig: str, r: float, e: float) -> str:
    from eval_lane_c import PREAMBLE, REPORT_FORMAT
    task = PROMPT.read_text().format(range_nm=r, spec_e=e,
                                     objective_text=OBJECTIVE_TEXT[fig])
    keys = ", ".join(f'"{k}": <number>' for k in REPORT_KEYS)
    return PREAMBLE + task + REPORT_FORMAT.format(metric_keys=keys)


# ---------------------------------------------------------------------------
# Effect grading
# ---------------------------------------------------------------------------

def _omd_env(data_root: Path) -> dict:
    env = dict(os.environ)
    env.update(OMD_DATA_ROOT=str(data_root / "omd_data"),
               OMD_DB_PATH=str(data_root / "analysis.db"),
               OMD_PLAN_STORE=str(data_root / "plans"),
               OMD_RECORDINGS_DIR=str(data_root / "recordings"))
    return env


def read_final(run_id: str, env: dict | None = None) -> dict:
    """The final-case values of an omd run, from its analysis DB."""
    omd_cli = Path(sys.executable).parent / "omd-cli"
    cmd = [str(omd_cli), "results", run_id, "--summary"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=REPO_ROOT)
    out = proc.stdout
    start = out.find("{")
    if proc.returncode != 0 or start < 0:
        raise RuntimeError(f"omd-cli results failed for {run_id}: {proc.stderr[-500:]}")
    data = json.loads(out[start:])
    if "error" in data:
        raise RuntimeError(f"{run_id}: {data['error']}")
    return data.get("final") or {}


def _final_value(final: dict, name: str) -> float | None:
    """Look a promoted name up in a summary 'final' dict (exact, else
    shortest key ending in '.name' / '|name')."""
    if name in final:
        v = final[name]
    else:
        hits = sorted((k for k in final if k.endswith("." + name)), key=len)
        if not hits:
            return None
        v = final[hits[0]]
    if isinstance(v, list):
        v = v[0] if v else None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def grade_run(fig: str, r: float, e: float, run_id: str,
              env: dict | None = None) -> dict:
    """Effect-grade one omd run: read its DVs, rescore upstream."""
    from upstream_truth import rescore_design
    final = read_final(run_id, env)
    dvs = {dv: _final_value(final, key) for dv, key in _FINAL_DV_KEYS.items()}
    objective = "fuel" if fig == "5" else "cost"
    rescored = rescore_design(r, e, objective, dvs)
    omd_obj = _final_value(final, "mixed_objective" if fig == "5" else "doc_per_nmi")
    return {"dvs": dvs, "omd_objective": omd_obj, "rescored": rescored}


def list_runs(data_root: Path) -> list[str]:
    """Every run recorded in an isolated omd data root, oldest first."""
    import sqlite3
    db = data_root / "analysis.db"
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT entity_id FROM entities WHERE entity_type = 'run_record' "
            "ORDER BY created_at").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [r[0] for r in rows]


def grade_best_in_db(fig: str, r: float, e: float, data_root: Path):
    """Fallback when the agent named no run (turn cap, crash, no report):
    grade every run in its data root, keep the best feasible one."""
    best = None
    for run_id in list_runs(data_root):
        try:
            g = grade_run(fig, r, e, run_id, _omd_env(data_root))
        except Exception:  # noqa: BLE001 -- e.g. an analysis-only run
            continue
        rs = g["rescored"]
        if not rs.get("feasible"):
            continue
        if best is None or rs["objective_value"] < best[1]["rescored"]["objective_value"]:
            best = (run_id, g)
    return best


def _clean(v):
    if isinstance(v, float) and v != v:
        return None
    return v


def build_record(fig: str, r: float, e: float, *, run_id: str | None,
                 grade: dict | None, report: dict | None, meta: dict) -> dict:
    """Flat per-cell record; metric keys match collect_stats aliases."""
    rec = {"case_id": case_id(fig, r, e), "fig": fig,
           "design_range_nm": r, "spec_energy_whkg": e,
           "run_id": run_id, "converged": False, **meta}
    if report is not None:
        rec["report"] = report
    if grade:
        rs = {k: _clean(v) for k, v in grade["rescored"].items() if not k.startswith("_")}
        rec.update(
            converged=bool(rs.get("feasible")),
            mixed_objective=rs.get("mixed_objective_kg"),
            doc_per_nmi=rs.get("doc_per_nmi"),
            MTOW_kg=rs.get("MTOW_kg"),
            fuel_burn_kg=rs.get("fuel_burn_kg"),
            W_battery_kg=rs.get("W_battery_kg"),
            S_ref_m2=rs.get("S_ref_m2"),
            cruise_hybridization=rs.get("cruise_hybridization"),
            electric_energy_frac=rs.get("electric_energy_frac"),
            max_constraint_violation=rs.get("max_constraint_violation"),
            omd_objective=grade["omd_objective"],
            dvs=grade["dvs"],
            rescore_error=rs.get("error") or "",
        )
        # does the agent's report agree with what its run did?
        rep_obj = (report or {}).get("metrics", {}).get("objective")
        eff_obj = rec["mixed_objective"] if fig == "5" else rec["doc_per_nmi"]
        if rep_obj is not None and eff_obj:
            try:
                rec["report_rel_err"] = abs(float(rep_obj) - eff_obj) / abs(eff_obj)
            except (TypeError, ValueError):
                rec["report_rel_err"] = None
    return rec


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

async def run_agent(prompt: str, data_root: Path, model: str | None,
                    max_turns: int, verbose: bool) -> tuple[str, float | None, int | None]:
    """eval_lane_c.run_agent without ``bypassPermissions`` (which the CLI
    refuses under root, e.g. in containers): the omd MCP tools are
    pre-approved and everything else is disallowed, so no permission
    prompt can arise."""
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage,
                                  TextBlock, query)
    env = _omd_env(data_root)
    options = ClaudeAgentOptions(
        cwd=str(data_root),
        model=model,
        max_turns=max_turns,
        mcp_servers={"omd": {
            "type": "stdio", "command": sys.executable,
            "args": ["-m", "hangar.omd.server"],
            "env": {k: env[k] for k in ("OMD_DATA_ROOT", "OMD_DB_PATH",
                                        "OMD_PLAN_STORE", "OMD_RECORDINGS_DIR")},
        }},
        allowed_tools=["mcp__omd"],
        disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch",
                          "WebSearch", "Task", "NotebookEdit", "Agent"],
    )
    final_text, cost, turns = "", None, None
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
            turns = getattr(message, "num_turns", None)
    return final_text, cost, turns


async def _run_cell(fig, r, e, out_path: Path, args, sem: asyncio.Semaphore) -> dict:
    from eval_lane_c import extract_report
    async with sem:
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="brelje-agent-") as tmp:
            data_root = Path(tmp)
            meta = {"arm": args.arm, "model": args.model, "status": "lost"}
            report = grade = run_id = None
            try:
                text, cost, turns = await run_agent(render_prompt(fig, r, e), data_root,
                                                    args.model, args.max_turns, args.verbose)
                meta.update(cost_usd=cost, turns=turns)
                try:
                    report = extract_report(text)
                except ValueError:
                    meta["status"] = "no_report"
                else:
                    run_id = report.get("run_id")
                    if not run_id:
                        meta["status"] = "no_run_named"
                    else:
                        grade = await asyncio.to_thread(
                            grade_run, fig, r, e, run_id, _omd_env(data_root))
                        meta["status"] = "graded"
            except Exception as exc:  # noqa: BLE001 -- a lost cell is data
                meta["error"] = f"{type(exc).__name__}: {exc}"[:500]
            meta["grading"] = "named_run" if grade else None
            if grade is None:
                # The named-run policy found nothing to grade; still record
                # what the agent's runs achieved, flagged so collect_stats
                # can separate it (--named-only drops these cells).
                found = await asyncio.to_thread(grade_best_in_db, fig, r, e, data_root)
                if found:
                    run_id, grade = found
                    meta["grading"] = "best_in_db"
            meta["n_runs"] = len(list_runs(data_root))
            meta["wall_time_s"] = time.time() - t0
        rec = build_record(fig, r, e, run_id=run_id, grade=grade, report=report, meta=meta)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rec, indent=2, default=str))
        print(f"  {rec['case_id']:<22} {meta['status']:<12} "
              f"feasible={rec['converged']} t={meta['wall_time_s']:.0f}s", flush=True)
        return rec


def _selected(args) -> list[tuple[str, float, float]]:
    figs = ["5", "6"] if args.figure == "all" else [args.figure]
    cells = grid_cells(args.grid)
    if args.cells:
        want = {tuple(float(x) for x in c.split(",")) for c in args.cells}
        cells = [c for c in cells if c in want] + [c for c in want if c not in cells]
    return [(f, r, e) for f in figs for r, e in cells]


def cmd_run(args) -> int:
    todo = []
    for seed in range(args.seed_offset, args.seed_offset + args.seeds):
        for fig, r, e in _selected(args):
            out = CAMPAIGN_DIR / args.arm / f"seed{seed}" / f"fig{fig}" / f"{case_id(fig, r, e)}.json"
            if out.exists() and not args.force:
                continue
            todo.append((fig, r, e, out))
    est_min = len(todo) * args.est_cell_minutes / max(args.workers, 1)
    print(f"[agent-campaign] arm={args.arm}: {len(todo)} cell run(s) to go, "
          f"{args.workers} concurrent, ~{est_min / 60:.1f} h at "
          f"{args.est_cell_minutes:g} min/cell")
    if args.dry_run:
        if todo:
            fig, r, e, _ = todo[0]
            print("\n--- first prompt ---\n" + render_prompt(fig, r, e))
        return 0

    async def go():
        sem = asyncio.Semaphore(args.workers)
        return await asyncio.gather(*(_run_cell(f, r, e, o, args, sem) for f, r, e, o in todo))
    asyncio.run(go())
    return cmd_status(args)


# ---------------------------------------------------------------------------
# grade / status / collect
# ---------------------------------------------------------------------------

def cmd_grade(args) -> int:
    fig = args.figure
    env = None
    if args.data_root:
        env = _omd_env(Path(args.data_root))
    grade = grade_run(fig, args.range, args.spec_energy, args.run_id, env)
    rec = build_record(fig, args.range, args.spec_energy, run_id=args.run_id,
                       grade=grade, report=None,
                       meta={"arm": args.arm, "status": "graded", "source": "grade"})
    out = CAMPAIGN_DIR / args.arm / f"seed{args.seed}" / f"fig{fig}" / f"{rec['case_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2, default=str))
    print(json.dumps({k: rec[k] for k in ("case_id", "converged", "mixed_objective",
                                          "doc_per_nmi", "omd_objective", "MTOW_kg",
                                          "electric_energy_frac", "rescore_error")},
                     indent=2, default=str))
    print(f"-> {out.relative_to(DEMO_DIR)}")
    return 0


def _records(arm: str) -> dict[str, list[dict]]:
    by_seed: dict[str, list[dict]] = {}
    for p in sorted((CAMPAIGN_DIR / arm).glob("seed*/fig*/*.json")):
        by_seed.setdefault(p.parts[-3], []).append(json.loads(p.read_text()))
    return by_seed


def cmd_status(args) -> int:
    by_seed = _records(args.arm)
    if not by_seed:
        print(f"no records under {CAMPAIGN_DIR / args.arm}")
        return 1
    print(f"\n{'seed':<8} {'cells':>5} {'graded':>6} {'feas':>5} {'lost':>5} "
          f"{'noRep':>5} {'noRun':>5} {'rep>1%':>6} {'cost$':>8} {'wall_h':>6}")
    for seed, recs in sorted(by_seed.items()):
        st = [r.get("status") for r in recs]
        mism = [r for r in recs if (r.get("report_rel_err") or 0) > 0.01]
        cost = sum(r.get("cost_usd") or 0 for r in recs)
        wall = sum(r.get("wall_time_s") or 0 for r in recs) / 3600
        fallback = sum(r.get("grading") == "best_in_db" for r in recs)
        if fallback:
            print(f"  ({seed}: {fallback} cell(s) graded best_in_db, no named run)")
        print(f"{seed:<8} {len(recs):>5} {st.count('graded'):>6} "
              f"{sum(bool(r.get('converged')) for r in recs):>5} {st.count('lost'):>5} "
              f"{st.count('no_report'):>5} {st.count('no_run_named'):>5} {len(mism):>6} "
              f"{cost:>8.2f} {wall:>6.2f}")
    return 0


def cmd_collect(args) -> int:
    flags = []
    for arm in args.arms:
        for seed_dir in sorted((CAMPAIGN_DIR / arm).glob("seed*")):
            for fig_dir in sorted(seed_dir.glob("fig*")):
                flags += ["--agent", f"{arm}={fig_dir}"]
    if not flags:
        raise SystemExit("no campaign records found")
    cmd = [sys.executable, str(STATS_DIR / "collect_stats.py"), *flags, *args.extra]
    return subprocess.call(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--arm", required=True, help="arm name (e.g. the model)")
    r.add_argument("--model", default=None)
    r.add_argument("--seeds", type=int, default=1)
    r.add_argument("--seed-offset", type=int, default=0)
    r.add_argument("--figure", choices=["5", "6", "all"], default="all")
    r.add_argument("--grid", choices=["paper", "demo", "anchors"], default="demo")
    r.add_argument("--cells", nargs="*", metavar="R,E", help="restrict to these cells")
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--max-turns", type=int, default=150)
    r.add_argument("--est-cell-minutes", type=float, default=8.0)
    r.add_argument("--force", action="store_true", help="re-run cells that have a record")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--verbose", action="store_true")

    g = sub.add_parser("grade")
    g.add_argument("--arm", required=True)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--figure", choices=["5", "6"], required=True)
    g.add_argument("--range", type=float, required=True)
    g.add_argument("--spec-energy", type=float, required=True)
    g.add_argument("--run-id", required=True)
    g.add_argument("--data-root", default=None,
                   help="isolated omd data root the run lives in (default: "
                        "the ambient OMD_* environment)")

    s = sub.add_parser("status")
    s.add_argument("--arm", required=True)

    c = sub.add_parser("collect")
    c.add_argument("arms", nargs="+")
    c.add_argument("extra", nargs=argparse.REMAINDER,
                   help="further collect_stats.py flags after '--'")

    args = ap.parse_args()
    if getattr(args, "extra", None) and args.extra[:1] == ["--"]:
        args.extra = args.extra[1:]
    return {"run": cmd_run, "grade": cmd_grade, "status": cmd_status,
            "collect": cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
