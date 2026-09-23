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


# ---------------------------------------------------------------------------
# Workspace-first resolution (2026-09-23): on the http transport the server
# cwd and the plan workspace differ; write_plan and the plan_* builders only
# write into the workspace, so a same-named file next to the cwd must not
# shadow it. qwen arm, pyc_turbojet seed 0: assemble_plan(output=...) wrote
# next to the cwd, validate_plan kept reading that stale copy, three
# write_plan rewrites never counted.
# ---------------------------------------------------------------------------

def _minimal_plan_dir(plan_dir):
    import yaml

    plan_dir.mkdir(parents=True)
    (plan_dir / "metadata.yaml").write_text(
        yaml.dump({"id": "study", "name": "Study", "version": 1}))
    (plan_dir / "components").mkdir()
    (plan_dir / "components" / "wing.yaml").write_text(yaml.dump({
        "id": "wing", "type": "oas/AeroPoint",
        "config": {"surfaces": [{"name": "wing", "num_y": 5}]},
    }))
    (plan_dir / "operating_points.yaml").write_text(
        yaml.dump({"velocity": 248.136, "alpha": 5.0, "Mach_number": 0.84}))


@pytest.fixture
def cwd_and_workspace(tmp_path, monkeypatch):
    """A server cwd and a separate plan workspace, as on the http transport."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "omd_data"))
    from hangar.omd.tools._helpers import workspace_dir

    return cwd, workspace_dir()


def test_workspace_copy_wins_over_cwd_copy(cwd_and_workspace):
    from hangar.omd.tools._helpers import resolve_plan_dir, resolve_plan_path

    cwd, ws = cwd_and_workspace
    for root in (cwd, ws):
        (root / "study").mkdir()
        (root / "study" / "plan.yaml").write_text(f"metadata: {{id: {root.name}}}\n")
    assert resolve_plan_path("study/plan.yaml") == ws / "study" / "plan.yaml"
    assert resolve_plan_path("study", want_file=True) == ws / "study" / "plan.yaml"
    assert resolve_plan_dir("study") == ws / "study"


def test_cwd_is_still_the_fallback(cwd_and_workspace):
    from hangar.omd.tools._helpers import resolve_plan_dir, resolve_plan_path

    cwd, _ws = cwd_and_workspace
    (cwd / "local").mkdir()
    (cwd / "local" / "plan.yaml").write_text("metadata: {}\n")
    assert resolve_plan_path("local/plan.yaml") == cwd / "local" / "plan.yaml"
    assert resolve_plan_dir("local") == cwd / "local"


def test_not_found_before_assemble_names_the_next_call(cwd_and_workspace):
    from hangar.sdk.errors import UserInputError

    from hangar.omd.tools._helpers import resolve_plan_path

    cwd, ws = cwd_and_workspace
    _minimal_plan_dir(ws / "study")
    with pytest.raises(UserInputError) as exc:
        resolve_plan_path("study/plan.yaml")
    msg = str(exc.value)
    assert "assemble_plan(plan_dir='study')" in msg
    assert "'study/plan.yaml'" in msg
    # no host paths for a sandboxed agent to go hunting with
    assert str(cwd) not in msg and str(ws) not in msg


def test_not_found_elsewhere_points_at_the_workspace(cwd_and_workspace):
    from hangar.sdk.errors import UserInputError

    from hangar.omd.tools._helpers import resolve_plan_dir, resolve_plan_path

    cwd, ws = cwd_and_workspace
    with pytest.raises(UserInputError, match=r"read_plan\('\.'\)") as exc:
        resolve_plan_path("nope/plan.yaml")
    assert str(cwd) not in str(exc.value) and str(ws) not in str(exc.value)
    with pytest.raises(UserInputError, match="plan_init") as exc:
        resolve_plan_dir("nope")
    assert str(ws) not in str(exc.value)


def test_assemble_plan_tool_relative_output_lands_in_the_workspace(cwd_and_workspace):
    import asyncio
    from pathlib import Path

    from hangar.omd.tools._helpers import resolve_plan_path
    from hangar.omd.tools.execution import assemble_plan

    cwd, ws = cwd_and_workspace
    _minimal_plan_dir(ws / "study")
    result = asyncio.run(assemble_plan("study", output="study/plan.yaml"))
    assert result["errors"] == []
    assert Path(result["output_path"]) == ws / "study" / "plan.yaml"
    assert not (cwd / "study").exists()
    # and the readers now find exactly that file
    assert resolve_plan_path("study/plan.yaml") == ws / "study" / "plan.yaml"
