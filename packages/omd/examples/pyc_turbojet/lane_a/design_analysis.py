"""Lane A -- Direct pyCycle API: design-point analysis.

Builds and runs a single-spool turbojet at the design point using the
raw pyCycle/OpenMDAO API via omd's self-contained archetype classes.
Returns a flat dict of results that can be compared against Lane B (omd pipeline).
"""

from __future__ import annotations

import os
os.environ.setdefault("OPENMDAO_REPORTS", "0")

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openmdao.api as om

from hangar.omd.pyc.archetypes import Turbojet
from shared import ENGINE_PARAMS, DESIGN_POINT, DESIGN_GUESSES


def run() -> dict:
    """Run design-point analysis, return flat results dict."""
    prob = om.Problem(reports=False)
    prob.model = Turbojet(params=ENGINE_PARAMS)
    prob.setup(check=False)

    prob.set_val("fc.alt", DESIGN_POINT["alt"], units="ft")
    prob.set_val("fc.MN", DESIGN_POINT["MN"])
    prob.set_val("comp.PR", ENGINE_PARAMS["comp_PR"])
    prob.set_val("comp.eff", ENGINE_PARAMS["comp_eff"])
    prob.set_val("turb.eff", ENGINE_PARAMS["turb_eff"])
    prob.set_val("Nmech", ENGINE_PARAMS["Nmech"], units="rpm")
    prob.set_val("balance.Fn_target", DESIGN_POINT["Fn_target"], units="lbf")
    prob.set_val("balance.T4_target", DESIGN_POINT["T4_target"], units="degR")

    prob["balance.FAR"] = DESIGN_GUESSES["FAR"]
    prob["balance.W"] = DESIGN_GUESSES["W"]
    prob["balance.turb_PR"] = DESIGN_GUESSES["turb_PR"]
    prob["fc.balance.Pt"] = DESIGN_GUESSES["fc_Pt"]
    prob["fc.balance.Tt"] = DESIGN_GUESSES["fc_Tt"]

    prob.set_solver_print(level=-1)
    prob.run_model()

    return {
        "Fn": float(prob["perf.Fn"][0]),
        "TSFC": float(prob["perf.TSFC"][0]),
        "OPR": float(prob["perf.OPR"][0]),
        "Fg": float(prob["perf.Fg"][0]),
        "W": float(prob["inlet.Fl_O:stat:W"][0]),
        "comp.PR": float(prob["comp.PR"][0]),
        "comp.eff": float(prob["comp.eff"][0]),
        "turb.PR": float(prob["turb.PR"][0]),
        "turb.eff": float(prob["turb.eff"][0]),
        "shaft.Nmech": float(prob["shaft.Nmech"][0]),
        "burner.Fl_O:tot:T": float(prob["burner.Fl_O:tot:T"][0]),
        "comp.Fl_O:tot:P": float(prob["comp.Fl_O:tot:P"][0]),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
