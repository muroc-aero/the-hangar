"""Lane A: Caravan mission with VLMDragPolar using raw OpenConcept.

Replaces PolarDrag with OpenAeroStruct's VLMDragPolar in each
flight phase. This is the reference implementation for the coupled
OCP+OAS slot example -- no omd dependency.
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
from openconcept.aerodynamics import VLMDragPolar
from openconcept.mission import BasicMission
from openconcept.examples.aircraft_data.caravan import data as acdata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import MISSION, VLM_CONFIG, VLM_REMOVES_FIELDS, VLM_ADDS_FIELDS


class CaravanVLMModel(om.Group):
    """Caravan aircraft model with VLM drag instead of parabolic polar."""

    def initialize(self):
        self.options.declare("num_nodes", default=1)
        self.options.declare("flight_phase", default=None)

    def setup(self):
        nn = self.options["num_nodes"]

        controls = self.add_subsystem(
            "controls", om.IndepVarComp(), promotes_outputs=["*"],
        )
        controls.add_output("prop1rpm", val=np.ones((nn,)) * 2000, units="rpm")

        self.add_subsystem(
            "propmodel",
            TurbopropPropulsionSystem(num_nodes=nn),
            promotes_inputs=["fltcond|*", "ac|propulsion|*", "throttle"],
            promotes_outputs=["fuel_flow", "thrust"],
        )
        self.connect("prop1rpm", "propmodel.prop1.rpm")

        # VLMDragPolar replaces PolarDrag
        self.add_subsystem(
            "drag",
            VLMDragPolar(
                num_nodes=nn,
                num_x=VLM_CONFIG["num_x"],
                num_y=VLM_CONFIG["num_y"],
                num_twist=VLM_CONFIG["num_twist"],
            ),
            promotes_inputs=[
                "fltcond|CL", "fltcond|M", "fltcond|h", "fltcond|q",
                "ac|geom|wing|S_ref", "ac|geom|wing|AR",
                "ac|geom|wing|taper", "ac|geom|wing|c4sweep",
                "ac|geom|wing|twist", "ac|aero|CD_nonwing",
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


class CaravanVLMAnalysis(om.Group):
    """Analysis group with VLM-aware aircraft data dict."""

    def setup(self):
        nn = MISSION["num_nodes"]
        dv_comp = self.add_subsystem(
            "dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"],
        )

        # Standard fields, excluding those replaced by VLM
        fields = [
            "ac|aero|CLmax_TO",
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
            "ac|propulsion|propeller|diameter",
            "ac|num_passengers_max", "ac|q_cruise",
        ]
        for field in fields:
            if field not in VLM_REMOVES_FIELDS:
                dv_comp.add_output_from_dict(field)

        # Add VLM-specific fields
        for field_name, value in VLM_ADDS_FIELDS.items():
            dv_comp.add_output(field_name, val=value)

        self.add_subsystem(
            "analysis",
            BasicMission(num_nodes=nn, aircraft_model=CaravanVLMModel),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )


def run() -> dict:
    """Run Caravan mission with VLM drag and return key results."""
    nn = MISSION["num_nodes"]

    prob = om.Problem(reports=False)
    prob.model = CaravanVLMAnalysis()
    prob.model.nonlinear_solver = om.NewtonSolver(
        iprint=0, solve_subsystems=True,
    )
    prob.model.linear_solver = om.DirectSolver()
    prob.model.nonlinear_solver.options["maxiter"] = 20
    prob.model.nonlinear_solver.options["atol"] = 1e-10
    prob.model.nonlinear_solver.options["rtol"] = 1e-10
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

    with contextlib.redirect_stdout(io.StringIO()), \
         contextlib.redirect_stderr(io.StringIO()):
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
