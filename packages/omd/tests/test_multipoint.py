"""Tests for multipoint aerostructural optimization support."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hangar.omd.plan_schema import validate_plan
from hangar.omd.factories.oas import (
    build_oas_aerostruct,
    build_oas_aerostruct_multipoint,
    _plan_config_to_surface_dict,
)
from hangar.omd.materializer import _resolve_var_path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_multipoint_schema_valid():
    """Multipoint operating_points with flight_points passes validation."""
    plan = {
        "metadata": {"id": "test-mp", "name": "test", "version": 1},
        "components": [{"id": "w", "type": "oas/AerostructMultipoint", "config": {}}],
        "operating_points": {
            "shared": {"CT": 9.81e-6, "R": 3e6},
            "flight_points": [
                {"name": "cruise", "velocity": 248.0, "load_factor": 1.0},
                {"name": "maneuver", "velocity": 248.0, "load_factor": 2.5},
            ],
        },
        "constraints": [
            {"name": "CL", "equals": 0.5, "point": 0},
            {"name": "failure", "upper": 0.0, "point": 1},
        ],
    }
    errors = validate_plan(plan)
    assert errors == [], f"Validation errors: {errors}"


def test_single_point_schema_still_valid():
    """Existing single-point operating_points format still passes."""
    plan = {
        "metadata": {"id": "test-sp", "name": "test", "version": 1},
        "components": [{"id": "w", "type": "oas/AerostructPoint", "config": {}}],
        "operating_points": {
            "velocity": 248.136,
            "alpha": 5.0,
            "Mach_number": 0.84,
        },
    }
    errors = validate_plan(plan)
    assert errors == [], f"Validation errors: {errors}"


def test_constraint_with_point_field_valid():
    """Constraint with point field passes schema validation."""
    plan = {
        "metadata": {"id": "test", "name": "test", "version": 1},
        "components": [{"id": "w", "type": "oas/AerostructMultipoint", "config": {}}],
        "constraints": [
            {"name": "failure", "upper": 0.0, "point": 0},
            {"name": "failure", "upper": 0.0, "point": 1},
        ],
    }
    errors = validate_plan(plan)
    assert errors == [], f"Validation errors: {errors}"


# ---------------------------------------------------------------------------
# Variable path resolution
# ---------------------------------------------------------------------------


def test_resolve_multipoint_promoted_names():
    """Multipoint-specific names resolve to promoted paths."""
    assert _resolve_var_path("alpha_maneuver", "AS_point_0", []) == "alpha_maneuver"
    assert _resolve_var_path("fuel_mass", "AS_point_0", []) == "fuel_mass"
    assert _resolve_var_path("W0_without_point_masses", "AS_point_0", []) == "W0_without_point_masses"
    assert _resolve_var_path("point_masses", "AS_point_0", []) == "point_masses"
    assert _resolve_var_path("point_mass_locations", "AS_point_0", []) == "point_mass_locations"


def test_resolve_aero_only_perf_outputs():
    """Aero-only CL/CD resolve without _perf subgroup."""
    assert _resolve_var_path("CL", "aero_point_0", ["wing"],
                             component_type="oas/AeroPoint") == "aero_point_0.CL"
    assert _resolve_var_path("CD", "aero_point_0", ["wing"],
                             component_type="oas/AeroPoint") == "aero_point_0.CD"
    assert _resolve_var_path("CM", "aero_point_0", ["wing"],
                             component_type="oas/AeroPoint") == "aero_point_0.CM"


def test_resolve_aerostruct_perf_outputs():
    """Aerostruct CL/CD resolve with _perf subgroup."""
    assert _resolve_var_path("CL", "AS_point_0", ["wing"],
                             component_type="oas/AerostructPoint") == "AS_point_0.wing_perf.CL"
    assert _resolve_var_path("CD", "AS_point_0", ["wing"],
                             component_type="oas/AerostructPoint") == "AS_point_0.wing_perf.CD"


def test_resolve_multipoint_toplevel_constraints():
    """Top-level multipoint constraints resolve correctly."""
    assert _resolve_var_path("fuel_vol_delta", "AS_point_0", []) == "fuel_vol_delta.fuel_vol_delta"
    assert _resolve_var_path("fuel_diff", "AS_point_0", []) == "fuel_diff"


def test_resolve_per_point_constraint():
    """Constraint paths use the provided point_name."""
    # failure at point 0 vs point 1
    path0 = _resolve_var_path("failure", "AS_point_0", ["wing"])
    path1 = _resolve_var_path("failure", "AS_point_1", ["wing"])
    assert path0 == "AS_point_0.wing_perf.failure"
    assert path1 == "AS_point_1.wing_perf.failure"


# ---------------------------------------------------------------------------
# Factory topology
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_multipoint_factory_topology():
    """Multipoint factory creates N AerostructPoint groups with shared geometry."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 5,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "fem_model_type": "tube",
            "E": 70.0e9,
            "G": 30.0e9,
            "yield_stress": 500.0e6,
            "mrho": 3000.0,
        }],
    }
    operating_points = {
        "flight_points": [
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 1.0},
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 2.5},
        ],
        "shared": {"W0_without_point_masses": 5000.0, "R": 3e6},
    }

    prob, metadata = build_oas_aerostruct_multipoint(component_config, operating_points)

    # Metadata shape
    assert metadata["multipoint"] is True
    assert metadata["point_names"] == ["AS_point_0", "AS_point_1"]
    assert metadata["point_name"] == "AS_point_0"
    assert metadata["surface_names"] == ["wing"]
    assert len(metadata["flight_points"]) == 2

    # Setup should succeed
    prob.setup()

    # Model topology: shared geometry + two analysis points
    subsystem_names = [s.name for s in prob.model.system_iter(
        include_self=False, recurse=False)]
    assert "prob_vars" in subsystem_names
    assert "W0_comp" in subsystem_names
    assert "wing" in subsystem_names  # shared geometry
    assert "AS_point_0" in subsystem_names
    assert "AS_point_1" in subsystem_names

    prob.cleanup()


