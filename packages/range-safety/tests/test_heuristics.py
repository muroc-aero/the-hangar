"""Tests for engineering heuristic validation."""

from __future__ import annotations

from hangar.range_safety.validators.heuristics import validate_heuristics


def test_reasonable_plan_passes(valid_aerostruct_plan, catalog_dir):
    """A reasonable plan produces no errors."""
    findings = validate_heuristics(valid_aerostruct_plan, catalog_dir=catalog_dir)
    errors = [f for f in findings if f["severity"] == "error"]
    assert errors == [], f"Unexpected errors: {errors}"


def test_out_of_range_mach_warns(valid_aero_plan, catalog_dir):
    """Mach number outside typical range warns."""
    valid_aero_plan["operating_points"]["Mach_number"] = 10.0
    findings = validate_heuristics(valid_aero_plan, catalog_dir=catalog_dir)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "operating_point_range" for f in warnings)


def test_negative_rho_warns(valid_aero_plan, catalog_dir):
    """Negative air density warns."""
    valid_aero_plan["operating_points"]["rho"] = -0.5
    findings = validate_heuristics(valid_aero_plan, catalog_dir=catalog_dir)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "operating_point_range" for f in warnings)


def test_dv_bounds_outside_catalog_warns(valid_aerostruct_plan, catalog_dir):
    """DV bounds exceeding catalog range warns."""
    # twist_cp catalog range is [-10, 15]
    valid_aerostruct_plan["design_variables"][0]["upper"] = 50.0
    findings = validate_heuristics(valid_aerostruct_plan, catalog_dir=catalog_dir)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "dv_bounds_catalog" for f in warnings)


def test_large_range_no_scaler_warns(catalog_dir):
    """Large DV range without scaler warns."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "oas/AerostructPoint", "config": {"surfaces": [{"name": "w", "num_y": 7, "fem_model_type": "tube", "E": 70e9, "G": 30e9, "yield_stress": 500e6, "mrho": 3000}]}}],
        "design_variables": [
            {"name": "some_var", "lower": 0.001, "upper": 1.0},  # ratio 1000
        ],
        "objective": {"name": "CD"},
    }
    findings = validate_heuristics(plan, catalog_dir=catalog_dir)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "dv_scaler_recommended" for f in warnings)


def test_objective_without_dvs_errors(catalog_dir):
    """Objective with no DVs is an error."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "oas/AeroPoint", "config": {"surfaces": [{"name": "w", "num_y": 7}]}}],
        "objective": {"name": "CD"},
    }
    findings = validate_heuristics(plan, catalog_dir=catalog_dir)
    errors = [f for f in findings if f["severity"] == "error"]
    assert any(f["check"] == "optimization_has_dvs" for f in errors)


def test_coarse_mesh_for_optimization_warns(catalog_dir):
    """num_y=3 for optimization warns."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "oas/AeroPoint", "config": {"surfaces": [{"name": "w", "num_y": 3}]}}],
        "design_variables": [{"name": "twist_cp", "lower": -10, "upper": 15}],
        "objective": {"name": "CD"},
    }
    findings = validate_heuristics(plan, catalog_dir=catalog_dir)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "mesh_density_optimization" for f in warnings)
