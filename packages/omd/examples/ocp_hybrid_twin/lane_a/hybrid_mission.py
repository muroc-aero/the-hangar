"""Lane A: Hybrid twin mission using raw OpenConcept.

Series-hybrid electric twin turboprop (King Air C90GT airframe) with
full balanced-field takeoff + climb/cruise/descent. Builds the problem
manually to match Lane B parameters exactly.
"""

import contextlib
import io
import sys
import os

import numpy as np
import openmdao.api as om

from openconcept.utilities import (
    AddSubtractComp,
    DictIndepVarComp,
    Integrator,
    LinearInterpolator,
)
from openconcept.propulsion import TwinSeriesHybridElectricPropulsionSystem
from openconcept.weights import TwinSeriesHybridEmptyWeight
from openconcept.aerodynamics import PolarDrag
from openconcept.mission import FullMissionAnalysis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import MISSION, PROPULSION

# Use the omd factory's built-in King Air template data
from hangar.omd.factories.ocp import AIRCRAFT_TEMPLATES
acdata = AIRCRAFT_TEMPLATES["kingair"]["data"]


class HybridTwinModel(om.Group):
    def initialize(self):
        self.options.declare("num_nodes", default=1)
        self.options.declare("flight_phase", default=None)

    def setup(self):
        nn = self.options["num_nodes"]
        flight_phase = self.options["flight_phase"]

        controls = self.add_subsystem("controls", om.IndepVarComp(), promotes_outputs=["*"])
        controls.add_output("proprpm", val=np.ones((nn,)) * 2000, units="rpm")

        if flight_phase in ["climb", "cruise", "descent"]:
            controls.add_output("hybridization", val=0.0)
        else:
            controls.add_output("hybridization", val=1.0)

        self.add_subsystem(
            "hybrid_factor",
            LinearInterpolator(num_nodes=nn),
            promotes_inputs=[
                ("start_val", "hybridization"),
                ("end_val", "hybridization"),
            ],
        )

        propulsion_promotes_inputs = [
            "fltcond|*", "ac|propulsion|*", "throttle",
            "propulsor_active", "ac|weights*", "duration",
        ]
        self.add_subsystem(
            "propmodel",
            TwinSeriesHybridElectricPropulsionSystem(num_nodes=nn),
            promotes_inputs=propulsion_promotes_inputs,
            promotes_outputs=["fuel_flow", "thrust"],
        )
        self.connect("proprpm", ["propmodel.prop1.rpm", "propmodel.prop2.rpm"])
        self.connect("hybrid_factor.vec", "propmodel.hybrid_split.power_split_fraction")

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
            TwinSeriesHybridEmptyWeight(),
            promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
            promotes_outputs=["OEW"],
        )
        self.connect("propmodel.propellers_weight", "W_propeller")
        self.connect("propmodel.eng1.component_weight", "W_engine")
        self.connect("propmodel.gen1.component_weight", "W_generator")
        self.connect("propmodel.motors_weight", "W_motors")

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


