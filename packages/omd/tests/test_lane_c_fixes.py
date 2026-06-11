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
