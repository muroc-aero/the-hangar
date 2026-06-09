"""Run Lane A and Lane B and print their results side by side.

    uv run python packages/ocp/examples/b738_mission/compare.py

Lane A is the upstream OpenConcept ``run_738_analysis`` (the reference).
Lane B drives the same aircraft through the OCP MCP tools. Unlike the King Air
demo, the two columns do **not** match exactly: the upstream script ramps each
phase speed and flies the reserve at jet speeds, while the MCP tools fly
constant per-phase speeds and default the reserve speeds to GA values. Expect
block fuel within a few percent and a larger gap on the reserve total. See
README.md for the full explanation.
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
    ("Block fuel", "fuel_burn_kg", "kg", "{:.1f}"),
    ("Total fuel", "total_fuel_with_reserve_kg", "kg", "{:.1f}"),
    ("OEW", "OEW_kg", "kg", "{:.0f}"),
    ("MTOW", "MTOW_kg", "kg", "{:.0f}"),
]


def run_lane_a() -> dict:
    from lane_a.reserve_mission import run
    return run()


async def run_lane_b() -> dict:
    from hangar.ocp.cli import build_ocp_registry
    from hangar.sdk.cli.runner import set_registry_builder, run_tool

    set_registry_builder(build_ocp_registry)
    await run_tool("reset", {})

    steps = json.loads((LANE_B_DIR / "reserve_mission.json").read_text())
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
    print("Boeing 737-800 reserve mission -- Lane A (upstream) vs Lane B (OCP MCP)")
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
    print("Block fuel matches to a few percent; the reserve total diverges more")
    print("because configure_mission can't set the reserve-phase jet speeds.")


if __name__ == "__main__":
    main()
