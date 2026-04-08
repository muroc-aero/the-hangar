"""Lane A: Caravan mission with pyCycle turbojet propulsion.

Replaces the default turboprop propulsion with a pyCycle turbojet
surrogate. This is the reference implementation for the pyCycle
propulsion slot example -- no omd dependency beyond the slot group.

Note: a turbojet is unrealistic for a Caravan; this demonstrates the
propulsion slot mechanism, not a physical aircraft design.
"""

import contextlib
import io
import os
import sys

import numpy as np
import openmdao.api as om

from openconcept.utilities import Integrator, AddSubtractComp, DictIndepVarComp
from openconcept.aerodynamics import PolarDrag
from openconcept.weights import SingleTurboPropEmptyWeight
from openconcept.mission import BasicMission
from openconcept.examples.aircraft_data.caravan import data as acdata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import MISSION, PYC_CONFIG, PYC_REMOVES_FIELDS, PYC_ADDS_FIELDS

from hangar.omd.slots import _DirectPyCyclePropGroup


class CaravanPyCycleModel(om.Group):
    """Caravan aircraft model with pyCycle turbojet propulsion."""

    def initialize(self):
        self.options.declare("num_nodes", default=1)
        self.options.declare("flight_phase", default=None)

    def setup(self):
        nn = self.options["num_nodes"]

        # pyCycle turbojet replaces turboprop propulsion (native Group)
        self.add_subsystem(
            "propmodel",
            _DirectPyCyclePropGroup(
                nn=nn,
                design_alt=PYC_CONFIG["design_alt"],
                design_MN=PYC_CONFIG["design_MN"],
                design_Fn=PYC_CONFIG["design_Fn"],
                design_T4=PYC_CONFIG["design_T4"],
                thermo_method=PYC_CONFIG["thermo_method"],
                engine_params=PYC_CONFIG.get("engine_params", {}),
            ),
            promotes_inputs=["fltcond|h", "fltcond|M", "throttle"],
            promotes_outputs=["fuel_flow", "thrust"],
        )

        # Standard drag (parabolic polar -- not using VLM here)
        flight_phase = self.options["flight_phase"]
        if flight_phase not in ["v0v1", "v1v0", "v1vr", "rotate"]:
            cd0_source = "ac|aero|polar|CD0_cruise"
        else:
            cd0_source = "ac|aero|polar|CD0_TO"

        self.add_subsystem(
            "drag",
            PolarDrag(num_nodes=nn),
            promotes_inputs=[
                "fltcond|CL",
                "ac|geom|*",
                ("CD0", cd0_source),
                "fltcond|q",
                ("e", "ac|aero|polar|e"),
            ],
            promotes_outputs=["drag"],
        )

        # Empty weight (use turboprop weight model as placeholder)
        self.add_subsystem(
            "OEW",
            SingleTurboPropEmptyWeight(),
            promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
            promotes_outputs=["OEW"],
        )

        intfuel = self.add_subsystem(
            "intfuel",
            Integrator(
                num_nodes=nn, method="simpson",
                diff_units="s", time_setup="duration",
            ),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )
        intfuel.add_integrand(
            "fuel_used", rate_name="fuel_flow", val=1.0, units="kg",
        )

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


class CaravanPyCycleAnalysis(om.Group):
    """Analysis group with pyCycle-aware aircraft data dict."""

    def setup(self):
        dv_comp = self.add_subsystem(
            "dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"],
        )

        fields = [
            "ac|aero|CLmax_TO",
            "ac|aero|polar|e",
            "ac|aero|polar|CD0_TO",
            "ac|aero|polar|CD0_cruise",
            "ac|geom|wing|S_ref", "ac|geom|wing|AR",
            "ac|geom|wing|c4sweep", "ac|geom|wing|taper",
            "ac|geom|wing|toverc",
            "ac|geom|hstab|S_ref", "ac|geom|hstab|c4_to_wing_c4",
            "ac|geom|vstab|S_ref",
            "ac|geom|fuselage|S_wet", "ac|geom|fuselage|width",
            "ac|geom|fuselage|length", "ac|geom|fuselage|height",
            "ac|geom|nosegear|length", "ac|geom|maingear|length",
            "ac|weights|MTOW", "ac|weights|W_fuel_max", "ac|weights|MLW",
            "ac|propulsion|engine|rating",
            "ac|num_passengers_max", "ac|q_cruise",
        ]
        for field in fields:
            if field not in PYC_REMOVES_FIELDS:
                dv_comp.add_output_from_dict(field)

        for field_name, value in PYC_ADDS_FIELDS.items():
            dv_comp.add_output(field_name, val=value)

        nn = MISSION["num_nodes"]
        self.add_subsystem(
            "analysis",
            BasicMission(num_nodes=nn, aircraft_model=CaravanPyCycleModel),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )


def run() -> dict:
    """Run Caravan mission with pyCycle turbojet and return key results."""
    nn = MISSION["num_nodes"]

    prob = om.Problem(reports=False)
    prob.model = CaravanPyCycleAnalysis()
    prob.model.nonlinear_solver = om.NewtonSolver(
        iprint=2, solve_subsystems=True,
    )
    prob.model.linear_solver = om.DirectSolver()
    prob.model.nonlinear_solver.options["maxiter"] = 30
    prob.model.nonlinear_solver.options["atol"] = 1e-8
    prob.model.nonlinear_solver.options["rtol"] = 1e-8
    prob.model.nonlinear_solver.linesearch = om.BoundsEnforceLS(
        bound_enforcement="scalar", print_bound_enforce=False,
    )
    prob.setup(check=False, mode="fwd")

    prob.set_val(
        "climb.fltcond|vs",
        np.ones((nn,)) * MISSION["climb_vs_ftmin"], units="ft/min",
    )
    prob.set_val(
        "climb.fltcond|Ueas",
        np.ones((nn,)) * MISSION["climb_Ueas_kn"], units="kn",
    )
    prob.set_val(
        "cruise.fltcond|vs", np.ones((nn,)) * 0.01, units="ft/min",
    )
    prob.set_val(
        "cruise.fltcond|Ueas",
        np.ones((nn,)) * MISSION["cruise_Ueas_kn"], units="kn",
    )
    prob.set_val(
        "descent.fltcond|vs",
        np.ones((nn,)) * (-MISSION["descent_vs_ftmin"]), units="ft/min",
    )
    prob.set_val(
        "descent.fltcond|Ueas",
        np.ones((nn,)) * MISSION["descent_Ueas_kn"], units="kn",
    )
    prob.set_val("cruise|h0", MISSION["cruise_altitude_ft"], units="ft")
    prob.set_val("mission_range", MISSION["mission_range_NM"], units="NM")

    prob.run_model()

    fuel_burn = float(prob.get_val("descent.fuel_used_final", units="kg")[0])
    oew = float(prob.get_val("climb.OEW", units="kg")[0])
    mtow = float(prob.get_val("ac|weights|MTOW", units="kg")[0])

    return {
        "fuel_burn_kg": fuel_burn,
        "OEW_kg": oew,
        "MTOW_kg": mtow,
    }


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result, indent=2))
