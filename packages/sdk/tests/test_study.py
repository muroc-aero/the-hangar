"""Tests for the tool-independent study core (hangar.sdk.study)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from hangar.sdk.study import (
    StudyGuardError,
    StudyStore,
    expand_cases,
    load_study,
    register_runner,
    review_study,
    run_study,
    set_by_path,
    validate_study,
)
from hangar.sdk.study.expand import ExpansionError
from hangar.sdk.study.orchestrate import generate_study


def _base_spec(**overrides) -> dict:
    spec = {
        "metadata": {"id": "demo-study", "name": "Demo", "version": 1},
        "defaults": {"runner": "fake", "spec": {"mode": "analysis"}},
        "cases": [
            {"matrix": {
                "axes": {
                    "a": {"values": [1, 2]},
                    "b": {"linspace": [0.0, 1.0, 3]},
                },
                "bind": {
                    "a": ["config.a"],
                    "b": ["config.b"],
                },
            }},
            {"case": {
                "id": "manual-1",
                "params": {"a": 99},
                "spec": {"plan": "special.yaml"},
            }},
        ],
        "outputs": [{"name": "metric", "path": "m"}],
    }
    spec.update(overrides)
    return spec


def _write_spec(tmp_path: Path, spec: dict) -> Path:
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_valid_spec(self):
        assert validate_study(_base_spec()) == []

    def test_missing_metadata_and_cases(self):
        errors = validate_study({})
        paths = {e["path"] for e in errors}
        assert "metadata" in paths
        assert "cases" in paths

    def test_unbound_axis_rejected(self):
        spec = _base_spec()
        del spec["cases"][0]["matrix"]["bind"]["b"]
        errors = validate_study(spec)
        assert any("no bind paths" in e["message"] for e in errors)

    def test_bad_linspace(self):
        spec = _base_spec()
        spec["cases"][0]["matrix"]["axes"]["b"] = {"linspace": [0.0, 1.0]}
        assert validate_study(spec)

    def test_unknown_top_key(self):
        spec = _base_spec()
        spec["bogus"] = 1
        assert any(e["path"] == "bogus" for e in validate_study(spec))

    def test_multistart_needs_pick(self):
        spec = _base_spec(multistart={"presets": {"low": {}}})
        assert any(e["path"] == "multistart.pick" for e in validate_study(spec))

    def test_load_study_roundtrip(self, tmp_path):
        path = _write_spec(tmp_path, _base_spec())
        spec, errors = load_study(path)
        assert errors == []
        assert spec["metadata"]["id"] == "demo-study"


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


class TestExpansion:
    def test_matrix_plus_manual_counts(self):
        cases = expand_cases(_base_spec())
        assert len(cases) == 2 * 3 + 1
        assert sum(1 for c in cases if c.source == "manual") == 1

    def test_bind_lands_in_spec_set(self):
        cases = expand_cases(_base_spec())
        matrix = [c for c in cases if c.source == "matrix"]
        first = matrix[0]
        assert first.spec["set"]["config.a"] == first.params["a"]
        assert first.spec["set"]["config.b"] == first.params["b"]
        assert first.spec["mode"] == "analysis"  # defaults merged

    def test_case_key_deterministic_and_param_sensitive(self):
        keys1 = [c.case_key for c in expand_cases(_base_spec())]
        keys2 = [c.case_key for c in expand_cases(_base_spec())]
        assert keys1 == keys2
        spec = _base_spec()
        spec["cases"][0]["matrix"]["axes"]["a"]["values"] = [1, 3]
        keys3 = {c.case_key for c in expand_cases(spec)}
        assert keys3 != set(keys1)

    def test_id_template(self):
        spec = _base_spec()
        spec["cases"][0]["matrix"]["id_template"] = "a{a}-b{b:.1f}"
        cases = expand_cases(spec)
        assert any(c.case_id == "a1-b0.5" for c in cases)

    def test_guard_max_cases(self):
        spec = _base_spec(execution={"guard_max_cases": 3})
        with pytest.raises(ExpansionError, match="guard_max_cases"):
            expand_cases(spec)

    def test_duplicate_manual_id_rejected(self):
        spec = _base_spec()
        spec["cases"].append({"case": {"id": "manual-1", "spec": {"plan": "x"}}})
        with pytest.raises(ExpansionError, match="duplicate case_id"):
            expand_cases(spec)

    def test_identical_cases_rejected(self):
        spec = _base_spec()
        spec["cases"].append({"case": {"id": "manual-2",
                                       "params": {"a": 99},
                                       "spec": {"plan": "special.yaml"}}})
        with pytest.raises(ExpansionError, match="identical"):
            expand_cases(spec)


class TestSetByPath:
    def test_nested_dict_create(self):
        obj: dict = {}
        set_by_path(obj, "a.b.c", 5)
        assert obj == {"a": {"b": {"c": 5}}}

    def test_list_selector_by_id(self):
        obj = {"components": [{"id": "wing", "config": {}},
                              {"id": "tail", "config": {}}]}
        set_by_path(obj, "components[tail].config.span", 3.0)
        assert obj["components"][1]["config"]["span"] == 3.0

    def test_list_selector_by_name(self):
        obj = {"design_variables": [{"name": "x", "lower": 0}]}
        set_by_path(obj, "design_variables[x].initial", 1.5)
        assert obj["design_variables"][0]["initial"] == 1.5

    def test_missing_selector_raises(self):
        obj = {"components": [{"id": "wing"}]}
        with pytest.raises(ExpansionError, match="no element"):
            set_by_path(obj, "components[fuselage].config.x", 1)


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class TestReview:
    def test_counts_and_estimate(self):
        spec = _base_spec(execution={"workers": 2, "est_case_seconds": 60})
        cases = expand_cases(spec)
        rev = review_study(spec, cases)
        assert rev["n_cases"] == 7
        assert rev["n_pending"] == 7
        assert rev["est_wall_seconds"] == pytest.approx(7 * 60 / 2)
        assert rev["matrix_axes"] == [{"a": 2, "b": 3}]

    def test_threshold_warning(self):
        spec = _base_spec(execution={"review_threshold": 3})
        cases = expand_cases(spec)
        rev = review_study(spec, cases)
        assert any("review_threshold" in w for w in rev["warnings"])

    def test_observed_mean_overrides_seed(self):
        spec = _base_spec(execution={"est_case_seconds": 60})
        cases = expand_cases(spec)
        state = {"cases": {
            cases[0].case_key: {"status": "completed", "wall_time_s": 10.0},
            cases[1].case_key: {"status": "completed", "wall_time_s": 20.0},
        }}
        rev = review_study(spec, cases, state=state)
        assert rev["n_pending"] == 5
        assert rev["est_case_seconds"] == pytest.approx(15.0)
        assert "observed" in rev["est_source"]

    def test_multistart_multiplies_runs(self):
        spec = _base_spec(multistart={
            "presets": {"low": {}, "high": {}},
            "pick": {"output": "metric"},
        })
        cases = expand_cases(spec)
        rev = review_study(spec, cases)
        assert rev["n_runs_pending"] == 14


# ---------------------------------------------------------------------------
# Orchestration (fake runner, workers=1)
# ---------------------------------------------------------------------------


def _fake_runner(spec: dict, ctx: dict) -> dict:
    """Computes m = a + 10*b from bound set paths; fails when a == 2."""
    sets = spec.get("set") or {}
    a = sets.get("config.a", ctx["params"].get("a", 0))
    b = sets.get("config.b", 0.0)
    preset = ctx.get("preset") or {}
    bias = preset.get("bias", 0.0)
    if spec.get("fail_when_a") == a:
        return {"status": "failed", "run_ref": None, "outputs": {},
                "error": "synthetic failure"}
    return {
        "status": "completed",
        "run_ref": f"run-{ctx['case_id']}" + (f"-{ctx.get('preset_name')}" if preset else ""),
        "outputs": {"metric": a + 10 * b + bias},
        "error": None,
    }


register_runner("fake", _fake_runner)


@pytest.fixture()
def study_root(tmp_path, monkeypatch):
    root = tmp_path / "studies"
    monkeypatch.setenv("HANGAR_STUDY_DIR", str(root))
    return root


class TestRunStudy:
    def test_full_run_and_resume(self, tmp_path, study_root):
        path = _write_spec(tmp_path, _base_spec())
        result = run_study(path, confirm=True, workers=1, store_root=study_root)
        assert result["batch"]["ran"] == 7
        assert result["batch"]["succeeded"] == 7
        assert result["remaining"] == 0

        again = run_study(path, confirm=True, workers=1, store_root=study_root)
        assert again["batch"]["ran"] == 0

    def test_outputs_in_state_and_csv(self, tmp_path, study_root):
        path = _write_spec(tmp_path, _base_spec())
        result = run_study(path, confirm=True, workers=1, store_root=study_root)
        store = StudyStore("demo-study", root=study_root)
        state = store.load_state()
        vals = {e["case_id"]: e["outputs"].get("metric")
                for e in state["cases"].values() if e["source"] == "matrix"}
        assert vals["a=1-b=0"] == pytest.approx(1.0)
        assert vals["a=2-b=1"] == pytest.approx(12.0)

        with open(result["cases_csv"]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 7
        assert {"case_id", "a", "b", "status", "metric"} <= set(rows[0])

    def test_max_cases_pilot_batch(self, tmp_path, study_root):
        path = _write_spec(tmp_path, _base_spec())
        result = run_study(path, max_cases=2, workers=1, store_root=study_root)
        assert result["batch"]["ran"] == 2
        assert result["remaining"] == 5
        summary = StudyStore("demo-study", root=study_root).status_summary()
        assert summary["done"] == 2

    def test_guard_requires_confirmation(self, tmp_path, study_root):
        spec = _base_spec(execution={"review_threshold": 3})
        path = _write_spec(tmp_path, spec)
        with pytest.raises(StudyGuardError) as excinfo:
            run_study(path, workers=1, store_root=study_root)
        assert excinfo.value.review["n_pending"] == 7
        # max_cases batches bypass the guard
        result = run_study(path, max_cases=1, workers=1, store_root=study_root)
        assert result["batch"]["ran"] == 1

    def test_failed_cases_not_rerun_without_flag(self, tmp_path, study_root):
        spec = _base_spec()
        spec["defaults"]["spec"]["fail_when_a"] = 2
        path = _write_spec(tmp_path, spec)
        result = run_study(path, confirm=True, workers=1, store_root=study_root)
        assert result["batch"]["failed"] == 3  # a=2 cells fail

        again = run_study(path, confirm=True, workers=1, store_root=study_root)
        assert again["batch"]["ran"] == 0

        retry = run_study(path, confirm=True, workers=1, store_root=study_root,
                          retry_failed=True)
        assert retry["batch"]["ran"] == 3

    def test_multistart_picks_best(self, tmp_path, study_root):
        spec = _base_spec(multistart={
            "presets": {"low": {"bias": -5.0}, "high": {"bias": 5.0}},
            "pick": {"output": "metric", "mode": "min"},
        })
        path = _write_spec(tmp_path, spec)
        run_study(path, confirm=True, workers=1, store_root=study_root)
        state = StudyStore("demo-study", root=study_root).load_state()
        entry = next(e for e in state["cases"].values()
                     if e["case_id"] == "a=1-b=0")
        assert entry["outputs"]["metric"] == pytest.approx(-4.0)  # low preset
        assert entry["run_ref"].endswith("-low")
        assert len(entry["attempts"]) == 2

    def test_spec_edit_reruns_only_changed_cases(self, tmp_path, study_root):
        path = _write_spec(tmp_path, _base_spec())
        run_study(path, confirm=True, workers=1, store_root=study_root)

        spec = _base_spec()
        spec["cases"][0]["matrix"]["axes"]["a"]["values"] = [1, 5]  # a=2 -> a=5
        path = _write_spec(tmp_path, spec)
        result = run_study(path, confirm=True, workers=1, store_root=study_root)
        assert result["batch"]["ran"] == 3  # only the new a=5 cells

        state = StudyStore("demo-study", root=study_root).load_state()
        stale = [e for e in state["cases"].values() if not e["in_spec"]]
        assert len(stale) == 3  # old a=2 cells kept, flagged out of spec


class TestGenerateStudy:
    def test_runner_without_generate_hook_is_skipped(self, tmp_path, study_root):
        path = _write_spec(tmp_path, _base_spec())
        result = generate_study(path, store_root=study_root)
        assert result["generated"] == []
        assert len(result["skipped"]) == 7
