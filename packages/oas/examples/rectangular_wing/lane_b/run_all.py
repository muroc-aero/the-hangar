"""Lane B: Run all four JSON scripts in-process and print a summary.

Can also be run via CLI:
    uv run oas-cli run-script lane_b/aero_analysis.json --pretty

Migrated from: upstream/OpenAeroStruct/oas_mcp/demonstrations/rectangular_wing/lane_b/run_all.py
"""

import asyncio
import json
from pathlib import Path


SCRIPTS = ["aero_analysis", "drag_polar", "opt_twist", "opt_chord"]
SCRIPT_DIR = Path(__file__).parent


def _ensure_registry():
    """Wire the OAS tool registry so run_tool() works outside oas-cli."""
    from hangar.oas.cli import build_oas_registry
    from hangar.sdk.cli.runner import set_registry_builder
    set_registry_builder(build_oas_registry)


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
        if "CL" in r and not isinstance(r["CL"], list):
            print(f"  CL = {r['CL']:.6f}")
        if "CD" in r and not isinstance(r["CD"], list):
            print(f"  CD = {r['CD']:.6f}")
        if "L_over_D" in r and not isinstance(r.get("L_over_D"), list):
            print(f"  L/D = {r['L_over_D']:.2f}")
        if "best_L_over_D" in r:
            best = r["best_L_over_D"]
            print(f"  Best L/D = {best['L_over_D']:.2f} at alpha = {best['alpha_deg']:.1f} deg")
        if "success" in r:
            print(f"  Optimisation converged: {r['success']}")
        if "optimized_design_variables" in r:
            for dv, val in r["optimized_design_variables"].items():
                print(f"  {dv} = {val}")


if __name__ == "__main__":
    main()