@pytest.mark.slow
def test_multipoint_analysis():
    """Multipoint problem runs and produces results at both points."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 5,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "fem_model_type": "tube",
            "E": 70.0e9,
            "G": 30.0e9,
            "yield_stress": 500.0e6,
            "mrho": 3000.0,
        }],
    }
    operating_points = {
        "flight_points": [
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 1.0},
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 2.5},
        ],
        "shared": {"W0_without_point_masses": 5000.0, "R": 3e6},
    }

    prob, metadata = build_oas_aerostruct_multipoint(component_config, operating_points)
    prob.setup()
    prob.run_model()

    # Both points should produce aerodynamic results
    CL_0 = float(prob.get_val("AS_point_0.CL")[0])
    CD_0 = float(prob.get_val("AS_point_0.CD")[0])
    CL_1 = float(prob.get_val("AS_point_1.CL")[0])
    CD_1 = float(prob.get_val("AS_point_1.CD")[0])

    assert CL_0 > 0, f"Cruise CL should be > 0, got {CL_0}"
    assert CD_0 > 0, f"Cruise CD should be > 0, got {CD_0}"
    # Maneuver point has alpha_maneuver=0 by default in run_model,
    # so CL may be ~0. Just verify CD is computed (always > 0 due to CD0).
    assert CD_1 > 0, f"Maneuver CD should be > 0, got {CD_1}"

    # Structural mass should be shared (same geometry)
    mass_0 = float(prob.get_val("wing.structural_mass"))
    assert mass_0 > 0, f"Structural mass should be > 0, got {mass_0}"

    prob.cleanup()


# ---------------------------------------------------------------------------
# Golden optimization test
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_multipoint_optimization_golden():
    """Multipoint CD minimization matches OAS MCP golden values.

    Golden reference generated via OAS MCP server run_optimization
    (run_id: 20260406T135052_6dc05e8528f86f64).
    """
    golden_path = GOLDEN_DIR / "golden_multipoint.json"
    with open(golden_path) as f:
        golden = json.load(f)

    expected = golden["expected"]
    tols = golden["tolerances"]

    # Build the same problem
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 7,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "fem_model_type": "tube",
            "E": 7.0e10,
            "G": 3.0e10,
            "yield_stress": 5.0e8,
            "mrho": 3000.0,
            "safety_factor": 1.5,
            "with_viscous": True,
            "CD0": 0.015,
        }],
    }
    operating_points = {
        "flight_points": golden["flight_points"],
        "shared": golden["shared"],
    }

    prob, metadata = build_oas_aerostruct_multipoint(component_config, operating_points)

    # Configure optimizer
    import openmdao.api as om
    driver = om.ScipyOptimizeDriver()
    driver.options["optimizer"] = "SLSQP"
    driver.options["tol"] = 1e-8
    driver.options["maxiter"] = 200
    prob.driver = driver

    # Design variables
    prob.model.add_design_var("wing.twist_cp", lower=-5, upper=10, scaler=0.1)
    prob.model.add_design_var("wing.thickness_cp", lower=0.001, upper=0.1, scaler=100)
    prob.model.add_design_var("alpha", lower=-5, upper=10)
    prob.model.add_design_var("alpha_maneuver", lower=-5, upper=10)

    # Constraints
    prob.model.add_constraint("AS_point_0.wing_perf.CL", equals=0.5)
    prob.model.add_constraint("AS_point_0.wing_perf.failure", upper=0.0)
    prob.model.add_constraint("AS_point_1.wing_perf.failure", upper=0.0)

    # Objective
    prob.model.add_objective("AS_point_0.CD")

    prob.setup()
    prob.run_driver()

    # Verify cruise results
    CL_cruise = float(prob.get_val("AS_point_0.wing_perf.CL")[0])
    CD_cruise = float(prob.get_val("AS_point_0.CD")[0])
    fail_cruise = float(np.max(prob.get_val("AS_point_0.wing_perf.failure")))

    assert CL_cruise == pytest.approx(expected["cruise"]["CL"],
                                       rel=tols["CL"]["rel"])
    assert CD_cruise == pytest.approx(expected["cruise"]["CD"],
                                       rel=tols["CD"]["rel"])
    assert fail_cruise <= 0.0, f"Cruise failure > 0: {fail_cruise}"

    # Verify maneuver results
    fail_maneuver = float(np.max(prob.get_val("AS_point_1.wing_perf.failure")))
    assert fail_maneuver <= 0.0, f"Maneuver failure > 0: {fail_maneuver}"

    # Verify structural mass
    mass = float(np.sum(prob.get_val("wing.structural_mass")))
    assert mass == pytest.approx(expected["cruise"]["structural_mass_kg"],
                                  rel=tols["structural_mass_kg"]["rel"])

    prob.cleanup()


# ---------------------------------------------------------------------------
# Assembler round-trip
# ---------------------------------------------------------------------------


def test_multipoint_assemble_roundtrip(tmp_path):
    """Multipoint plan directory assembles and validates correctly."""
    import shutil
    from hangar.omd.assemble import assemble_plan

    fixture = FIXTURES_DIR / "oas_aerostruct_multipoint"
    plan_dir = tmp_path / "mp_plan"
    shutil.copytree(fixture, plan_dir)

    result = assemble_plan(plan_dir)

    assert result["errors"] == [], f"Assembly errors: {result['errors']}"
    plan = result["plan"]
    assert "flight_points" in plan["operating_points"]
    assert len(plan["operating_points"]["flight_points"]) == 2
    assert plan["components"][0]["type"] == "oas/AerostructMultipoint"

    # Constraints should have point fields
    constraints = plan.get("constraints", [])
    point_cons = [c for c in constraints if "point" in c]
    assert len(point_cons) > 0


# ---------------------------------------------------------------------------
# Single-point regression
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_single_point_still_works():
    """Existing single-point factory still works unchanged."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 5,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "fem_model_type": "tube",
            "E": 70.0e9,
            "G": 30.0e9,
            "yield_stress": 500.0e6,
            "mrho": 3000.0,
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    assert metadata["point_name"] == "AS_point_0"
    assert "multipoint" not in metadata

    prob.setup()
    prob.run_model()

    CL = float(prob.get_val("AS_point_0.CL")[0])
    assert CL > 0
    prob.cleanup()


