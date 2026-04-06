"""Lane A: Full Caravan mission using raw OpenConcept.

Full mission with balanced-field takeoff + climb/cruise/descent.
Builds the problem manually with the same parameters as Lane B.
"""

import contextlib
import io
import sys
import os

import numpy as np
import openmdao.api as om

from openconcept.utilities import Integrator, AddSubtractComp, DictIndepVarComp
from openconcept.propulsion import TurbopropPropulsionSystem
from openconcept.weights import SingleTurboPropEmptyWeight
from openconcept.aerodynamics import PolarDrag
from openconcept.mission import FullMissionAnalysis
from openconcept.examples.aircraft_data.caravan import data as acdata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import MISSION


class CaravanModel(om.Group):
    def initialize(self):
        self.options.declare("num_nodes", default=1)
        self.options.declare("flight_phase", default=None)

    def setup(self):
        nn = self.options["num_nodes"]
        flight_phase = self.options["flight_phase"]

        controls = self.add_subsystem("controls", om.IndepVarComp(), promotes_outputs=["*"])
        controls.add_output("prop1rpm", val=np.ones((nn,)) * 2000, units="rpm")

        self.add_subsystem(
            "propmodel",
            TurbopropPropulsionSystem(num_nodes=nn),
            promotes_inputs=["fltcond|*", "ac|propulsion|*", "throttle"],
            promotes_outputs=["fuel_flow", "thrust"],
        )
        self.connect("prop1rpm", "propmodel.prop1.rpm")

        if flight_phase not in ["v0v1", "v1v0", "v1vr", "rotate"]:
            cd0_source = "ac|aero|polar|CD0_cruise"
        else:
            cd0_source = "ac|aero|polar|CD0_TO"

        self.add_subsystem(
            "drag",
            PolarDrag(num_nodes=nn),
            promotes_inputs=[
                "fltcond|CL", "ac|geom|*",
                ("CD0", cd0_source), "fltcond|q",
                ("e", "ac|aero|polar|e"),
            ],
            promotes_outputs=["drag"],
        )

        self.add_subsystem(
            "OEW",
            SingleTurboPropEmptyWeight(),
            promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
            promotes_outputs=["OEW"],
        )
        self.connect("propmodel.prop1.component_weight", "W_propeller")
        self.connect("propmodel.eng1.component_weight", "W_engine")

        intfuel = self.add_subsystem(
            "intfuel",
            Integrator(num_nodes=nn, method="simpson", diff_units="s", time_setup="duration"),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )
        intfuel.add_integrand("fuel_used", rate_name="fuel_flow", val=1.0, units="kg")

        self.add_subsystem(
            "weight",
            AddSubtractComp(
                output_name="weight",
                input_names=["ac|weights|MTOW", "fuel_used"],
                units="kg",
                vec_size=[1, nn],
                scaling_factors=[1, -1],
            ),
            promotes_inputs=["*"],
            promotes_outputs=["weight"],
        )


class CaravanFullAnalysis(om.Group):
    def setup(self):
        nn = MISSION["num_nodes"]
        dv_comp = self.add_subsystem("dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"])
        dv_comp.add_output_from_dict("ac|aero|CLmax_TO")
        dv_comp.add_output_from_dict("ac|aero|polar|e")
        dv_comp.add_output_from_dict("ac|aero|polar|CD0_TO")
        dv_comp.add_output_from_dict("ac|aero|polar|CD0_cruise")
        dv_comp.add_output_from_dict("ac|geom|wing|S_ref")
        dv_comp.add_output_from_dict("ac|geom|wing|AR")
        dv_comp.add_output_from_dict("ac|geom|wing|c4sweep")
        dv_comp.add_output_from_dict("ac|geom|wing|taper")
        dv_comp.add_output_from_dict("ac|geom|wing|toverc")
        dv_comp.add_output_from_dict("ac|geom|hstab|S_ref")
        dv_comp.add_output_from_dict("ac|geom|hstab|c4_to_wing_c4")
        dv_comp.add_output_from_dict("ac|geom|vstab|S_ref")
        dv_comp.add_output_from_dict("ac|geom|fuselage|S_wet")
        dv_comp.add_output_from_dict("ac|geom|fuselage|width")
        dv_comp.add_output_from_dict("ac|geom|fuselage|length")
        dv_comp.add_output_from_dict("ac|geom|fuselage|height")
        dv_comp.add_output_from_dict("ac|geom|nosegear|length")
        dv_comp.add_output_from_dict("ac|geom|maingear|length")
        dv_comp.add_output_from_dict("ac|weights|MTOW")
        dv_comp.add_output_from_dict("ac|weights|W_fuel_max")
        dv_comp.add_output_from_dict("ac|weights|MLW")
        dv_comp.add_output_from_dict("ac|propulsion|engine|rating")
        dv_comp.add_output_from_dict("ac|propulsion|propeller|diameter")
        dv_comp.add_output_from_dict("ac|num_passengers_max")
        dv_comp.add_output_from_dict("ac|q_cruise")

        self.add_subsystem(
            "analysis",
            FullMissionAnalysis(num_nodes=nn, aircraft_model=CaravanModel),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )


def run() -> dict:
    """Run full Caravan mission and return key results."""
    nn = MISSION["num_nodes"]

    prob = om.Problem(reports=False)
    prob.model = CaravanFullAnalysis()
    prob.model.nonlinear_solver = om.NewtonSolver(iprint=0, solve_subsystems=True)
    prob.model.linear_solver = om.DirectSolver()
    prob.model.nonlinear_solver.options["maxiter"] = 20
    prob.model.nonlinear_solver.options["atol"] = 1e-10
    prob.model.nonlinear_solver.options["rtol"] = 1e-10
    prob.model.nonlinear_solver.linesearch = om.BoundsEnforceLS(
        bound_enforcement="scalar", print_bound_enforce=False,
    )
    prob.setup(check=False, mode="fwd")

    # Phase speeds
    prob.set_val("climb.fltcond|vs", np.ones((nn,)) * MISSION["climb_vs_ftmin"], units="ft/min")
    prob.set_val("climb.fltcond|Ueas", np.ones((nn,)) * MISSION["climb_Ueas_kn"], units="kn")
    prob.set_val("cruise.fltcond|vs", np.ones((nn,)) * 0.01, units="ft/min")
    prob.set_val("cruise.fltcond|Ueas", np.ones((nn,)) * MISSION["cruise_Ueas_kn"], units="kn")
    prob.set_val("descent.fltcond|vs", np.ones((nn,)) * (-MISSION["descent_vs_ftmin"]), units="ft/min")
    prob.set_val("descent.fltcond|Ueas", np.ones((nn,)) * MISSION["descent_Ueas_kn"], units="kn")

    prob.set_val("cruise|h0", MISSION["cruise_altitude_ft"], units="ft")
    prob.set_val("mission_range", MISSION["mission_range_NM"], units="NM")

    # Takeoff speed guesses (match factory defaults)
    prob.set_val("v0v1.fltcond|Utrue", np.ones((nn,)) * 50, units="kn")
    prob.set_val("v1vr.fltcond|Utrue", np.ones((nn,)) * 85, units="kn")
    prob.set_val("v1v0.fltcond|Utrue", np.ones((nn,)) * 85, units="kn")
    prob.set_val("rotate.fltcond|Utrue", np.ones((nn,)) * 80, units="kn")
    prob.set_val("v0v1.throttle", np.ones((nn,)))
    prob.set_val("v1vr.throttle", np.ones((nn,)))
    prob.set_val("rotate.throttle", np.ones((nn,)))

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        prob.run_model()

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
