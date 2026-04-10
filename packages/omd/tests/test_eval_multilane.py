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


class TestPycTurbojetMultilane:
    """Lane A: direct pyCycle API. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_pyc_turbojet_design_multilane(self, tmp_path):
        from hangar.omd.pyc.archetypes import Turbojet
        from hangar.omd.pyc.defaults import (
            DEFAULT_TURBOJET_PARAMS,
            DEFAULT_TURBOJET_DESIGN_GUESSES,
            DEFAULT_DESIGN_CONDITIONS,
        )

        # Lane A: direct pyCycle
        prob = om.Problem(reports=False)
        prob.model = Turbojet(params=DEFAULT_TURBOJET_PARAMS)
        prob.setup(check=False)

        prob.set_val("fc.alt", DEFAULT_DESIGN_CONDITIONS["alt"], units="ft")
        prob.set_val("fc.MN", DEFAULT_DESIGN_CONDITIONS["MN"])
        prob.set_val("comp.PR", DEFAULT_TURBOJET_PARAMS["comp_PR"])
        prob.set_val("comp.eff", DEFAULT_TURBOJET_PARAMS["comp_eff"])
        prob.set_val("turb.eff", DEFAULT_TURBOJET_PARAMS["turb_eff"])
        prob.set_val("Nmech", DEFAULT_TURBOJET_PARAMS["Nmech"], units="rpm")
        prob.set_val(
            "balance.Fn_target",
            DEFAULT_DESIGN_CONDITIONS["Fn_target"], units="lbf",
        )
        prob.set_val(
            "balance.T4_target",
            DEFAULT_DESIGN_CONDITIONS["T4_target"], units="degR",
        )

        prob["balance.FAR"] = DEFAULT_TURBOJET_DESIGN_GUESSES["FAR"]
        prob["balance.W"] = DEFAULT_TURBOJET_DESIGN_GUESSES["W"]
        prob["balance.turb_PR"] = DEFAULT_TURBOJET_DESIGN_GUESSES["turb_PR"]
        prob["fc.balance.Pt"] = DEFAULT_TURBOJET_DESIGN_GUESSES["fc_Pt"]
        prob["fc.balance.Tt"] = DEFAULT_TURBOJET_DESIGN_GUESSES["fc_Tt"]

        prob.set_solver_print(level=-1)
        prob.run_model()

        lane_a = {
            "Fn": float(prob["perf.Fn"][0]),
            "TSFC": float(prob["perf.TSFC"][0]),
            "OPR": float(prob["perf.OPR"][0]),
            "Fg": float(prob["perf.Fg"][0]),
        }

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "pyc_turbojet_design"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "Fn": result["summary"]["Fn"],
            "TSFC": result["summary"]["TSFC"],
            "OPR": result["summary"]["OPR"],
            "Fg": result["summary"]["Fg"],
        }

        manifest = _lane_report(
            "pyc_turbojet_design", lane_a, lane_b,
            {"Fn": 1e-6, "TSFC": 1e-6, "OPR": 1e-6, "Fg": 1e-6},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestPycHBTFMultilane:
    """Lane A: direct HBTF via MPHbtf. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_pyc_hbtf_design_multilane(self, tmp_path):
        from hangar.omd.pyc.hbtf import MPHbtf
        from hangar.omd.pyc.defaults import DEFAULT_HBTF_PARAMS, DEFAULT_HBTF_DESIGN_GUESSES

        # Lane A: direct pyCycle
        prob = om.Problem(reports=False)
        prob.model = MPHbtf(params=DEFAULT_HBTF_PARAMS, od_points=[])
        prob.setup()

        prob.set_val("DESIGN.fan.PR", 1.685)
        prob.set_val("DESIGN.fan.eff", 0.8948)
        prob.set_val("DESIGN.lpc.PR", 1.935)
        prob.set_val("DESIGN.lpc.eff", 0.9243)
        prob.set_val("DESIGN.hpc.PR", 9.369)
        prob.set_val("DESIGN.hpc.eff", 0.8707)
        prob.set_val("DESIGN.hpt.eff", 0.8888)
        prob.set_val("DESIGN.lpt.eff", 0.8996)
        prob.set_val("DESIGN.fc.alt", 35000.0, units="ft")
        prob.set_val("DESIGN.fc.MN", 0.8)
        prob.set_val("DESIGN.T4_MAX", 2857, units="degR")
        prob.set_val("DESIGN.Fn_DES", 5900.0, units="lbf")

        prob["DESIGN.balance.FAR"] = DEFAULT_HBTF_DESIGN_GUESSES["FAR"]
        prob["DESIGN.balance.W"] = DEFAULT_HBTF_DESIGN_GUESSES["W"]
        prob["DESIGN.balance.lpt_PR"] = DEFAULT_HBTF_DESIGN_GUESSES["lpt_PR"]
        prob["DESIGN.balance.hpt_PR"] = DEFAULT_HBTF_DESIGN_GUESSES["hpt_PR"]
        prob["DESIGN.fc.balance.Pt"] = DEFAULT_HBTF_DESIGN_GUESSES["fc_Pt"]
        prob["DESIGN.fc.balance.Tt"] = DEFAULT_HBTF_DESIGN_GUESSES["fc_Tt"]

        prob.set_solver_print(level=-1)
        prob.run_model()

        lane_a = {
            "Fn": float(prob["DESIGN.perf.Fn"][0]),
            "TSFC": float(prob["DESIGN.perf.TSFC"][0]),
            "OPR": float(prob["DESIGN.perf.OPR"][0]),
            "Fg": float(prob["DESIGN.perf.Fg"][0]),
        }

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "pyc_hbtf_design"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "Fn": result["summary"]["Fn"],
            "TSFC": result["summary"]["TSFC"],
            "OPR": result["summary"]["OPR"],
            "Fg": result["summary"]["Fg"],
        }

        manifest = _lane_report(
            "pyc_hbtf_design", lane_a, lane_b,
            {"Fn": 1e-6, "TSFC": 1e-6, "OPR": 1e-6, "Fg": 1e-6},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestPycABTurbojetMultilane:
    """Lane A: direct ABTurbojet. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_pyc_ab_turbojet_design_multilane(self, tmp_path):
        from hangar.omd.pyc.ab_turbojet import ABTurbojet
        from hangar.omd.pyc.defaults import (
            DEFAULT_AB_TURBOJET_PARAMS, DEFAULT_AB_TURBOJET_DESIGN_GUESSES,
            DEFAULT_AB_TURBOJET_DESIGN_CONDITIONS,
        )

        # Lane A: direct pyCycle
        prob = om.Problem(reports=False)
        prob.model = ABTurbojet(params=DEFAULT_AB_TURBOJET_PARAMS)
        prob.setup(check=False)

        dc = DEFAULT_AB_TURBOJET_DESIGN_CONDITIONS
        prob.set_val("fc.alt", dc["alt"], units="ft")
        prob.set_val("fc.MN", dc["MN"])
        prob.set_val("balance.rhs:W", dc["Fn_target"], units="lbf")
        prob.set_val("balance.rhs:FAR", dc["T4_target"], units="degR")
        prob.set_val("comp.PR", DEFAULT_AB_TURBOJET_PARAMS["comp_PR"])
        prob.set_val("comp.eff", DEFAULT_AB_TURBOJET_PARAMS["comp_eff"])
        prob.set_val("turb.eff", DEFAULT_AB_TURBOJET_PARAMS["turb_eff"])
        prob.set_val("Nmech", DEFAULT_AB_TURBOJET_PARAMS["Nmech"], units="rpm")
        prob.set_val("ab.Fl_I:FAR", dc["ab_FAR"])
        for k in ("inlet_MN", "duct1_MN", "comp_MN", "burner_MN", "turb_MN", "ab_MN"):
            prob.set_val(k.replace("_MN", ".MN"), DEFAULT_AB_TURBOJET_PARAMS[k])
        prob.set_val("duct1.dPqP", DEFAULT_AB_TURBOJET_PARAMS["duct1_dPqP"])
        prob.set_val("burner.dPqP", DEFAULT_AB_TURBOJET_PARAMS["burner_dPqP"])
        prob.set_val("ab.dPqP", DEFAULT_AB_TURBOJET_PARAMS["ab_dPqP"])
        prob.set_val("nozz.Cv", DEFAULT_AB_TURBOJET_PARAMS["nozz_Cv"])
        prob.set_val("comp.cool1:frac_W", DEFAULT_AB_TURBOJET_PARAMS["cool1_frac_W"])
        prob.set_val("comp.cool1:frac_P", DEFAULT_AB_TURBOJET_PARAMS["cool1_frac_P"])
        prob.set_val("comp.cool1:frac_work", DEFAULT_AB_TURBOJET_PARAMS["cool1_frac_work"])
        prob.set_val("comp.cool2:frac_W", DEFAULT_AB_TURBOJET_PARAMS["cool2_frac_W"])
        prob.set_val("comp.cool2:frac_P", DEFAULT_AB_TURBOJET_PARAMS["cool2_frac_P"])
        prob.set_val("comp.cool2:frac_work", DEFAULT_AB_TURBOJET_PARAMS["cool2_frac_work"])
        prob.set_val("turb.cool1:frac_P", DEFAULT_AB_TURBOJET_PARAMS["turb_cool1_frac_P"])
        prob.set_val("turb.cool2:frac_P", DEFAULT_AB_TURBOJET_PARAMS["turb_cool2_frac_P"])

        g = DEFAULT_AB_TURBOJET_DESIGN_GUESSES
        prob["balance.FAR"] = g["FAR"]
        prob["balance.W"] = g["W"]
        prob["balance.turb_PR"] = g["turb_PR"]
        prob["fc.balance.Pt"] = g["fc_Pt"]
        prob["fc.balance.Tt"] = g["fc_Tt"]

        prob.set_solver_print(level=-1)
        prob.run_model()

        lane_a = {
            "Fn": float(prob["perf.Fn"][0]),
            "TSFC": float(prob["perf.TSFC"][0]),
            "OPR": float(prob["perf.OPR"][0]),
            "Fg": float(prob["perf.Fg"][0]),
        }

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "pyc_ab_turbojet_design"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "Fn": result["summary"]["Fn"],
            "TSFC": result["summary"]["TSFC"],
            "OPR": result["summary"]["OPR"],
            "Fg": result["summary"]["Fg"],
        }

        manifest = _lane_report(
            "pyc_ab_turbojet_design", lane_a, lane_b,
            {"Fn": 1e-6, "TSFC": 1e-6, "OPR": 1e-6, "Fg": 1e-6},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestPycSingleTurboshaftMultilane:
    """Lane A: direct SingleSpoolTurboshaft. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_pyc_single_turboshaft_design_multilane(self, tmp_path):
        from hangar.omd.pyc.turboshaft import SingleSpoolTurboshaft
        from hangar.omd.pyc.defaults import (
            DEFAULT_SINGLE_TURBOSHAFT_PARAMS,
            DEFAULT_SINGLE_TURBOSHAFT_DESIGN_GUESSES,
            DEFAULT_SINGLE_TURBOSHAFT_DESIGN_CONDITIONS,
        )

        # Lane A
        prob = om.Problem(reports=False)
        prob.model = SingleSpoolTurboshaft(
            params=DEFAULT_SINGLE_TURBOSHAFT_PARAMS)
        prob.setup(check=False)

        dc = DEFAULT_SINGLE_TURBOSHAFT_DESIGN_CONDITIONS
        prob.set_val("fc.alt", dc["alt"], units="ft")
        prob.set_val("fc.MN", dc["MN"])
        prob.set_val("balance.T4_target", dc["T4_target"], units="degR")
        prob.set_val("balance.pwr_target", dc["pwr_target"], units="hp")
        prob.set_val("balance.nozz_PR_target", dc["nozz_PR_target"])
        p = DEFAULT_SINGLE_TURBOSHAFT_PARAMS
        prob.set_val("comp.PR", p["comp_PR"])
        prob.set_val("comp.eff", p["comp_eff"])
        prob.set_val("turb.eff", p["turb_eff"])
        prob.set_val("pt.eff", p["pt_eff"])
        prob.set_val("HP_Nmech", p["HP_Nmech"], units="rpm")
        prob.set_val("LP_Nmech", p["LP_Nmech"], units="rpm")
        prob.set_val("inlet.MN", p["inlet_MN"])
        prob.set_val("comp.MN", p["comp_MN"])
        prob.set_val("burner.MN", p["burner_MN"])
        prob.set_val("turb.MN", p["turb_MN"])
        prob.set_val("burner.dPqP", p["burner_dPqP"])
        prob.set_val("nozz.Cv", p["nozz_Cv"])

        g = DEFAULT_SINGLE_TURBOSHAFT_DESIGN_GUESSES
        prob["balance.FAR"] = g["FAR"]
        prob["balance.W"] = g["W"]
        prob["balance.turb_PR"] = g["turb_PR"]
        prob["balance.pt_PR"] = g["pt_PR"]
        prob["fc.balance.Pt"] = g["fc_Pt"]
        prob["fc.balance.Tt"] = g["fc_Tt"]

        prob.set_solver_print(level=-1)
        prob.run_model()

        lane_a = {
            "Fn": float(prob["perf.Fn"][0]),
            "TSFC": float(prob["perf.TSFC"][0]),
            "OPR": float(prob["perf.OPR"][0]),
            "Fg": float(prob["perf.Fg"][0]),
        }

        # Lane B
        plan_dir = FIXTURES / "pyc_single_turboshaft_design"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "Fn": result["summary"]["Fn"],
            "TSFC": result["summary"]["TSFC"],
            "OPR": result["summary"]["OPR"],
            "Fg": result["summary"]["Fg"],
        }

        manifest = _lane_report(
            "pyc_single_turboshaft_design", lane_a, lane_b,
            {"Fn": 1e-6, "TSFC": 1e-6, "OPR": 1e-6, "Fg": 1e-6},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestPycMultiTurboshaftMultilane:
    """Lane A: direct MultiSpoolTurboshaft. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_pyc_multi_turboshaft_design_multilane(self, tmp_path):
        from hangar.omd.pyc.turboshaft import MultiSpoolTurboshaft
        from hangar.omd.pyc.defaults import (
            DEFAULT_MULTI_TURBOSHAFT_PARAMS,
            DEFAULT_MULTI_TURBOSHAFT_DESIGN_GUESSES,
            DEFAULT_MULTI_TURBOSHAFT_DESIGN_CONDITIONS,
        )

        # Lane A
        prob = om.Problem(reports=False)
        prob.model = MultiSpoolTurboshaft(
            params=DEFAULT_MULTI_TURBOSHAFT_PARAMS, maxiter=10)
        prob.setup(check=False)

        dc = DEFAULT_MULTI_TURBOSHAFT_DESIGN_CONDITIONS
        p = DEFAULT_MULTI_TURBOSHAFT_PARAMS
        prob.set_val("fc.alt", dc["alt"], units="ft")
        prob.set_val("fc.MN", dc["MN"])
        prob.set_val("balance.rhs:FAR", dc["T4_target"], units="degR")
        prob.set_val("balance.rhs:W", dc["nozz_PR_target"])
        prob.set_val("LP_Nmech", p["LP_Nmech"], units="rpm")
        prob.set_val("IP_Nmech", p["IP_Nmech"], units="rpm")
        prob.set_val("HP_Nmech", p["HP_Nmech"], units="rpm")
        prob.set_val("lp_shaft.HPX", p["lp_shaft_HPX"], units="hp")
        prob.set_val("lpc.PR", p["lpc_PR"])
        prob.set_val("lpc.eff", p["lpc_eff"])
        prob.set_val("hpc_axi.PR", p["hpc_axi_PR"])
        prob.set_val("hpc_axi.eff", p["hpc_axi_eff"])
        prob.set_val("hpc_centri.PR", p["hpc_centri_PR"])
        prob.set_val("hpc_centri.eff", p["hpc_centri_eff"])
        prob.set_val("hpt.eff", p["hpt_eff"])
        prob.set_val("lpt.eff", p["lpt_eff"])
        prob.set_val("pt.eff", p["pt_eff"])
        # Element MNs
        for k, v in {"inlet.MN": 0.4, "duct1.MN": 0.4, "lpc.MN": 0.3,
                      "icduct.MN": 0.3, "hpc_axi.MN": 0.25, "bld25.MN": 0.3,
                      "hpc_centri.MN": 0.2, "bld3.MN": 0.2, "duct6.MN": 0.2,
                      "burner.MN": 0.15, "hpt.MN": 0.3, "duct43.MN": 0.3,
                      "lpt.MN": 0.4, "itduct.MN": 0.4, "pt.MN": 0.4,
                      "duct12.MN": 0.4}.items():
            prob.set_val(k, v)
        # Cycle params
        prob.set_val("inlet.ram_recovery", p["inlet_ram_recovery"])
        prob.set_val("duct1.dPqP", p["duct1_dPqP"])
        prob.set_val("icduct.dPqP", p["icduct_dPqP"])
        prob.set_val("duct6.dPqP", p["duct6_dPqP"])
        prob.set_val("burner.dPqP", p["burner_dPqP"])
        prob.set_val("duct43.dPqP", p["duct43_dPqP"])
        prob.set_val("itduct.dPqP", p["itduct_dPqP"])
        prob.set_val("duct12.dPqP", p["duct12_dPqP"])
        prob.set_val("nozzle.Cv", p["nozzle_Cv"])
        prob.set_val("bld25.cool1:frac_W", p["cool1_frac_W"])
        prob.set_val("bld25.cool2:frac_W", p["cool2_frac_W"])
        prob.set_val("bld3.cool3:frac_W", p["cool3_frac_W"])
        prob.set_val("bld3.cool4:frac_W", p["cool4_frac_W"])
        prob.set_val("hpt.cool3:frac_P", p["hpt_cool3_frac_P"])
        prob.set_val("hpt.cool4:frac_P", p["hpt_cool4_frac_P"])
        prob.set_val("lpt.cool1:frac_P", p["lpt_cool1_frac_P"])
        prob.set_val("lpt.cool2:frac_P", p["lpt_cool2_frac_P"])

        g = DEFAULT_MULTI_TURBOSHAFT_DESIGN_GUESSES
        prob["balance.FAR"] = g["FAR"]
        prob["balance.W"] = g["W"]
        prob["balance.hpt_PR"] = g["hpt_PR"]
        prob["balance.lpt_PR"] = g["lpt_PR"]
        prob["balance.pt_PR"] = g["pt_PR"]
        prob["fc.balance.Pt"] = g["fc_Pt"]
        prob["fc.balance.Tt"] = g["fc_Tt"]

        prob.set_solver_print(level=-1)
        prob.run_model()

        lane_a = {
            "Fn": float(prob["perf.Fn"][0]),
            "OPR": float(prob["perf.OPR"][0]),
            "Fg": float(prob["perf.Fg"][0]),
        }

        # Lane B
        plan_dir = FIXTURES / "pyc_multi_turboshaft_design"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "Fn": result["summary"]["Fn"],
            "OPR": result["summary"]["OPR"],
            "Fg": result["summary"]["Fg"],
        }

        manifest = _lane_report(
            "pyc_multi_turboshaft_design", lane_a, lane_b,
            {"Fn": 1e-6, "OPR": 1e-6, "Fg": 1e-6},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestPycMixedFlowMultilane:
    """Lane A: direct MixedFlowTurbofan. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_pyc_mixedflow_design_multilane(self, tmp_path):
        from hangar.omd.pyc.mixedflow_turbofan import MixedFlowTurbofan
        from hangar.omd.pyc.defaults import (
            DEFAULT_MIXEDFLOW_PARAMS, DEFAULT_MIXEDFLOW_DESIGN_GUESSES,
            DEFAULT_MIXEDFLOW_DESIGN_CONDITIONS,
        )

        # Lane A
        prob = om.Problem(reports=False)
        prob.model = MixedFlowTurbofan(params=DEFAULT_MIXEDFLOW_PARAMS)
        prob.setup(check=False)

        dc = DEFAULT_MIXEDFLOW_DESIGN_CONDITIONS
        p = DEFAULT_MIXEDFLOW_PARAMS
        prob.set_val("fc.alt", dc["alt"], units="ft")
        prob.set_val("fc.MN", dc["MN"])
        prob.set_val("balance.rhs:W", dc["Fn_target"], units="lbf")
        prob.set_val("balance.rhs:FAR_core", dc["T4_target"], units="degR")
        prob.set_val("balance.rhs:FAR_ab", dc["T_ab_target"], units="degR")
        prob.set_val("balance.rhs:BPR", dc["BPR_target"])
        prob.set_val("LP_Nmech", p["LP_Nmech"], units="rpm")
        prob.set_val("HP_Nmech", p["HP_Nmech"], units="rpm")
        prob.set_val("hp_shaft.HPX", p["hp_shaft_HPX"], units="hp")
        prob.set_val("fan.PR", p["fan_PR"])
        prob.set_val("fan.eff", p["fan_eff"])
        prob.set_val("lpc.PR", p["lpc_PR"])
        prob.set_val("lpc.eff", p["lpc_eff"])
        prob.set_val("hpc.PR", p["hpc_PR"])
        prob.set_val("hpc.eff", p["hpc_eff"])
        prob.set_val("hpt.eff", p["hpt_eff"])
        prob.set_val("lpt.eff", p["lpt_eff"])
        # Element MNs
        for k, v in {"inlet.MN": 0.751, "inlet_duct.MN": 0.4463,
                      "fan.MN": 0.4578, "splitter.MN1": 0.3104,
                      "splitter.MN2": 0.4518, "splitter_core_duct.MN": 0.3121,
                      "lpc.MN": 0.3059, "lpc_duct.MN": 0.3563,
                      "hpc.MN": 0.2442, "bld3.MN": 0.3, "burner.MN": 0.1025,
                      "hpt.MN": 0.365, "hpt_duct.MN": 0.3063,
                      "lpt.MN": 0.4127, "lpt_duct.MN": 0.4463,
                      "bypass_duct.MN": 0.4463, "mixer_duct.MN": 0.4463,
                      "afterburner.MN": 0.1025}.items():
            prob.set_val(k, v)
        # Cycle params
        prob.set_val("inlet.ram_recovery", p["inlet_ram_recovery"])
        prob.set_val("inlet_duct.dPqP", p["inlet_duct_dPqP"])
        prob.set_val("splitter_core_duct.dPqP", p["splitter_core_duct_dPqP"])
        prob.set_val("lpc_duct.dPqP", p["lpc_duct_dPqP"])
        prob.set_val("burner.dPqP", p["burner_dPqP"])
        prob.set_val("hpt_duct.dPqP", p["hpt_duct_dPqP"])
        prob.set_val("lpt_duct.dPqP", p["lpt_duct_dPqP"])
        prob.set_val("bypass_duct.dPqP", p["bypass_duct_dPqP"])
        prob.set_val("mixer_duct.dPqP", p["mixer_duct_dPqP"])
        prob.set_val("afterburner.dPqP", p["afterburner_dPqP"])
        prob.set_val("mixed_nozz.Cfg", p["mixed_nozz_Cfg"])
        prob.set_val("hpc.cool1:frac_W", p["cool1_frac_W"])
        prob.set_val("hpc.cool1:frac_P", p["cool1_frac_P"])
        prob.set_val("hpc.cool1:frac_work", p["cool1_frac_work"])
        prob.set_val("bld3.cool3:frac_W", p["cool3_frac_W"])
        prob.set_val("hpt.cool3:frac_P", p["hpt_cool3_frac_P"])
        prob.set_val("lpt.cool1:frac_P", p["lpt_cool1_frac_P"])

        g = DEFAULT_MIXEDFLOW_DESIGN_GUESSES
        prob["balance.FAR_core"] = g["FAR_core"]
        prob["balance.FAR_ab"] = g["FAR_ab"]
        prob["balance.BPR"] = g["BPR"]
        prob["balance.W"] = g["W"]
        prob["balance.lpt_PR"] = g["lpt_PR"]
        prob["balance.hpt_PR"] = g["hpt_PR"]
        prob["fc.balance.Pt"] = g["fc_Pt"]
        prob["fc.balance.Tt"] = g["fc_Tt"]
        prob["mixer.balance.P_tot"] = g["mixer_P_tot"]

        prob.set_solver_print(level=-1)
        prob.run_model()

        lane_a = {
            "Fn": float(prob["perf.Fn"][0]),
            "TSFC": float(prob["perf.TSFC"][0]),
            "OPR": float(prob["perf.OPR"][0]),
            "Fg": float(prob["perf.Fg"][0]),
        }

        # Lane B
        plan_dir = FIXTURES / "pyc_mixedflow_design"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "Fn": result["summary"]["Fn"],
            "TSFC": result["summary"]["TSFC"],
            "OPR": result["summary"]["OPR"],
            "Fg": result["summary"]["Fg"],
        }

        manifest = _lane_report(
            "pyc_mixedflow_design", lane_a, lane_b,
            {"Fn": 1e-6, "TSFC": 1e-6, "OPR": 1e-6, "Fg": 1e-6},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


# ---------------------------------------------------------------------------
# OCP mission multilane tests
# ---------------------------------------------------------------------------


class TestOCPBasicMissionMultilane:
    """Lane A: direct OpenConcept BasicMission. Lane B: omd plan pipeline."""

    @pytest.mark.slow
    def test_ocp_basic_mission_multilane(self, tmp_path):
        import contextlib
        import io

        from openconcept.utilities import (
            Integrator, AddSubtractComp, DictIndepVarComp,
        )
        from openconcept.propulsion import TurbopropPropulsionSystem
        from openconcept.weights import SingleTurboPropEmptyWeight
        from openconcept.aerodynamics import PolarDrag
        from openconcept.mission import BasicMission
        from openconcept.examples.aircraft_data.caravan import data as acdata

        nn = 11

        class _CaravanModel(om.Group):
            def initialize(self):
                self.options.declare("num_nodes", default=1)
                self.options.declare("flight_phase", default=None)

            def setup(self):
                _nn = self.options["num_nodes"]
                ctrl = self.add_subsystem(
                    "controls", om.IndepVarComp(), promotes_outputs=["*"])
                ctrl.add_output(
                    "prop1rpm", val=np.ones((_nn,)) * 2000, units="rpm")
                self.add_subsystem(
                    "propmodel", TurbopropPropulsionSystem(num_nodes=_nn),
                    promotes_inputs=["fltcond|*", "ac|propulsion|*", "throttle"],
                    promotes_outputs=["fuel_flow", "thrust"])
                self.connect("prop1rpm", "propmodel.prop1.rpm")
                self.add_subsystem(
                    "drag", PolarDrag(num_nodes=_nn),
                    promotes_inputs=[
                        "fltcond|CL", "ac|geom|*",
                        ("CD0", "ac|aero|polar|CD0_cruise"),
                        "fltcond|q", ("e", "ac|aero|polar|e")],
                    promotes_outputs=["drag"])
                self.add_subsystem(
                    "OEW", SingleTurboPropEmptyWeight(),
                    promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
                    promotes_outputs=["OEW"])
                self.connect("propmodel.prop1.component_weight", "W_propeller")
                self.connect("propmodel.eng1.component_weight", "W_engine")
                intfuel = self.add_subsystem(
                    "intfuel",
                    Integrator(num_nodes=_nn, method="simpson",
                               diff_units="s", time_setup="duration"),
                    promotes_inputs=["*"], promotes_outputs=["*"])
                intfuel.add_integrand(
                    "fuel_used", rate_name="fuel_flow", val=1.0, units="kg")
                self.add_subsystem(
                    "weight", AddSubtractComp(
                        output_name="weight",
                        input_names=["ac|weights|MTOW", "fuel_used"],
                        units="kg", vec_size=[1, _nn],
                        scaling_factors=[1, -1]),
                    promotes_inputs=["*"], promotes_outputs=["weight"])

        class _CaravanAnalysis(om.Group):
            def setup(self):
                dv = self.add_subsystem(
                    "dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"])
                for f in [
                    "ac|aero|CLmax_TO",
                    "ac|aero|polar|e",
                    "ac|aero|polar|CD0_TO", "ac|aero|polar|CD0_cruise",
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
                ]:
                    dv.add_output_from_dict(f)
                self.add_subsystem(
                    "analysis",
                    BasicMission(num_nodes=nn, aircraft_model=_CaravanModel),
                    promotes_inputs=["*"], promotes_outputs=["*"])

        # Lane A: direct OpenConcept
        prob = om.Problem(reports=False)
        prob.model = _CaravanAnalysis()
        prob.model.nonlinear_solver = om.NewtonSolver(
            iprint=0, solve_subsystems=True)
        prob.model.linear_solver = om.DirectSolver()
        prob.model.nonlinear_solver.options["maxiter"] = 20
        prob.model.nonlinear_solver.options["atol"] = 1e-10
        prob.model.nonlinear_solver.options["rtol"] = 1e-10
        prob.model.nonlinear_solver.linesearch = om.BoundsEnforceLS(
            bound_enforcement="scalar", print_bound_enforce=False)
        prob.setup(check=False, mode="fwd")

        prob.set_val("climb.fltcond|vs", np.ones((nn,)) * 850, units="ft/min")
        prob.set_val("climb.fltcond|Ueas", np.ones((nn,)) * 104, units="kn")
        prob.set_val("cruise.fltcond|vs", np.ones((nn,)) * 0.01, units="ft/min")
        prob.set_val("cruise.fltcond|Ueas", np.ones((nn,)) * 129, units="kn")
        prob.set_val("descent.fltcond|vs", np.ones((nn,)) * -400, units="ft/min")
        prob.set_val("descent.fltcond|Ueas", np.ones((nn,)) * 100, units="kn")
        prob.set_val("cruise|h0", 18000, units="ft")
        prob.set_val("mission_range", 250, units="NM")

        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            prob.run_model()

        lane_a = {
            "fuel_burn_kg": float(prob.get_val(
                "descent.fuel_used_final", units="kg")[0]),
            "OEW_kg": float(prob.get_val("climb.OEW", units="kg")[0]),
            "MTOW_kg": float(prob.get_val("ac|weights|MTOW", units="kg")[0]),
        }

        # Lane B: omd pipeline
        plan_dir = FIXTURES / "ocp_basic_mission"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "fuel_burn_kg": result["summary"]["fuel_burn_kg"],
            "OEW_kg": result["summary"]["OEW_kg"],
            "MTOW_kg": result["summary"]["MTOW_kg"],
        }

        manifest = _lane_report(
            "ocp_basic_mission", lane_a, lane_b,
            {"fuel_burn_kg": 1e-6, "OEW_kg": 1e-6, "MTOW_kg": 1e-10},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestOCPVLMDragSlotMultilane:
    """Lane A: direct OpenConcept + VLMDragPolar. Lane B: omd with oas/vlm slot."""

    @pytest.mark.slow
    def test_ocp_vlm_drag_slot_multilane(self, tmp_path):
        import contextlib
        import io

        from openconcept.utilities import (
            Integrator, AddSubtractComp, DictIndepVarComp,
        )
        from openconcept.propulsion import TurbopropPropulsionSystem
        from openconcept.weights import SingleTurboPropEmptyWeight
        from openconcept.aerodynamics import VLMDragPolar
        from openconcept.mission import BasicMission
        from openconcept.examples.aircraft_data.caravan import data as acdata

        nn = 11

        class _CaravanVLMModel(om.Group):
            def initialize(self):
                self.options.declare("num_nodes", default=1)
                self.options.declare("flight_phase", default=None)

            def setup(self):
                _nn = self.options["num_nodes"]
                ctrl = self.add_subsystem(
                    "controls", om.IndepVarComp(), promotes_outputs=["*"])
                ctrl.add_output(
                    "prop1rpm", val=np.ones((_nn,)) * 2000, units="rpm")
                self.add_subsystem(
                    "propmodel", TurbopropPropulsionSystem(num_nodes=_nn),
                    promotes_inputs=["fltcond|*", "ac|propulsion|*", "throttle"],
                    promotes_outputs=["fuel_flow", "thrust"])
                self.connect("prop1rpm", "propmodel.prop1.rpm")
                self.add_subsystem(
                    "drag", VLMDragPolar(
                        num_nodes=_nn, num_x=2, num_y=7, num_twist=4),
                    promotes_inputs=[
                        "fltcond|CL", "fltcond|M", "fltcond|h", "fltcond|q",
                        "ac|geom|wing|S_ref", "ac|geom|wing|AR",
                        "ac|geom|wing|taper", "ac|geom|wing|c4sweep",
                        "ac|geom|wing|twist", "ac|aero|CD_nonwing"],
                    promotes_outputs=["drag"])
                self.add_subsystem(
                    "OEW", SingleTurboPropEmptyWeight(),
                    promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
                    promotes_outputs=["OEW"])
                self.connect("propmodel.prop1.component_weight", "W_propeller")
                self.connect("propmodel.eng1.component_weight", "W_engine")
                intfuel = self.add_subsystem(
                    "intfuel",
                    Integrator(num_nodes=_nn, method="simpson",
                               diff_units="s", time_setup="duration"),
                    promotes_inputs=["*"], promotes_outputs=["*"])
                intfuel.add_integrand(
                    "fuel_used", rate_name="fuel_flow", val=1.0, units="kg")
                self.add_subsystem(
                    "weight", AddSubtractComp(
                        output_name="weight",
                        input_names=["ac|weights|MTOW", "fuel_used"],
                        units="kg", vec_size=[1, _nn],
                        scaling_factors=[1, -1]),
                    promotes_inputs=["*"], promotes_outputs=["weight"])

        class _CaravanVLMAnalysis(om.Group):
            def setup(self):
                dv = self.add_subsystem(
                    "dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"])
                for f in [
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
                ]:
                    dv.add_output_from_dict(f)
                dv.add_output("ac|aero|CD_nonwing", val=0.0145)
                self.add_subsystem(
                    "analysis",
                    BasicMission(num_nodes=nn, aircraft_model=_CaravanVLMModel),
                    promotes_inputs=["*"], promotes_outputs=["*"])

        # Lane A: direct OpenConcept + VLMDragPolar
        prob = om.Problem(reports=False)
        prob.model = _CaravanVLMAnalysis()
        prob.model.nonlinear_solver = om.NewtonSolver(
            iprint=0, solve_subsystems=True)
        prob.model.linear_solver = om.DirectSolver()
        prob.model.nonlinear_solver.options["maxiter"] = 20
        prob.model.nonlinear_solver.options["atol"] = 1e-10
        prob.model.nonlinear_solver.options["rtol"] = 1e-10
        prob.model.nonlinear_solver.linesearch = om.BoundsEnforceLS(
            bound_enforcement="scalar", print_bound_enforce=False)
        prob.setup(check=False, mode="fwd")

        prob.set_val("climb.fltcond|vs", np.ones((nn,)) * 850, units="ft/min")
        prob.set_val("climb.fltcond|Ueas", np.ones((nn,)) * 104, units="kn")
        prob.set_val("cruise.fltcond|vs", np.ones((nn,)) * 0.01, units="ft/min")
        prob.set_val("cruise.fltcond|Ueas", np.ones((nn,)) * 129, units="kn")
        prob.set_val("descent.fltcond|vs", np.ones((nn,)) * -400, units="ft/min")
        prob.set_val("descent.fltcond|Ueas", np.ones((nn,)) * 100, units="kn")
        prob.set_val("cruise|h0", 18000, units="ft")
        prob.set_val("mission_range", 250, units="NM")

        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            prob.run_model()

        lane_a = {
            "fuel_burn_kg": float(prob.get_val(
                "descent.fuel_used_final", units="kg")[0]),
        }

        # Lane B: omd pipeline with oas/vlm slot
        plan_dir = FIXTURES / "ocp_vlm_drag_slot"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "fuel_burn_kg": result["summary"]["fuel_burn_kg"],
        }

        manifest = _lane_report(
            "ocp_vlm_drag_slot", lane_a, lane_b,
            {"fuel_burn_kg": 1e-3},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"


class TestOCPPyCyclePropSlotMultilane:
    """Lane A: direct OpenConcept + pyCycle turbojet. Lane B: omd with pyc/turbojet slot."""

    @pytest.mark.slow
    def test_ocp_pyc_prop_slot_multilane(self, tmp_path):
        import contextlib
        import io

        from openconcept.utilities import (
            Integrator, AddSubtractComp, DictIndepVarComp,
        )
        from openconcept.aerodynamics import PolarDrag
        from openconcept.weights import SingleTurboPropEmptyWeight
        from openconcept.mission import BasicMission
        from openconcept.examples.aircraft_data.caravan import data as acdata
        from hangar.omd.slots import _DirectPyCyclePropGroup

        nn = 3

        class _CaravanPyCycleModel(om.Group):
            def initialize(self):
                self.options.declare("num_nodes", default=1)
                self.options.declare("flight_phase", default=None)

            def setup(self):
                _nn = self.options["num_nodes"]
                self.add_subsystem(
                    "propmodel",
                    _DirectPyCyclePropGroup(
                        nn=_nn,
                        design_alt=18000.0,
                        design_MN=0.35,
                        design_Fn=4000.0,
                        design_T4=2370.0,
                        thermo_method="TABULAR",
                        engine_params={},
                    ),
                    promotes_inputs=["fltcond|h", "fltcond|M", "throttle"],
                    promotes_outputs=["fuel_flow", "thrust"])
                flight_phase = self.options["flight_phase"]
                if flight_phase not in ["v0v1", "v1v0", "v1vr", "rotate"]:
                    cd0_source = "ac|aero|polar|CD0_cruise"
                else:
                    cd0_source = "ac|aero|polar|CD0_TO"
                self.add_subsystem(
                    "drag", PolarDrag(num_nodes=_nn),
                    promotes_inputs=[
                        "fltcond|CL", "ac|geom|*",
                        ("CD0", cd0_source),
                        "fltcond|q", ("e", "ac|aero|polar|e")],
                    promotes_outputs=["drag"])
                self.add_subsystem(
                    "OEW", SingleTurboPropEmptyWeight(),
                    promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
                    promotes_outputs=["OEW"])
                intfuel = self.add_subsystem(
                    "intfuel",
                    Integrator(num_nodes=_nn, method="simpson",
                               diff_units="s", time_setup="duration"),
                    promotes_inputs=["*"], promotes_outputs=["*"])
                intfuel.add_integrand(
                    "fuel_used", rate_name="fuel_flow", val=1.0, units="kg")
                self.add_subsystem(
                    "weight", AddSubtractComp(
                        output_name="weight",
                        input_names=["ac|weights|MTOW", "fuel_used"],
                        units="kg", vec_size=[1, _nn],
                        scaling_factors=[1, -1]),
                    promotes_inputs=["*"], promotes_outputs=["weight"])

        class _CaravanPyCycleAnalysis(om.Group):
            def setup(self):
                dv = self.add_subsystem(
                    "dv_comp", DictIndepVarComp(acdata), promotes_outputs=["*"])
                for f in [
                    "ac|aero|CLmax_TO",
                    "ac|aero|polar|e",
                    "ac|aero|polar|CD0_TO", "ac|aero|polar|CD0_cruise",
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
                ]:
                    dv.add_output_from_dict(f)
                self.add_subsystem(
                    "analysis",
                    BasicMission(num_nodes=nn, aircraft_model=_CaravanPyCycleModel),
                    promotes_inputs=["*"], promotes_outputs=["*"])

        # Lane A: direct OpenConcept + pyCycle turbojet
        prob = om.Problem(reports=False)
        prob.model = _CaravanPyCycleAnalysis()
        prob.model.nonlinear_solver = om.NewtonSolver(
            iprint=0, solve_subsystems=True)
        prob.model.linear_solver = om.DirectSolver()
        prob.model.nonlinear_solver.options["maxiter"] = 30
        prob.model.nonlinear_solver.options["atol"] = 1e-8
        prob.model.nonlinear_solver.options["rtol"] = 1e-8
        prob.model.nonlinear_solver.linesearch = om.BoundsEnforceLS(
            bound_enforcement="scalar", print_bound_enforce=False)
        prob.setup(check=False, mode="fwd")

        prob.set_val("climb.fltcond|vs", np.ones((nn,)) * 850, units="ft/min")
        prob.set_val("climb.fltcond|Ueas", np.ones((nn,)) * 104, units="kn")
        prob.set_val("cruise.fltcond|vs", np.ones((nn,)) * 0.01, units="ft/min")
        prob.set_val("cruise.fltcond|Ueas", np.ones((nn,)) * 129, units="kn")
        prob.set_val("descent.fltcond|vs", np.ones((nn,)) * -400, units="ft/min")
        prob.set_val("descent.fltcond|Ueas", np.ones((nn,)) * 100, units="kn")
        prob.set_val("cruise|h0", 18000, units="ft")
        prob.set_val("mission_range", 250, units="NM")

        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            prob.run_model()

        lane_a = {
            "fuel_burn_kg": float(prob.get_val(
                "descent.fuel_used_final", units="kg")[0]),
        }

        # Lane B: omd pipeline with pyc/turbojet slot
        plan_dir = FIXTURES / "ocp_pyc_prop_slot"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        lane_b = {
            "fuel_burn_kg": result["summary"]["fuel_burn_kg"],
        }

        manifest = _lane_report(
            "ocp_pyc_prop_slot", lane_a, lane_b,
            {"fuel_burn_kg": 1e-3},
            tmp_path,
        )
        assert manifest["all_pass"], f"Parity failed: {manifest['comparison']}"