# ---------------------------------------------------------------------------
# Wingbox FEM
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_wingbox_aerostruct_runs():
    """Wingbox FEM model builds and runs correctly."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "CRM",
            "num_x": 2,
            "num_y": 5,
            "symmetry": True,
            "fem_model_type": "wingbox",
            "E": 73.1e9,
            "G": 28.0e9,
            "yield_stress": 324.0e6,
            "mrho": 2780.0,
            "safety_factor": 1.5,
            "spar_thickness_cp": [0.004, 0.005, 0.008],
            "skin_thickness_cp": [0.005, 0.010, 0.015],
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    prob.setup()
    prob.run_model()

    CL = float(prob.get_val("AS_point_0.CL")[0])
    assert CL > 0, f"Wingbox CL should be > 0, got {CL}"

    # Wingbox has structural mass
    mass = float(prob.get_val("wing.structural_mass"))
    assert mass > 0, f"Structural mass should be > 0, got {mass}"

    prob.cleanup()


@pytest.mark.slow
def test_multipoint_wingbox_fuel_volume():
    """Multipoint wingbox has fuel_vol_delta and fuel_diff subsystems."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "CRM",
            "num_x": 2,
            "num_y": 5,
            "symmetry": True,
            "fem_model_type": "wingbox",
            "E": 73.1e9,
            "G": 28.0e9,
            "yield_stress": 324.0e6,
            "mrho": 2780.0,
            "safety_factor": 1.5,
            "spar_thickness_cp": [0.004, 0.005, 0.008],
            "skin_thickness_cp": [0.005, 0.010, 0.015],
        }],
    }
    operating_points = {
        "flight_points": [
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 1.0},
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 2.5},
        ],
        "shared": {"W0_without_point_masses": 25000.0, "R": 3e6},
    }

    prob, metadata = build_oas_aerostruct_multipoint(component_config, operating_points)
    prob.setup()

    # Verify fuel volume subsystems exist
    subsystem_names = [s.name for s in prob.model.system_iter(
        include_self=False, recurse=False)]
    assert "fuel_vol_delta" in subsystem_names
    assert "fuel_diff" in subsystem_names

    prob.run_model()

    # fuel_vol_delta should produce a value
    fvd = prob.get_val("fuel_vol_delta.fuel_vol_delta")
    assert fvd is not None

    prob.cleanup()


