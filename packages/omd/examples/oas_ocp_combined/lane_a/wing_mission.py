"""Lane A: OAS wing aero + OCP mission using raw OpenMDAO composition.

Builds an OAS AeroPoint and an OCP BasicMission AnalysisGroup as
separate subsystems in one Problem, mirroring what the multi-component
materializer does. No omd dependency beyond the OCP factory data.
"""

import contextlib
import copy
import io
import sys
import os

import numpy as np
import openmdao.api as om

from openaerostruct.meshing.mesh_generator import generate_mesh
from openaerostruct.aerodynamics.aero_groups import AeroPoint
from openaerostruct.geometry.geometry_group import Geometry

from openconcept.utilities import (
    AddSubtractComp,
    DictIndepVarComp,
    Integrator,
)
from openconcept.propulsion import TurbopropPropulsionSystem
from openconcept.weights import SingleTurboPropEmptyWeight
from openconcept.aerodynamics import PolarDrag
from openconcept.mission import BasicMission
from openconcept.examples.aircraft_data.caravan import data as acdata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import WING, FLIGHT, MISSION


# ---- OAS wing setup ----

def _build_oas_wing_group() -> tuple[om.Group, dict]:
    """Build an OAS aero-only wing group (same as oas_aero factory)."""
    mesh_dict = {
        "num_x": WING["num_x"],
        "num_y": WING["num_y"],
        "wing_type": WING["wing_type"],
        "symmetry": WING["symmetry"],
        "span": WING["span"],
        "root_chord": WING["root_chord"],
        "span_cos_spacing": 0.0,
        "chord_cos_spacing": 0.0,
    }
    mesh = generate_mesh(mesh_dict)
    if isinstance(mesh, tuple):
        mesh = mesh[0]

    surface = {
        "name": WING["name"],
        "mesh": mesh,
        "symmetry": WING["symmetry"],
        "S_ref_type": "wetted",
        "CL0": 0.0,
        "CD0": WING["CD0"],
        "k_lam": 0.05,
        "t_over_c_cp": np.array([0.15]),
        "c_max_t": 0.303,
        "with_viscous": WING["with_viscous"],
        "with_wave": False,
    }

    group = om.Group()

    indep = om.IndepVarComp()
    indep.add_output("v", val=FLIGHT["velocity"], units="m/s")
    indep.add_output("alpha", val=FLIGHT["alpha"], units="deg")
    indep.add_output("beta", val=0.0, units="deg")
    indep.add_output("Mach_number", val=FLIGHT["Mach_number"])
    indep.add_output("re", val=FLIGHT["re"], units="1/m")
    indep.add_output("rho", val=FLIGHT["rho"], units="kg/m**3")
    indep.add_output("cg", val=np.zeros(3), units="m")

    group.add_subsystem(
        "prob_vars", indep,
        promotes=["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"],
    )
    group.add_subsystem(WING["name"], Geometry(surface=surface))
    group.add_subsystem(
        "aero_point_0",
        AeroPoint(surfaces=[surface]),
        promotes_inputs=[
            "v", "alpha", "beta", "Mach_number", "re", "rho", "cg",
        ],
    )

    name = WING["name"]
    group.connect(f"{name}.mesh", f"aero_point_0.{name}.def_mesh")
    group.connect(f"{name}.mesh", f"aero_point_0.aero_states.{name}_def_mesh")
    group.connect(f"{name}.t_over_c", f"aero_point_0.{name}_perf.t_over_c")

    return group, surface


# ---- OCP mission setup ----

class CaravanModel(om.Group):
    def initialize(self):
        self.options.declare("num_nodes", default=1)
        self.options.declare("flight_phase", default=None)

    def setup(self):
        nn = self.options["num_nodes"]

        controls = self.add_subsystem("controls", om.IndepVarComp(), promotes_outputs=["*"])
        controls.add_output("prop1rpm", val=np.ones((nn,)) * 2000, units="rpm")

        self.add_subsystem(
            "propmodel",
            TurbopropPropulsionSystem(num_nodes=nn),
            promotes_inputs=["fltcond|*", "ac|propulsion|*", "throttle"],
            promotes_outputs=["fuel_flow", "thrust"],
        )
        self.connect("prop1rpm", "propmodel.prop1.rpm")

        self.add_subsystem(
            "drag", PolarDrag(num_nodes=nn),
            promotes_inputs=[
                "fltcond|CL", "ac|geom|*",
                ("CD0", "ac|aero|polar|CD0_cruise"), "fltcond|q",
                ("e", "ac|aero|polar|e"),
            ],
            promotes_outputs=["drag"],
        )

        self.add_subsystem(
            "OEW", SingleTurboPropEmptyWeight(),
            promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
            promotes_outputs=["OEW"],
        )
        self.connect("propmodel.prop1.component_weight", "W_propeller")
        self.connect("propmodel.eng1.component_weight", "W_engine")

        intfuel = self.add_subsystem(
            "intfuel",
            Integrator(num_nodes=nn, method="simpson", diff_units="s", time_setup="duration"),
            promotes_inputs=["*"], promotes_outputs=["*"],
        )
        intfuel.add_integrand("fuel_used", rate_name="fuel_flow", val=1.0, units="kg")

        self.add_subsystem(
            "weight",
            AddSubtractComp(
                output_name="weight",
                input_names=["ac|weights|MTOW", "fuel_used"],
                units="kg", vec_size=[1, nn], scaling_factors=[1, -1],
            ),
            promotes_inputs=["*"], promotes_outputs=["weight"],
        )


