"""Regression tests for the blind Lane C parity-run fixes.

Each test pins one of the tool-surface gaps found by giving agents only
the Lane C task prompts and the MCP tools (docs/FEATURE_BACKLOG.md,
2026-06-10). The slow end-to-end behavior (DV retrieval after a real
optimize, conclusion verdicts on a mission run) is covered by
examples/tests/test_parity_lane_c.py; these stay fast and unit-level.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from hangar.omd.plan_validate import validate_component_config
from hangar.omd.recorder import _extract_case_data
from hangar.omd.run import _wallclock_timeout


# ---------------------------------------------------------------------------
# Recorder: promoted outputs (auto-IVC DVs) must survive the import
# ---------------------------------------------------------------------------


class _FakeCase:
    """Mimics an OpenMDAO Case: absolute names in list_outputs, promoted
    names (including auto-IVC DVs) only in .outputs."""

    def __init__(self):
        self.outputs = {
            "f_xy": np.array([-27.333]),
            "x": np.array([6.667]),
            "y": np.array([-7.333]),
        }

    def list_outputs(self, out_stream=None, return_format="dict"):
        return {"paraboloid.f_xy": {"val": np.array([-27.333])}}


def test_case_import_includes_promoted_dvs():
    data = _extract_case_data(_FakeCase())
    assert data["paraboloid.f_xy"] == pytest.approx(-27.333)
    assert data["x"] == pytest.approx(6.667)
    assert data["y"] == pytest.approx(-7.333)


# ---------------------------------------------------------------------------
# Timeout: must work off the main thread (MCP tools run via to_thread)
# ---------------------------------------------------------------------------


def test_wallclock_timeout_off_main_thread_no_crash():
    """A generous timeout in a worker thread must not raise (was: 'signal
    only works in main thread of the main interpreter')."""
    errors = []

    def work():
        try:
            with _wallclock_timeout(60):
                pass
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=work)
    t.start()
    t.join(10)
    assert not errors, errors


def test_wallclock_timeout_fires_off_main_thread():
    result = {}

    def work():
        try:
            with _wallclock_timeout(1):
                deadline = time.time() + 10
                while time.time() < deadline:
                    pass
            result["timed_out"] = False
        except TimeoutError:
            result["timed_out"] = True

    t = threading.Thread(target=work)
    t.start()
    t.join(15)
    assert result.get("timed_out") is True


# ---------------------------------------------------------------------------
# Preflight: unknown component config keys for closed-config factories
# ---------------------------------------------------------------------------


def _findings_for(config: dict, ctype: str = "ocp/BasicMission"):
    plan = {"components": [{"id": "c1", "type": ctype, "config": config}]}
    return validate_component_config(plan)


def test_config_typo_template_is_caught_with_suggestion():
    findings = _findings_for({"template": "caravan"})
    assert len(findings) == 1
    assert findings[0].path == "components[0].config.template"
    assert "aircraft_template" in findings[0].suggestions


def test_paraboloid_config_inputs_rejected():
    findings = _findings_for({"x": 1.0, "y": 2.0}, ctype="paraboloid/Paraboloid")
    assert {f.path for f in findings} == {
        "components[0].config.x", "components[0].config.y",
    }
    assert all("operating_points" in f.message for f in findings)


def test_mission_params_typo_is_caught_with_suggestion():
    findings = _findings_for({
        "aircraft_template": "caravan",
        "mission_params": {"mission_range_nm": 250},
    })
    assert len(findings) == 1
    assert "mission_range_NM" in findings[0].suggestions


def test_valid_ocp_config_passes():
    findings = _findings_for({
        "aircraft_template": "caravan",
        "architecture": "turboprop",
        "num_nodes": 11,
        "mission_params": {
            "mission_range_NM": 250, "cruise_altitude_ft": 18000,
            "climb_vs_ftmin": 850, "climb_Ueas_kn": 104,
            "cruise_Ueas_kn": 129, "descent_vs_ftmin": 400,
            "descent_Ueas_kn": 100, "cruise_hybridization": 0.2,
        },
        "slots": {"drag": {"provider": "oas/vlm",
                           "config": {"num_x": 2, "num_y": 7}}},
    })
    assert findings == []


