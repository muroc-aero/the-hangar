"""Lane A: B738 mission with VLM drag + pyCycle HBTF surrogate propulsion.

Combines VLMDragPolar (surrogate-coupled drag) with PyCycleSurrogateGroup
(Kriging surrogate propulsion, HBTF archetype) in a B738 basic mission.
This is the reference implementation for the three-tool composition
example -- no omd factory dependency.

B738 + HBTF is a physically matched combination: a 737-class narrowbody
with a CFM56-class high-bypass turbofan.
"""

import contextlib
import io
import os
import sys

import numpy as np
import openmdao.api as om

from openconcept.utilities import Integrator, AddSubtractComp, DictIndepVarComp
from openconcept.aerodynamics import VLMDragPolar
from openconcept.mission import BasicMission

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    MISSION, VLM_CONFIG, PYC_SURR_CONFIG, ALL_REMOVES_FIELDS,
    VLM_ADDS_FIELDS, B738_OEW_KG,
)

from hangar.omd.pyc.surrogate import PyCycleSurrogateGroup


# B738 aircraft data dict (matches factory's _B738_DATA format for
# DictIndepVarComp). This is the Lane A equivalent of the factory's
# built-in template -- no omd dependency.
B738_DATA = {
    "ac|aero|CLmax_TO": {"value": 2.0},
    "ac|aero|polar|e": {"value": 0.801},
    "ac|aero|polar|CD0_TO": {"value": 0.03},
    "ac|aero|polar|CD0_cruise": {"value": 0.01925},
    "ac|geom|wing|S_ref": {"value": 124.6, "units": "m**2"},
    "ac|geom|wing|AR": {"value": 9.45},
    "ac|geom|wing|c4sweep": {"value": 25.0, "units": "deg"},
    "ac|geom|wing|taper": {"value": 0.159},
    "ac|geom|wing|toverc": {"value": 0.12},
    "ac|geom|hstab|S_ref": {"value": 32.78, "units": "m**2"},
    "ac|geom|hstab|c4_to_wing_c4": {"value": 17.9, "units": "m"},
    "ac|geom|vstab|S_ref": {"value": 26.44, "units": "m**2"},
    "ac|geom|nosegear|length": {"value": 3, "units": "ft"},
    "ac|geom|maingear|length": {"value": 4, "units": "ft"},
    "ac|weights|MTOW": {"value": 79002, "units": "kg"},
    "ac|weights|W_fuel_max": {"value": 21015, "units": "kg"},
    "ac|weights|MLW": {"value": 66349, "units": "kg"},
    "ac|propulsion|engine|rating": {"value": 27000, "units": "lbf"},
    "ac|num_passengers_max": {"value": 180},
    "ac|q_cruise": {"value": 212.662, "units": "lb*ft**-2"},
}


class B738ThreeToolModel(om.Group):
    """B738 aircraft model with VLM drag + pyCycle HBTF surrogate propulsion."""

    def initialize(self):
        self.options.declare("num_nodes", default=1)
        self.options.declare("flight_phase", default=None)

    def setup(self):
        nn = self.options["num_nodes"]

        # Propulsion: pyCycle HBTF Kriging surrogate
        self.add_subsystem(
            "propmodel",
            PyCycleSurrogateGroup(
                nn=nn,
                archetype=PYC_SURR_CONFIG["archetype"],
                design_alt=PYC_SURR_CONFIG["design_alt"],
                design_MN=PYC_SURR_CONFIG["design_MN"],
                design_Fn=PYC_SURR_CONFIG["design_Fn"],
                design_T4=PYC_SURR_CONFIG["design_T4"],
                engine_params=PYC_SURR_CONFIG.get("engine_params", {}),
            ),
            promotes_inputs=["fltcond|h", "fltcond|M", "throttle"],
            promotes_outputs=["fuel_flow", "thrust"],
        )

        # Drag: VLMDragPolar (replaces PolarDrag)
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

        # OEW: passthrough (no component weights from surrogate propulsion)
        self.add_subsystem(
            "OEW",
            om.ExecComp(
                "OEW=x",
                x={"val": 1.0, "units": "kg"},
                OEW={"val": 1.0, "units": "kg"},
            ),
            promotes_inputs=[("x", "ac|weights|OEW")],
            promotes_outputs=["OEW"],
        )

        # Fuel integration
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

        # Weight tracking
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


class B738ThreeToolAnalysis(om.Group):
    """Analysis group with both-slots-aware aircraft data."""

    def setup(self):
        nn = MISSION["num_nodes"]

        # Build IndepVarComp from B738 data, filtering slot-removed fields
        dv_comp = self.add_subsystem(
            "dv_comp", om.IndepVarComp(), promotes_outputs=["*"],
        )
        for field_name, spec in B738_DATA.items():
            if field_name not in ALL_REMOVES_FIELDS:
                kwargs = {"val": spec["value"]}
                if "units" in spec:
                    kwargs["units"] = spec["units"]
                dv_comp.add_output(field_name, **kwargs)

        # Add VLM-specific fields
        for field_name, value in VLM_ADDS_FIELDS.items():
            dv_comp.add_output(field_name, val=value)

        # Add OEW (passthrough, not in standard field set)
        dv_comp.add_output("ac|weights|OEW", val=B738_OEW_KG, units="kg")

        self.add_subsystem(
            "analysis",
            BasicMission(num_nodes=nn, aircraft_model=B738ThreeToolModel),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )


def run() -> dict:
    """Run B738 mission with VLM drag + pyCycle HBTF surrogate propulsion."""
    nn = MISSION["num_nodes"]

    prob = om.Problem(reports=False)
    prob.model = B738ThreeToolAnalysis()

    # Dual-surrogate coupling uses NLBGS with Aitken relaxation to avoid
    # the ill-conditioned Jacobian that causes Newton to diverge.
    prob.model.nonlinear_solver = om.NonlinearBlockGS(
        iprint=0, maxiter=200, atol=1e-8, rtol=1e-8,
        use_aitken=True,
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