def _build_ocp_mission_group() -> om.Group:
    """Build an OCP BasicMission AnalysisGroup."""
    nn = MISSION["num_nodes"]

    class AnalysisGroup(om.Group):
        def setup(self):
            dv_comp = self.add_subsystem("dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"])
            for field in [
                "ac|aero|CLmax_TO", "ac|aero|polar|e",
                "ac|aero|polar|CD0_TO", "ac|aero|polar|CD0_cruise",
                "ac|geom|wing|S_ref", "ac|geom|wing|AR",
                "ac|geom|wing|c4sweep", "ac|geom|wing|taper", "ac|geom|wing|toverc",
                "ac|geom|hstab|S_ref", "ac|geom|hstab|c4_to_wing_c4",
                "ac|geom|vstab|S_ref",
                "ac|geom|fuselage|S_wet", "ac|geom|fuselage|width",
                "ac|geom|fuselage|length", "ac|geom|fuselage|height",
                "ac|geom|nosegear|length", "ac|geom|maingear|length",
                "ac|weights|MTOW", "ac|weights|W_fuel_max", "ac|weights|MLW",
                "ac|propulsion|engine|rating", "ac|propulsion|propeller|diameter",
                "ac|num_passengers_max", "ac|q_cruise",
            ]:
                dv_comp.add_output_from_dict(field)
            self.add_subsystem(
                "analysis",
                BasicMission(num_nodes=nn, aircraft_model=CaravanModel),
                promotes_inputs=["*"], promotes_outputs=["*"],
            )

    group = AnalysisGroup()
    group.nonlinear_solver = om.NewtonSolver(iprint=0, solve_subsystems=True)
    group.linear_solver = om.DirectSolver()
    group.nonlinear_solver.options["maxiter"] = 20
    group.nonlinear_solver.options["atol"] = 1e-10
    group.nonlinear_solver.options["rtol"] = 1e-10
    group.nonlinear_solver.linesearch = om.BoundsEnforceLS(
        bound_enforcement="scalar", print_bound_enforce=False,
    )
    return group


# ---- Compose and run ----

def run() -> dict:
    """Run OAS wing + OCP mission in one composite Problem."""
    nn = MISSION["num_nodes"]

    wing_group, surface = _build_oas_wing_group()
    mission_group = _build_ocp_mission_group()

    prob = om.Problem(reports=False)
    prob.model.add_subsystem("wing", wing_group)
    prob.model.add_subsystem("mission", mission_group)
    prob.setup(check=False, mode="fwd")

    # Set OCP mission values
    prob.set_val("mission.climb.fltcond|vs", np.ones((nn,)) * MISSION["climb_vs_ftmin"], units="ft/min")
    prob.set_val("mission.climb.fltcond|Ueas", np.ones((nn,)) * MISSION["climb_Ueas_kn"], units="kn")
    prob.set_val("mission.cruise.fltcond|vs", np.ones((nn,)) * 0.01, units="ft/min")
    prob.set_val("mission.cruise.fltcond|Ueas", np.ones((nn,)) * MISSION["cruise_Ueas_kn"], units="kn")
    prob.set_val("mission.descent.fltcond|vs", np.ones((nn,)) * (-MISSION["descent_vs_ftmin"]), units="ft/min")
    prob.set_val("mission.descent.fltcond|Ueas", np.ones((nn,)) * MISSION["descent_Ueas_kn"], units="kn")
    prob.set_val("mission.cruise|h0", MISSION["cruise_altitude_ft"], units="ft")
    prob.set_val("mission.mission_range", MISSION["mission_range_NM"], units="NM")

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        prob.run_model()

    # Extract results
    wing_cd = float(prob.get_val("wing.aero_point_0.wing_perf.CD")[0])
    wing_cl = float(prob.get_val("wing.aero_point_0.wing_perf.CL")[0])
    fuel_burn = float(prob.get_val("mission.descent.fuel_used_final", units="kg")[0])
    oew = float(prob.get_val("mission.climb.OEW", units="kg")[0])

    return {
        "wing_CL": wing_cl,
        "wing_CD": wing_cd,
        "wing_L_over_D": wing_cl / wing_cd if wing_cd > 0 else 0,
        "fuel_burn_kg": fuel_burn,
        "OEW_kg": oew,
        "MTOW_kg": float(prob.get_val("mission.ac|weights|MTOW", units="kg")[0]),
    }


if __name__ == "__main__":
    import json
    result = run()
    print(json.dumps(result, indent=2))
