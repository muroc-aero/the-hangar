"""Evaluation test: Multi-lane demonstration (Eval).

Side-by-side comparison: Lane A (direct OpenMDAO/OAS script) vs
Lane B (omd plan pipeline) for each problem type. Generates
JSON manifests documenting the comparison.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import openmdao.api as om
import pytest

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan

pytestmark = [pytest.mark.eval]

FIXTURES = Path(__file__).parent / "fixtures"


def _lane_report(
    name: str,
    lane_a_results: dict,
    lane_b_results: dict,
    tolerances: dict,
    tmp_path: Path,
) -> dict:
    """Build and write a multi-lane comparison manifest."""
    comparison = {}
    all_pass = True
    for qty, tol in tolerances.items():
        a_val = lane_a_results.get(qty)
        b_val = lane_b_results.get(qty)
        if a_val is not None and b_val is not None:
            rel_diff = abs(b_val - a_val) / max(abs(a_val), 1e-30)
            passed = rel_diff <= tol
            if not passed:
                all_pass = False
            comparison[qty] = {
                "direct": a_val, "omd": b_val,
                "rel_diff": rel_diff, "tol": tol,
                "status": "PASS" if passed else "FAIL",
            }
        else:
            comparison[qty] = {
                "direct": a_val, "omd": b_val,
                "status": "MISSING",
            }
            all_pass = False

    manifest = {
        "name": name,
        "comparison": comparison,
        "all_pass": all_pass,
    }

    out = tmp_path / "multilane_report.json"
    out.write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


class TestParaboloidMultilane:
    """Lane A: direct om.ExecComp. Lane B: omd plan pipeline."""

    def test_paraboloid_multilane(self, tmp_path):
        # Lane A: direct OpenMDAO
        prob = om.Problem(reports=False)
        prob.model.add_subsystem(
            "p", om.ExecComp("f_xy = (x-3)**2 + x*y + (y+4)**2 - 3"),
            promotes=["*"],
        )
        prob.setup()
        prob.set_val("x", 1.0)
        prob.set_val("y", 2.0)
        prob.run_model()
        lane_a = {"f_xy": float(prob.get_val("f_xy")[0])}

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "paraboloid_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {"f_xy": result["summary"]["f_xy"]}

        manifest = _lane_report(
            "paraboloid_analysis", lane_a, lane_b,
            {"f_xy": 1e-12}, tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestOASAeroMultilane:
    """Lane A: direct Geometry+AeroPoint. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_oas_aero_multilane(self, tmp_path):
        from openaerostruct.meshing.mesh_generator import generate_mesh
        from openaerostruct.geometry.geometry_group import Geometry
        from openaerostruct.aerodynamics.aero_groups import AeroPoint

        # Lane A: direct OAS
        mesh_dict = {"num_x": 2, "num_y": 7, "wing_type": "rect",
                     "symmetry": True, "span": 10.0, "root_chord": 1.0}
        mesh = generate_mesh(mesh_dict)
        if isinstance(mesh, tuple):
            mesh = mesh[0]

        surface = {
            "name": "wing", "mesh": mesh, "symmetry": True,
            "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
            "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
            "c_max_t": 0.303, "with_viscous": True, "with_wave": False,
            "twist_cp": np.zeros(4),
        }

        prob = om.Problem(reports=False)
        indep = om.IndepVarComp()
        indep.add_output("v", val=248.136, units="m/s")
        indep.add_output("alpha", val=5.0, units="deg")
        indep.add_output("beta", val=0.0, units="deg")
        indep.add_output("Mach_number", val=0.84)
        indep.add_output("re", val=1.0e6, units="1/m")
        indep.add_output("rho", val=0.38, units="kg/m**3")
        indep.add_output("cg", val=np.zeros(3), units="m")
        prob.model.add_subsystem("prob_vars", indep, promotes=["*"])
        prob.model.add_subsystem("wing", Geometry(surface=surface))
        prob.model.add_subsystem(
            "aero", AeroPoint(surfaces=[surface]),
            promotes_inputs=["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"],
        )
        prob.model.connect("wing.mesh", "aero.wing.def_mesh")
        prob.model.connect("wing.mesh", "aero.aero_states.wing_def_mesh")
        prob.model.connect("wing.t_over_c", "aero.wing_perf.t_over_c")
        prob.setup()
        prob.run_model()

        lane_a = {
            "CL": float(prob.get_val("aero.CL")[0]),
            "CD": float(prob.get_val("aero.CD")[0]),
        }

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "oas_aero_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "CL": result["summary"]["CL"],
            "CD": result["summary"]["CD"],
        }

        manifest = _lane_report(
            "oas_aero_analysis", lane_a, lane_b,
            {"CL": 1e-6, "CD": 1e-6}, tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestOASAerostructMultilane:
    """Lane A: direct AerostructGeometry+AerostructPoint. Lane B: omd plan."""

    @pytest.mark.slow
    def test_oas_aerostruct_multilane(self, tmp_path):
        from openaerostruct.meshing.mesh_generator import generate_mesh
        from openaerostruct.integration.aerostruct_groups import (
            AerostructGeometry, AerostructPoint,
        )

        # Lane A: direct OAS
        # Must match the fixture: num_y=7, same defaults as omd factory
        mesh_dict = {"num_x": 2, "num_y": 7, "wing_type": "rect",
                     "symmetry": True, "span": 10.0, "root_chord": 1.0}
        mesh = generate_mesh(mesh_dict)
        if isinstance(mesh, tuple):
            mesh = mesh[0]

        n_cp = 4  # (7+1)//2 = 4 for symmetric mesh
        surface = {
            "name": "wing", "mesh": mesh, "symmetry": True,
            "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
            "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
            "c_max_t": 0.303, "with_viscous": True, "with_wave": False,
            "twist_cp": np.zeros(n_cp),
            "thickness_cp": np.array([0.01, 0.02, 0.01]),
            "fem_model_type": "tube", "E": 7.0e10, "G": 3.0e10,
            "yield": 5.0e8, "mrho": 3000.0, "safety_factor": 1.5,
            "fem_origin": 0.35, "wing_weight_ratio": 2.0,
            "struct_weight_relief": False, "distributed_fuel_weight": False,
            "exact_failure_constraint": False,
        }

        prob = om.Problem(reports=False)
        indep = om.IndepVarComp()
        indep.add_output("v", val=248.136, units="m/s")
        indep.add_output("alpha", val=5.0, units="deg")
        indep.add_output("beta", val=0.0, units="deg")
        indep.add_output("Mach_number", val=0.84)
        indep.add_output("re", val=1.0e6, units="1/m")
        indep.add_output("rho", val=0.38, units="kg/m**3")
        indep.add_output("CT", val=9.81e-6, units="1/s")
        indep.add_output("R", val=14.3e6, units="m")
        indep.add_output("W0", val=25000.0, units="kg")
        indep.add_output("speed_of_sound", val=295.07, units="m/s")
        indep.add_output("load_factor", val=1.0)
        indep.add_output("empty_cg", val=np.array([0.35, 0.0, 0.0]), units="m")
        prob.model.add_subsystem("prob_vars", indep, promotes=["*"])
        prob.model.add_subsystem("wing", AerostructGeometry(surface=surface))
        promotes = ["v", "alpha", "beta", "Mach_number", "re", "rho",
                    "CT", "R", "W0", "speed_of_sound", "empty_cg", "load_factor"]
        prob.model.add_subsystem(
            "AS_point_0", AerostructPoint(surfaces=[surface]),
            promotes_inputs=promotes,
        )
        prob.model.connect("wing.local_stiff_transformed",
                           "AS_point_0.coupled.wing.local_stiff_transformed")
        prob.model.connect("wing.nodes", "AS_point_0.coupled.wing.nodes")
        prob.model.connect("wing.mesh", "AS_point_0.coupled.wing.mesh")
        prob.model.connect("wing.nodes", "AS_point_0.wing_perf.nodes")
        prob.model.connect("wing.cg_location",
                           "AS_point_0.total_perf.wing_cg_location")
        prob.model.connect("wing.structural_mass",
                           "AS_point_0.total_perf.wing_structural_mass")
        prob.model.connect("wing.t_over_c", "AS_point_0.wing_perf.t_over_c")
        prob.model.connect("wing.radius", "AS_point_0.wing_perf.radius")
        prob.model.connect("wing.thickness", "AS_point_0.wing_perf.thickness")

        # Match the fixture's solver config (Newton + Direct)
        prob.setup()
        coupled = prob.model.AS_point_0.coupled
        newton = om.NewtonSolver()
        newton.options["maxiter"] = 20
        newton.options["atol"] = 1e-6
        newton.options["solve_subsystems"] = True
        coupled.nonlinear_solver = newton
        coupled.linear_solver = om.DirectSolver()
        prob.run_model()

        lane_a = {
            "CL": float(prob.get_val("AS_point_0.CL")[0]),
            "CD": float(prob.get_val("AS_point_0.CD")[0]),
        }

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "oas_aerostruct_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "CL": result["summary"]["CL"],
            "CD": result["summary"]["CD"],
        }

        manifest = _lane_report(
            "oas_aerostruct_analysis", lane_a, lane_b,
            {"CL": 1e-6, "CD": 1e-6}, tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"
