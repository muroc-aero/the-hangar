"""Lane A: Full King Air C90GT mission using raw OpenConcept.

Twin-turboprop full mission: balanced-field takeoff + climb/cruise/descent.
Uses the upstream OpenConcept KingAirC90GT example directly, so this lane is the
ground-truth reference the other lanes are checked against.

The upstream example bakes in its own calibration (structural_fudge 1.67,
takeoff throttle 0.75, prop rpm 1900); see shared.MISSION_FULL for the values
Lane B passes through the MCP tools to reproduce it.
"""

import contextlib
import io

import sys, os
os.environ["OPENMDAO_REPORTS"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run() -> dict:
    """Run the full King Air mission and return key results."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from openconcept.examples.KingAirC90GT import run_kingair_analysis
        prob = run_kingair_analysis(plots=False)

    fuel_burn = float(prob.get_val("descent.fuel_used_final", units="kg")[0])
    oew = float(prob.get_val("climb.OEW", units="kg")[0])
    mtow = float(prob.get_val("ac|weights|MTOW", units="kg")[0])
    tofl = float(prob.get_val("rotate.range_final", units="ft")[0])

    return {
        "fuel_burn_kg": fuel_burn,
        "OEW_kg": oew,
        "MTOW_kg": mtow,
        "TOFL_ft": tofl,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