class HybridTwinAnalysis(om.Group):
    def setup(self):
        import copy
        nn = MISSION["num_nodes"]
        ac_data = copy.deepcopy(acdata)

        dv_comp = self.add_subsystem("dv_comp", DictIndepVarComp(ac_data), promotes_outputs=["*"])

        # Register fields
        for field in [
            "ac|aero|CLmax_TO",
            "ac|aero|polar|e",
            "ac|aero|polar|CD0_TO",
            "ac|aero|polar|CD0_cruise",
            "ac|geom|wing|S_ref",
            "ac|geom|wing|AR",
            "ac|geom|wing|c4sweep",
            "ac|geom|wing|taper",
            "ac|geom|wing|toverc",
            "ac|geom|hstab|S_ref",
            "ac|geom|hstab|c4_to_wing_c4",
            "ac|geom|vstab|S_ref",
            "ac|geom|fuselage|S_wet",
            "ac|geom|fuselage|width",
            "ac|geom|fuselage|length",
            "ac|geom|fuselage|height",
            "ac|geom|nosegear|length",
            "ac|geom|maingear|length",
            "ac|weights|MTOW",
            "ac|weights|W_fuel_max",
            "ac|weights|MLW",
            "ac|weights|W_battery",
            "ac|propulsion|engine|rating",
            "ac|propulsion|propeller|diameter",
            "ac|propulsion|motor|rating",
            "ac|propulsion|generator|rating",
            "ac|num_passengers_max",
            "ac|q_cruise",
            "ac|num_engines",
        ]:
            try:
                dv_comp.add_output_from_dict(field)
            except KeyError:
                pass

        dv_comp.add_output(
            "ac|propulsion|battery|specific_energy",
            val=PROPULSION.get("battery_specific_energy", 300),
            units="W*h/kg",
        )

        mission_data = self.add_subsystem(
            "mission_data_comp", om.IndepVarComp(), promotes_outputs=["*"],
        )
        mission_data.add_output("batt_soc_target", val=0.1, units=None)

        self.add_subsystem(
            "analysis",
            FullMissionAnalysis(num_nodes=nn, aircraft_model=HybridTwinModel),
            promotes_inputs=["*"],
            promotes_outputs=["*"],
        )

        # Weight margins
        self.add_subsystem(
            "margins",
            om.ExecComp(
                "MTOW_margin = MTOW - OEW - total_fuel - W_battery - payload",
                MTOW_margin={"units": "lbm", "val": 100},
                MTOW={"units": "lbm", "val": 10000},
                OEW={"units": "lbm", "val": 5000},
                total_fuel={"units": "lbm", "val": 1000},
                W_battery={"units": "lbm", "val": 1000},
                payload={"units": "lbm", "val": 1000},
            ),
            promotes_inputs=["payload"],
        )
        self.connect("cruise.OEW", "margins.OEW")
        self.connect("descent.fuel_used_final", "margins.total_fuel")
        self.connect("ac|weights|MTOW", "margins.MTOW")
        self.connect("ac|weights|W_battery", "margins.W_battery")

        self.add_subsystem(
            "aug_obj",
            om.ExecComp(
                "mixed_objective = fuel_burn + MTOW / 100",
                mixed_objective={"units": "kg"},
                fuel_burn={"units": "kg"},
                MTOW={"units": "kg"},
            ),
            promotes_outputs=["mixed_objective"],
        )
        self.connect("ac|weights|MTOW", "aug_obj.MTOW")
        self.connect("descent.fuel_used_final", "aug_obj.fuel_burn")


def run() -> dict:
    """Run hybrid twin mission and return key results."""
    nn = MISSION["num_nodes"]

    prob = om.Problem(reports=False)
    prob.model = HybridTwinAnalysis()
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
    vs_descent = -MISSION["descent_vs_ftmin"]
    prob.set_val("descent.fltcond|vs", np.ones((nn,)) * vs_descent, units="ft/min")
    prob.set_val("descent.fltcond|Ueas", np.ones((nn,)) * MISSION["descent_Ueas_kn"], units="kn")

    prob.set_val("cruise|h0", MISSION["cruise_altitude_ft"], units="ft")
    prob.set_val("mission_range", MISSION["mission_range_NM"], units="NM")
    prob.set_val("payload", MISSION["payload_lb"], units="lb")
    prob.set_val(
        "ac|propulsion|battery|specific_energy",
        PROPULSION["battery_specific_energy"],
        units="W*h/kg",
    )

    # Takeoff speed guesses (match factory defaults)
    prob.set_val("v0v1.fltcond|Utrue", np.ones((nn,)) * 50, units="kn")
    prob.set_val("v1vr.fltcond|Utrue", np.ones((nn,)) * 85, units="kn")
    prob.set_val("v1v0.fltcond|Utrue", np.ones((nn,)) * 85, units="kn")
    prob.set_val("v0v1.throttle", np.ones((nn,)))
    prob.set_val("v1vr.throttle", np.ones((nn,)))
    prob.set_val("rotate.throttle", np.ones((nn,)))

    # Hybridization
    prob.set_val("cruise.hybridization", MISSION["cruise_hybridization"])

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
