"""Tests for the generic script-step study runner (fake tool registry)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from hangar.sdk.study import run_study
from hangar.sdk.study.orchestrate import generate_study
from hangar.sdk.study.script_runner import make_script_runner

# ---------------------------------------------------------------------------
# Fake tool registry: records calls, mimics the {run_id, results} envelope
# shape real tools return. Module-level so single-worker runs (in-process)
# can assert on call order.
# ---------------------------------------------------------------------------

CALLS: list[tuple] = []


async def _setup(name: str = "thing"):
    CALLS.append(("setup", name))
    return {"created": name}


async def _analyze(alpha: float = 0.0, fail: bool = False):
    CALLS.append(("analyze", alpha))
    if fail:
        raise ValueError("boom")
    return {
        "run_id": f"run-a{alpha:g}",
        "results": {"CL": round(0.1 * alpha, 6), "success": alpha < 5.0},
    }


async def _post(run_id: str = ""):
    CALLS.append(("post", run_id))
    return {"saw": run_id}


async def _reset():
    CALLS.append(("reset",))
    return {"reset": True}


def _registry():
    return {"setup": _setup, "analyze": _analyze, "post": _post,
            "reset": _reset}


run_case, generate_case = make_script_runner("fakescript", _registry)


def _spec(tmp_path: Path, *, steps=None, script=None, spec_extra=None,
          alphas=(1.0, 2.0), outputs=None) -> Path:
    case_spec: dict = {}
    if steps is not None:
        case_spec["steps"] = steps
    if script is not None:
        case_spec["script"] = script
    case_spec.update(spec_extra or {})
    study = {
        "metadata": {"id": "script-study", "name": "Script", "version": 1},
        "defaults": {"runner": "fakescript", "spec": case_spec},
        "cases": [
            {"matrix": {
                "id_template": "a{alpha:g}",
                "axes": {"alpha": {"values": list(alphas)}},
                "bind": {"alpha": ["steps[an].args.alpha"]},
            }},
        ],
        "outputs": outputs if outputs is not None else [
            {"name": "CL", "path": "an:results.CL"},
        ],
    }
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(study))
    return path


_STEPS = [
    {"id": "prep", "tool": "setup", "args": {"name": "wing"}},
    {"id": "an", "tool": "analyze", "args": {"alpha": 0.0}},
]


def test_run_basic_outputs_and_run_ref(tmp_path):
    CALLS.clear()
    path = _spec(tmp_path, steps=_STEPS)
    result = run_study(path, workers=1, store_root=tmp_path / "store")

    assert result["batch"] == {"ran": 2, "succeeded": 2, "failed": 0,
                               "requested": 2}
    state = json.loads(
        (tmp_path / "store" / "script-study" / "state.json").read_text())
    rows = {e["case_id"]: e for e in state["cases"].values()}
    assert rows["a1"]["status"] == "completed"
    assert rows["a1"]["outputs"] == {"CL": 0.1}
    assert rows["a2"]["outputs"] == {"CL": 0.2}
    # run_ref defaults to the last run_id any step returned
    assert rows["a1"]["run_ref"] == "run-a1"
    # the bound alpha actually reached the tool
    assert ("analyze", 1.0) in CALLS and ("analyze", 2.0) in CALLS
    # session state cleared before every case
    assert CALLS.count(("reset",)) == 2


def test_run_ref_interpolation_between_steps(tmp_path):
    CALLS.clear()
    steps = _STEPS + [
        {"id": "after", "tool": "post", "args": {"run_id": "$prev.run_id"}},
    ]
    path = _spec(tmp_path, steps=steps, alphas=(3.0,))
    result = run_study(path, workers=1, store_root=tmp_path / "store")
    assert result["batch"]["succeeded"] == 1
    assert ("post", "run-a3") in CALLS


def test_first_failing_step_fails_case_and_stops(tmp_path):
    CALLS.clear()
    steps = [
        {"id": "prep", "tool": "setup", "args": {}},
        {"id": "an", "tool": "analyze", "args": {"alpha": 0.0, "fail": True}},
        {"id": "after", "tool": "post", "args": {"run_id": "x"}},
    ]
    path = _spec(tmp_path, steps=steps, alphas=(1.0,))
    result = run_study(path, workers=1, store_root=tmp_path / "store")

    assert result["batch"]["failed"] == 1
    state = json.loads(
        (tmp_path / "store" / "script-study" / "state.json").read_text())
    entry = next(iter(state["cases"].values()))
    assert entry["status"] == "failed"
    assert "step 1 (analyze)" in entry["error"]
    assert "boom" in entry["error"]
    assert not any(c[0] == "post" for c in CALLS)


def test_success_when_maps_to_converged_or_failed(tmp_path):
    CALLS.clear()
    path = _spec(
        tmp_path,
        steps=_STEPS,
        spec_extra={"success_when": {"step": "an", "path": "results.success"}},
        alphas=(2.0, 7.0),  # success flag is alpha < 5
    )
    run_study(path, workers=1, store_root=tmp_path / "store")
    state = json.loads(
        (tmp_path / "store" / "script-study" / "state.json").read_text())
    rows = {e["case_id"]: e for e in state["cases"].values()}
    assert rows["a2"]["status"] == "converged"
    assert rows["a7"]["status"] == "failed"
    assert "success_when" in rows["a7"]["error"]
    # outputs still extracted from the failed-but-ran case
    assert rows["a7"]["outputs"] == {"CL": 0.7}


def test_script_loaded_from_file_relative_to_study(tmp_path):
    CALLS.clear()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "base.json").write_text(json.dumps(_STEPS))
    path = _spec(tmp_path, script="scripts/base.json", alphas=(4.0,))
    result = run_study(path, workers=1, store_root=tmp_path / "store")
    assert result["batch"]["succeeded"] == 1
    assert ("analyze", 4.0) in CALLS


def test_generate_writes_script_artifacts_and_validates(tmp_path):
    path = _spec(tmp_path, steps=_STEPS, alphas=(1.0, 2.0))
    result = generate_study(path, store_root=tmp_path / "store")
    assert len(result["generated"]) == 2
    artifact = Path(result["generated"][0]["artifact"])
    assert artifact.name == "script.json"
    steps = json.loads(artifact.read_text())
    assert steps[1]["args"]["alpha"] in (1.0, 2.0)


def test_generate_rejects_unknown_tool(tmp_path):
    bad = [{"id": "an", "tool": "no_such_tool", "args": {"alpha": 0.0}}]
    path = _spec(tmp_path, steps=bad, alphas=(1.0,))
    import pytest

    with pytest.raises(ValueError, match="no_such_tool"):
        generate_study(path, store_root=tmp_path / "store")


def test_run_failed_case_on_unknown_tool_not_study_crash(tmp_path):
    bad = [{"id": "an", "tool": "no_such_tool", "args": {"alpha": 0.0}}]
    path = _spec(tmp_path, steps=bad, alphas=(1.0,))
    result = run_study(path, workers=1, store_root=tmp_path / "store")
    assert result["batch"]["failed"] == 1


def test_outputs_numeric_step_ref_and_missing_path(tmp_path):
    CALLS.clear()
    path = _spec(
        tmp_path, steps=_STEPS, alphas=(1.0,),
        outputs=[
            {"name": "CL", "path": "1:results.CL"},
            {"name": "nope", "path": "an:results.does.not.exist"},
        ],
    )
    run_study(path, workers=1, store_root=tmp_path / "store")
    state = json.loads(
        (tmp_path / "store" / "script-study" / "state.json").read_text())
    entry = next(iter(state["cases"].values()))
    assert entry["outputs"] == {"CL": 0.1, "nope": None}


def test_multistart_presets_patch_steps(tmp_path):
    CALLS.clear()
    study = yaml.safe_load(_spec(tmp_path, steps=_STEPS, alphas=(1.0,))
                           .read_text())
    study["multistart"] = {
        "presets": {
            "low": {"set": {"steps[prep].args.name": "low-start"}},
            "high": {"set": {"steps[prep].args.name": "high-start"}},
        },
        "pick": {"output": "CL", "mode": "min"},
    }
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(study))

    result = run_study(path, workers=1, store_root=tmp_path / "store")
    assert result["batch"]["succeeded"] == 1
    names = [c[1] for c in CALLS if c[0] == "setup"]
    assert sorted(names) == ["high-start", "low-start"]
    # per-preset script artifacts written
    case_dir = tmp_path / "store" / "script-study" / "cases" / "a1"
    assert (case_dir / "script-low.json").exists()
    assert (case_dir / "script-high.json").exists()


def test_entry_points_advertise_all_four_tools():
    from hangar.sdk.study import list_available_runners

    runners = list_available_runners()
    for name in ("oas", "ocp", "pyc", "omd"):
        assert name in runners
