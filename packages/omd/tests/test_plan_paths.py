"""Tests for hangar.omd.plan_paths.resolve_element_path."""

from __future__ import annotations

import pytest

from hangar.omd.plan_paths import (
    element_entity_id,
    resolve_element_path,
)


PLAN = {
    "metadata": {"id": "p", "name": "p", "version": 1},
    "components": [
        {
            "id": "wing",
            "type": "oas/AerostructPoint",
            "config": {
                "surfaces": [
                    {"name": "wing", "num_y": 7, "num_x": 2, "E": 7e10},
                ],
            },
        },
    ],
    "design_variables": [
        {"name": "wing.twist_cp", "lower": -10, "upper": 15},
        {"name": "wing.thickness_cp", "lower": 0.003, "upper": 0.1},
    ],
    "constraints": [
        {"name": "AS_point_0.wing_perf.failure", "upper": 0.0},
    ],
    "objective": {"name": "wing.structural_mass"},
    "requirements": [
        {"id": "R1", "text": "minimize mass"},
    ],
    "analysis_plan": {
        "phases": [{"id": "phase-1"}],
    },
}


def test_resolve_bracket_id():
    r = resolve_element_path(PLAN, "components[wing]")
    assert r is not None
    assert r.value["id"] == "wing"
    assert r.entity_kind == "component"
    assert r.entity_key == "components[wing]"


def test_resolve_nested_dot_path():
    r = resolve_element_path(
        PLAN, "components[wing].config.surfaces[wing].num_y"
    )
    assert r is not None
    assert r.value == 7
    assert "surfaces[wing]" in r.entity_key


def test_resolve_design_variable_by_name():
    r = resolve_element_path(PLAN, "design_variables[wing.twist_cp]")
    assert r is not None
    assert r.value["name"] == "wing.twist_cp"
    assert r.entity_kind == "design_variable"


def test_resolve_constraint_by_name():
    r = resolve_element_path(
        PLAN, "constraints[AS_point_0.wing_perf.failure]"
    )
    assert r is not None
    assert r.entity_kind == "constraint"


def test_resolve_objective():
    r = resolve_element_path(PLAN, "objective")
    assert r is not None
    assert r.value["name"] == "wing.structural_mass"


def test_resolve_requirement():
    r = resolve_element_path(PLAN, "requirements[R1]")
    assert r is not None
    assert r.entity_kind == "requirement"


def test_resolve_phase():
    r = resolve_element_path(
        PLAN, "analysis_plan.phases[phase-1]"
    )
    assert r is not None
    assert r.entity_kind == "phase"


def test_resolve_positional_fallback():
    plan = {"connections": [{"src": "a", "tgt": "b"}]}
    r = resolve_element_path(plan, "connections[0].src")
    assert r is not None
    assert r.value == "a"


def test_unresolvable_returns_none():
    assert resolve_element_path(PLAN, "components[gone]") is None
    assert resolve_element_path(PLAN, "does.not.exist") is None


def test_empty_path_returns_none():
    assert resolve_element_path(PLAN, "") is None
    assert resolve_element_path(PLAN, None) is None


def test_malformed_path_returns_none():
    # Brackets without matching close should resolve to None rather than raise
    assert resolve_element_path(PLAN, "components[wing") is None


def test_element_entity_id_is_stable():
    r = resolve_element_path(PLAN, "components[wing]")
    assert r is not None
    eid = element_entity_id("plan-p/v1", r)
    assert eid == "plan-p/v1/elem/components[wing]"


# ---------------------------------------------------------------------------
# resolve_plan_path with want_file (2026-09-22): a plan DIRECTORY handed to
# run_plan / validate_plan used to surface as a bare "Is a directory".
# ---------------------------------------------------------------------------

def test_want_file_resolves_a_plan_dir_to_its_assembled_yaml(tmp_path, monkeypatch):
    from hangar.omd.tools._helpers import resolve_plan_path

    d = tmp_path / "study"
    d.mkdir()
    (d / "plan.yaml").write_text("metadata: {}\n")
    monkeypatch.chdir(tmp_path)
    assert resolve_plan_path("study", want_file=True) == d / "plan.yaml"
    assert resolve_plan_path("study") == d            # default: dirs pass through


def test_want_file_names_plan_yaml_when_the_dir_is_not_assembled(tmp_path, monkeypatch):
    from hangar.sdk.errors import UserInputError

    from hangar.omd.tools._helpers import resolve_plan_path

    d = tmp_path / "study"
    (d / "components").mkdir(parents=True)
    (d / "metadata.yaml").write_text("id: study\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(UserInputError, match=r"assemble_plan.*study/plan\.yaml"):
        resolve_plan_path("study", want_file=True)
