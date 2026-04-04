"""Tests for requirements traceability validation."""

from __future__ import annotations

from hangar.range_safety.validators.traceability import validate_traceability


def test_well_traced_plan_passes(valid_aerostruct_plan):
    """A fully traced plan produces no errors."""
    findings = validate_traceability(valid_aerostruct_plan)
    errors = [f for f in findings if f["severity"] == "error"]
    assert errors == [], f"Unexpected errors: {errors}"


def test_no_requirements_passes(valid_aero_plan):
    """Plan without requirements has nothing to check."""
    findings = validate_traceability(valid_aero_plan)
    assert findings == []


def test_orphan_requirement():
    """Requirement not referenced by any DV/constraint/objective is warned."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "t", "config": {}}],
        "requirements": [
            {"id": "R1", "text": "Something", "traces_to": ["twist_cp"]},
        ],
        "design_variables": [
            {"name": "twist_cp"},  # no traces_to back to R1
        ],
    }
    findings = validate_traceability(plan)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "orphan_requirement" for f in warnings)


def test_bad_traces_to_target():
    """Requirement tracing to nonexistent DV/constraint/objective is an error."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "t", "config": {}}],
        "requirements": [
            {"id": "R1", "text": "Something", "traces_to": ["nonexistent_var"]},
        ],
    }
    findings = validate_traceability(plan)
    errors = [f for f in findings if f["severity"] == "error"]
    assert any(f["check"] == "traces_to_target_exists" for f in errors)


def test_dv_traces_to_bad_requirement():
    """DV tracing to nonexistent requirement ID is an error."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "t", "config": {}}],
        "requirements": [
            {"id": "R1", "text": "Something", "traces_to": ["twist_cp"]},
        ],
        "design_variables": [
            {"name": "twist_cp", "traces_to": ["R_NONEXISTENT"]},
        ],
    }
    findings = validate_traceability(plan)
    errors = [f for f in findings if f["severity"] == "error"]
    assert any(f["check"] == "dv_traces_to_requirement" for f in errors)


def test_requirement_without_traces_warns():
    """Requirement with no traces_to is a warning."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "t", "config": {}}],
        "requirements": [
            {"id": "R1", "text": "Something"},  # no traces_to
        ],
    }
    findings = validate_traceability(plan)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "requirement_has_traces" for f in warnings)


def test_objective_without_traces_warns():
    """Objective without traces_to is a warning."""
    plan = {
        "metadata": {"id": "t", "name": "t", "version": 1},
        "components": [{"id": "w", "type": "t", "config": {}}],
        "requirements": [
            {"id": "R1", "text": "Min mass", "traces_to": ["structural_mass"]},
        ],
        "objective": {"name": "structural_mass"},  # no traces_to
    }
    findings = validate_traceability(plan)
    warnings = [f for f in findings if f["severity"] == "warning"]
    assert any(f["check"] == "objective_has_traces" for f in warnings)
