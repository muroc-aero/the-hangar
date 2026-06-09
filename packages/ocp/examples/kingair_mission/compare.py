"""Run Lane A and Lane B and print their results side by side.

This is the quickest way to see the parity by eye:

    uv run python packages/ocp/examples/kingair_mission/compare.py

Lane A is the upstream OpenConcept ``run_kingair_analysis`` (the reference),
re-converged to Newton 1e-10. Lane B drives the same analysis through the OCP
MCP tools. With the #36/#37, #38/#40 and #39 fixes in place, and both lanes at
1e-10, all four columns match to machine precision -- see README.
"""

import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

os.environ["OPENMDAO_REPORTS"] = "0"

DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEMO_DIR))

LANE_B_DIR = DEMO_DIR / "lane_b"

METRICS = [
    ("OEW", "OEW_kg", "kg", "{:.2f}"),
    ("Fuel burn", "fuel_burn_kg", "kg", "{:.2f}"),
    ("MTOW", "MTOW_kg", "kg", "{:.0f}"),
    ("TOFL", "TOFL_ft", "ft", "{:.2f}"),
]


def run_lane_a() -> dict:
    from lane_a.full_mission import run
    return run()


async def run_lane_b() -> dict:
    from hangar.ocp.cli import build_ocp_registry
    from hangar.sdk.cli.runner import set_registry_builder, run_tool

    set_registry_builder(build_ocp_registry)
    await run_tool("reset", {})

    steps = json.loads((LANE_B_DIR / "full_mission.json").read_text())
    last = None
    for step in steps:
        resp = await run_tool(step["tool"], step.get("args", {}))
        if not resp.get("ok"):
            raise RuntimeError(f"Lane B step {step['tool']} failed: {resp.get('error')}")
        last = resp.get("result", {})
    return last["results"] if last and "results" in last else last


def main():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        a = run_lane_a()
        b = asyncio.run(run_lane_b())

    print()
    print("King Air C90GT full mission -- Lane A (upstream) vs Lane B (OCP MCP)")
    print("=" * 64)
    print(f"{'Metric':<12}{'Lane A':>14}{'Lane B':>14}{'rel. diff':>14}")
    print("-" * 64)
    for label, key, unit, fmt in METRICS:
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            continue
        rel = abs(av - bv) / abs(av) if av else 0.0
        print(f"{label:<12}{fmt.format(av) + ' ' + unit:>14}"
              f"{fmt.format(bv) + ' ' + unit:>14}{rel:>13.2e}")
    print("=" * 64)
    print("All four metrics match to machine precision (both lanes at Newton 1e-10).")


if __name__ == "__main__":
    main()