@pytest.mark.slow
def test_wingbox_golden():
    """Wingbox analysis matches golden reference values."""
    golden_path = GOLDEN_DIR / "golden_wingbox.json"
    with open(golden_path) as f:
        golden = json.load(f)

    expected = golden["expected"]
    tols = golden["tolerances"]

    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "CRM",
            "num_x": 2,
            "num_y": 7,
            "symmetry": True,
            "fem_model_type": "wingbox",
            "E": 73.1e9,
            "G": 28.0e9,
            "yield_stress": 324.0e6,
            "mrho": 2780.0,
            "safety_factor": 1.5,
            "spar_thickness_cp": [0.004, 0.005, 0.005, 0.008],
            "skin_thickness_cp": [0.005, 0.010, 0.015, 0.020],
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
        "W0": 25000.0,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    prob.setup()
    prob.run_model()

    CL = float(prob.get_val("AS_point_0.CL")[0])
    CD = float(prob.get_val("AS_point_0.CD")[0])
    failure = float(np.max(prob.get_val("AS_point_0.wing_perf.failure")))
    mass = float(np.sum(prob.get_val("wing.structural_mass")))

    prob.cleanup()

    assert CL == pytest.approx(expected["CL"], rel=tols["CL"]["rel"])
    assert CD == pytest.approx(expected["CD"], rel=tols["CD"]["rel"])
    assert failure == pytest.approx(expected["failure"], abs=tols["failure"]["abs"])
    assert mass == pytest.approx(expected["structural_mass_kg"],
                                  rel=tols["structural_mass_kg"]["rel"])


# ---------------------------------------------------------------------------
# Point masses
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_multipoint_with_point_masses():
    """Multipoint problem with point masses computes correct W0."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 5,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "fem_model_type": "tube",
            "E": 70.0e9,
            "G": 30.0e9,
            "yield_stress": 500.0e6,
            "mrho": 3000.0,
            "n_point_masses": 1,
        }],
    }
    operating_points = {
        "flight_points": [
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 1.0},
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 2.5},
        ],
        "shared": {
            "W0_without_point_masses": 5000.0,
            "R": 3e6,
            "point_masses": [[5000.0]],
            "point_mass_locations": [[2.0, 3.0, 0.0]],
        },
    }

    prob, metadata = build_oas_aerostruct_multipoint(component_config, operating_points)
    prob.setup()
    prob.run_model()

    W0 = float(prob.get_val("W0")[0])
    expected_W0 = 5000.0 + 2 * 5000.0  # W0_wpm + 2*sum(point_masses)
    assert W0 == pytest.approx(expected_W0, rel=1e-6), f"W0={W0}, expected={expected_W0}"
    prob.cleanup()


@pytest.mark.slow
def test_single_point_with_point_masses():
    """Single-point factory with point masses computes correct W0."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 5,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "fem_model_type": "tube",
            "E": 70.0e9,
            "G": 30.0e9,
            "yield_stress": 500.0e6,
            "mrho": 3000.0,
            "n_point_masses": 1,
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
        "W0_without_point_masses": 5000.0,
        "point_masses": [[3000.0]],
        "point_mass_locations": [[1.5, 2.5, 0.0]],
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    prob.setup()
    prob.run_model()

    W0 = float(prob.get_val("W0")[0])
    expected_W0 = 5000.0 + 2 * 3000.0
    assert W0 == pytest.approx(expected_W0, rel=1e-6), f"W0={W0}, expected={expected_W0}"

    CL = float(prob.get_val("AS_point_0.CL")[0])
    assert CL > 0
    prob.cleanup()