def test_permissive_factories_not_enforced():
    findings = _findings_for({"anything_goes": 1}, ctype="oas/AeroPoint")
    assert findings == []
    findings = _findings_for({"anything_goes": 1}, ctype="pyc/TurbojetDesign")
    assert findings == []


# ---------------------------------------------------------------------------
# Slots: surrogate-training pool must use spawn, not fork
# ---------------------------------------------------------------------------


def test_training_pool_forced_to_spawn():
    """OpenConcept trains VLM surrogates with mp.Pool(); a forked pool
    deadlocks under the threaded MCP server (blind coupled Lane C run,
    2026-06-10). The slot builders must repoint the module to a spawn
    context."""
    pytest.importorskip("openconcept")
    from multiprocessing.context import SpawnContext

    from hangar.omd.slots import _force_spawn_training_pool

    _force_spawn_training_pool()

    from openconcept.aerodynamics.openaerostruct import drag_polar

    assert isinstance(drag_polar.mp, SpawnContext)
    assert callable(drag_polar.mp.Pool)


# ---------------------------------------------------------------------------
# run_plan tool: server-side default timeout
# ---------------------------------------------------------------------------


@pytest.fixture()
def _captured_run(monkeypatch, tmp_path):
    """Stub the run pipeline and capture the timeout the tool resolves."""
    import yaml

    import hangar.omd.run as run_mod
    from hangar.omd.tools import execution

    captured = {}

    def fake_run_plan(path, **kwargs):
        captured.update(kwargs)
        return {"run_id": "run-test", "status": "completed", "summary": {}}

    monkeypatch.setattr(run_mod, "run_plan", fake_run_plan)
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "omd_data"))

    plan = {
        "metadata": {"id": "timeout-probe", "name": "Timeout probe", "version": 1},
        "components": [
            {"id": "p", "type": "paraboloid/Paraboloid", "config": {}}
        ],
        "operating_points": {"x": 1.0, "y": 2.0},
    }
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan))
    return execution, str(plan_path), captured


async def test_run_plan_applies_default_timeout(_captured_run):
    execution, plan_path, captured = _captured_run
    await execution.run_plan(plan_path)
    assert captured["timeout_seconds"] == execution._DEFAULT_TIMEOUT_SECONDS


async def test_run_plan_explicit_timeout_wins(_captured_run):
    execution, plan_path, captured = _captured_run
    await execution.run_plan(plan_path, timeout_seconds=120)
    assert captured["timeout_seconds"] == 120


async def test_run_plan_zero_disables_default(_captured_run):
    execution, plan_path, captured = _captured_run
    await execution.run_plan(plan_path, timeout_seconds=0)
    assert captured["timeout_seconds"] is None


# ---------------------------------------------------------------------------
# plan_mutate: rejected mutations must not persist (coupled run, 2026-06-11)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _plan_dir(tmp_path):
    from hangar.omd.plan_mutate import init_plan

    d = tmp_path / "probe-plan"
    init_plan(d, plan_id="probe", name="Probe")
    return d


def test_failed_requirement_validation_rolls_back(_plan_dir):
    """A requirement that fails post-write schema validation must vanish;
    the corrected retry must not need replace=True (blind agent hit
    'requirement fuel-capacity already exists' after a rejected call)."""
    from hangar.sdk.errors import UserInputError

    from hangar.omd.plan_mutate import add_requirement

    bad = {"id": "fuel-capacity", "text": "ok", "statement": "extra key"}
    with pytest.raises(UserInputError):
        add_requirement(_plan_dir, req=bad)

    good = {"id": "fuel-capacity", "text": "Fuel burn within capacity"}
    req = add_requirement(_plan_dir, req=good)  # no replace=True needed
    assert req["id"] == "fuel-capacity"


