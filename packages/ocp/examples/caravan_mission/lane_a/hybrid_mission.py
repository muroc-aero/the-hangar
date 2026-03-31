"""Lane A: Hybrid Twin mission using raw OpenConcept.

Series-hybrid electric twin turboprop (King Air C90GT airframe) with
full balanced-field takeoff + climb/cruise/descent.
Uses the upstream OpenConcept HybridTwin example directly.
"""

import contextlib
import io

import sys, os
os.environ["OPENMDAO_REPORTS"] = "0"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import HYBRID_MISSION


def run() -> dict:
    """Run hybrid twin mission and return key results."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from openconcept.examples.HybridTwin import run_hybrid_twin_analysis
        prob = run_hybrid_twin_analysis(plots=False)

    fuel_burn = float(prob.get_val("descent.fuel_used_final", units="kg")[0])
    oew = float(prob.get_val("climb.OEW", units="kg")[0])
    mtow = float(prob.get_val("ac|weights|MTOW", units="kg")[0])
    tofl = float(prob.get_val("rotate.range_final", units="ft")[0])
    batt_soc = float(prob.get_val("descent.propmodel.batt1.SOC_final")[0])
    cruise_hyb = float(prob.get_val("cruise.hybridization")[0])

    return {
        "fuel_burn_kg": fuel_burn,
        "OEW_kg": oew,
        "MTOW_kg": mtow,
        "TOFL_ft": tofl,
        "battery_SOC_final": batt_soc,
        "cruise_hybridization": cruise_hyb,
    }


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result, indent=2))
