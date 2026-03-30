"""Lane B: Run all three JSON scripts in-process and print a summary.

Can also be run via CLI:
    uv run ocp-cli run-script lane_b/basic_mission.json --pretty
"""

import asyncio
import json
from pathlib import Path


SCRIPTS = ["basic_mission", "full_mission", "hybrid_mission"]
SCRIPT_DIR = Path(__file__).parent


def _ensure_registry():
    """Wire the OCP tool registry so run_tool() works outside ocp-cli."""
    from hangar.ocp.cli import build_ocp_registry
    from hangar.sdk.cli.runner import set_registry_builder
    set_registry_builder(build_ocp_registry)


async def run_all() -> dict:
    """Execute all Lane B scripts in-process, return dict of results."""
    from hangar.sdk.cli.runner import run_tool
    _ensure_registry()

    all_results = {}
    for name in SCRIPTS:
        # Reset between analyses
        await run_tool("reset", {})

        script_path = SCRIPT_DIR / f"{name}.json"
        steps = json.loads(script_path.read_text())
        last_result = None
        for step in steps:
            resp = await run_tool(step["tool"], step.get("args", {}))
            if not resp.get("ok"):
                print(f"ERROR in {name}/{step['tool']}: {resp.get('error')}")
                break
            last_result = resp.get("result", {})

        # Extract the results payload from the envelope
        if last_result and "results" in last_result:
            all_results[name] = last_result["results"]
        else:
            all_results[name] = last_result

    return all_results


def main():
    results = asyncio.run(run_all())
    for name, r in results.items():
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        if r is None:
            print("  FAILED")
            continue
        if "fuel_burn_kg" in r:
            print(f"  Fuel burn: {r['fuel_burn_kg']:.2f} kg")
        if "OEW_kg" in r:
            print(f"  OEW: {r['OEW_kg']:.1f} kg")
        if "MTOW_kg" in r:
            print(f"  MTOW: {r['MTOW_kg']:.0f} kg")
        if "TOFL_ft" in r:
            print(f"  TOFL: {r['TOFL_ft']:.0f} ft")
        if "battery_SOC_final" in r:
            print(f"  Battery SOC: {r['battery_SOC_final']:.3f}")
        if "MTOW_margin_lb" in r:
            print(f"  MTOW margin: {r['MTOW_margin_lb']:.0f} lb")


if __name__ == "__main__":
    main()
