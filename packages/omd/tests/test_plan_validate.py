"""Tests for semantic plan validation (var-path resolution + component types)."""

from __future__ import annotations

from hangar.omd.plan_validate import (
    validate_var_paths,
    validate_plan_semantic,
)


def _minimal_plan() -> dict:
    return {
        "components": [{"id": "c0", "type": "oas/AeroPoint", "config": {}}],
        "design_variables": [],
        "constraints": [],
    }


def test_clean_plan_no_findings():
    plan = _minimal_plan()
    plan["design_variables"] = [{"name": "twist_cp"}]
    plan["constraints"] = [{"name": "CL"}]
    plan["objective"] = {"name": "CD"}
    assert validate_var_paths(plan) == []


def test_pipe_separated_paths_pass_through():
    plan = _minimal_plan()
    plan["components"] = [{"id": "c0", "type": "ocp/BasicMission", "config": {}}]
    plan["design_variables"] = [{"name": "ac|geom|wing|S_ref"}]
    plan["constraints"] = [{"name": "ac|weights|MTOW"}]
    assert validate_var_paths(plan) == []


def test_dotted_paths_pass_through():
    plan = _minimal_plan()
    plan["design_variables"] = [{"name": "wing.twist_cp"}]
    assert validate_var_paths(plan) == []


def test_misspelled_dv_name_flagged_with_suggestion():
    plan = _minimal_plan()
    plan["design_variables"] = [{"name": "twsit_cp"}]  # typo
    findings = validate_var_paths(plan)
    assert len(findings) == 1
    assert findings[0].path == "design_variables[0].name"
    assert "twsit_cp" in findings[0].message
    assert "twist_cp" in findings[0].suggestions


def test_misspelled_constraint_name_flagged():
    plan = _minimal_plan()
    plan["constraints"] = [{"name": "CLL"}]  # typo of CL
    findings = validate_var_paths(plan)
    assert len(findings) == 1
    assert findings[0].path == "constraints[0].name"
    assert "CL" in findings[0].suggestions


def test_misspelled_objective_name_flagged():
    plan = _minimal_plan()
    plan["objective"] = {"name": "CDs"}  # typo of CD
    findings = validate_var_paths(plan)
    assert len(findings) == 1
    assert findings[0].path == "objective.name"
    assert "CD" in findings[0].suggestions


def test_unknown_component_type_flagged():
    plan = _minimal_plan()
    plan["components"] = [{"id": "c0", "type": "oas/AeroPointt", "config": {}}]
    registry_types = {"oas/AeroPoint", "oas/AerostructPoint", "paraboloid/Paraboloid"}
    findings = validate_plan_semantic(plan, registry_types=registry_types)
    # One finding for the unknown type
    type_findings = [f for f in findings if f.path.endswith(".type")]
    assert len(type_findings) == 1
    assert "oas/AeroPoint" in type_findings[0].suggestions


def test_known_component_type_not_flagged():
    plan = _minimal_plan()
    registry_types = {"oas/AeroPoint"}
    findings = validate_plan_semantic(plan, registry_types=registry_types)
    type_findings = [f for f in findings if f.path.endswith(".type")]
    assert type_findings == []


def test_empty_plan_no_findings():
    findings = validate_plan_semantic({})
    assert findings == []


def test_generic_promoted_names_recognized():
    """alpha, v, rho etc. are globally promoted and should never be flagged."""
    plan = _minimal_plan()
    plan["design_variables"] = [
        {"name": "alpha"},
        {"name": "load_factor"},
        {"name": "fuel_mass"},
    ]
    assert validate_var_paths(plan) == []


def test_ocp_short_names_recognized():
    plan = _minimal_plan()
    plan["components"] = [{"id": "c0", "type": "ocp/BasicMission", "config": {}}]
    plan["constraints"] = [{"name": "fuel_burn"}, {"name": "MTOW"}]
    assert validate_var_paths(plan) == []