def test_failed_replace_restores_prior_requirement(_plan_dir):
    from hangar.sdk.errors import UserInputError

    from hangar.omd.plan_mutate import add_requirement, load_partial

    add_requirement(_plan_dir, req={"id": "r1", "text": "original"})
    bad = {"id": "r1", "text": "edited", "statement": "extra key"}
    with pytest.raises(UserInputError):
        add_requirement(_plan_dir, req=bad, replace=True)

    reqs = load_partial(_plan_dir)["requirements"]
    assert reqs == [{"id": "r1", "text": "original"}]


def test_requirement_statement_alias_gets_hint(_plan_dir):
    from hangar.sdk.errors import UserInputError

    from hangar.omd.plan_mutate import add_requirement

    with pytest.raises(UserInputError, match="'statement'.*'text'"):
        add_requirement(
            _plan_dir, req={"id": "r1", "statement": "fuel must fit"}
        )


def test_requirement_criteria_object_rejected_with_shape(_plan_dir):
    """A single criterion mapping (not wrapped in a list) must fail before
    any write, with the expected shape in the message."""
    from hangar.sdk.errors import UserInputError

    from hangar.omd.plan_mutate import add_requirement, load_partial

    req = {
        "id": "r1",
        "text": "fuel within capacity",
        "acceptance_criteria": {
            "metric": "fuel_burn_kg", "comparator": "<=", "threshold": 150.0,
        },
    }
    with pytest.raises(UserInputError, match="LIST.*wrap"):
        add_requirement(_plan_dir, req=req)
    assert "requirements" not in load_partial(_plan_dir)


def test_failed_component_replace_restores_prior(_plan_dir):
    """replace=True + failed validation used to unlink the prior component
    file instead of restoring it."""
    from hangar.sdk.errors import UserInputError

    from hangar.omd.plan_mutate import add_component, load_partial

    add_component(
        _plan_dir, comp_id="p", comp_type="paraboloid/Paraboloid", config={}
    )
    with pytest.raises(UserInputError):
        add_component(
            _plan_dir, comp_id="p", comp_type=123, config={}, replace=True
        )

    comps = load_partial(_plan_dir)["components"]
    assert comps == [{"id": "p", "type": "paraboloid/Paraboloid", "config": {}}]


# ---------------------------------------------------------------------------
# read_plan: directory listings and file content must stay bounded
# ---------------------------------------------------------------------------


async def test_read_plan_directory_listing_is_capped(tmp_path, monkeypatch):
    """read_plan on a big directory returned 91k chars / 2008 files and blew
    the MCP token limit; listings are now paged."""
    from hangar.omd.tools import authoring

    monkeypatch.setattr(authoring, "_DIR_LISTING_LIMIT", 5)
    for i in range(12):
        (tmp_path / f"f{i:02d}.yaml").write_text("a: 1\n")

    page1 = await authoring.read_plan(str(tmp_path))
    assert page1["total_files"] == 12
    assert len(page1["files"]) == 5
    assert page1["truncated"] is True

    page3 = await authoring.read_plan(str(tmp_path), offset=10)
    assert page3["files"] == ["f10.yaml", "f11.yaml"]
    assert page3["truncated"] is False


async def test_read_plan_large_file_is_truncated(tmp_path, monkeypatch):
    from hangar.omd.tools import authoring

    monkeypatch.setattr(authoring, "_MAX_CONTENT_CHARS", 100)
    f = tmp_path / "big.yaml"
    f.write_text("x" * 250)

    first = await authoring.read_plan(str(f))
    assert len(first["content"]) == 100
    assert first["truncated"] is True
    assert first["total_chars"] == 250

    last = await authoring.read_plan(str(f), offset=200)
    assert len(last["content"]) == 50
    assert last["truncated"] is False


async def test_read_plan_small_file_unchanged(tmp_path):
    from hangar.omd.tools import authoring

    f = tmp_path / "small.yaml"
    f.write_text("a: 1\n")
    result = await authoring.read_plan(str(f))
    assert result == {"path": str(f), "is_dir": False, "content": "a: 1\n"}
