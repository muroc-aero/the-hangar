"""Lane A: Full Caravan mission using raw OpenConcept.

Full mission with balanced-field takeoff + climb/cruise/descent.
Uses the upstream OpenConcept Caravan example directly.
"""

import contextlib
import io

import sys, os
os.environ["OPENMDAO_REPORTS"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import MISSION_FULL


def run() -> dict:
    """Run full Caravan mission (with takeoff) and return key results."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from openconcept.examples.Caravan import run_caravan_analysis
        prob = run_caravan_analysis()

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
    result = run()
    print(json.dumps(result, indent=2))
