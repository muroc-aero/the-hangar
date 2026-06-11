"""End-to-end study tests with the omd runner (paraboloid plans).

Exercises the full path: study.yaml -> case expansion -> generated plan
artifacts (metadata.study stamped) -> run_plan per case -> output
extraction from the analysis DB -> study state/csv -> provenance edges.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

import hangar.omd.study_runner  # noqa: F401  (registers the omd runner)
from hangar.omd.assemble import assemble_plan
from hangar.sdk.study import StudyStore, run_study
from hangar.sdk.study.orchestrate import generate_study

FIXTURES = Path(__file__).parent / "fixtures"


def _paraboloid_f(x: float, y: float) -> float:
    return (x - 3.0) ** 2 + x * y + (y + 4.0) ** 2 - 3.0


@pytest.fixture()
def study_env(tmp_path, monkeypatch):
    """Isolated study root + assembled paraboloid base plan."""
    monkeypatch.setenv("HANGAR_STUDY_DIR", str(tmp_path / "studies"))
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "omd_data"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    result = assemble_plan(FIXTURES / "paraboloid_analysis",
                           output=base_dir / "plan.yaml")
    assert result["errors"] == []
    return tmp_path


def _study_spec(extra_cases: list | None = None, **top) -> dict:
    spec = {
        "metadata": {"id": "paraboloid-grid", "name": "Paraboloid grid",
                     "version": 1},
        "defaults": {"runner": "omd",
                     "spec": {"plan": "base/plan.yaml", "mode": "analysis",
                              "recording_level": "minimal"}},
        "cases": [
            {"matrix": {
                "id_template": "x{x:g}-y{y:g}",
                "axes": {
                    "x": {"values": [0.0, 1.0]},
                    "y": {"values": [0.0, 2.0]},
                },
                "bind": {
                    "x": ["operating_points.x"],
                    "y": ["operating_points.y"],
                },
            }},
        ] + (extra_cases or []),
        "outputs": [{"name": "f_xy", "path": "paraboloid.f_xy"}],
    }
    spec.update(top)
    return spec


def _write_study(tmp_path: Path, spec: dict) -> Path:
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(spec))
    return path


class TestGenerate:
    def test_plan_artifacts_written_and_stamped(self, study_env):
        path = _write_study(study_env, _study_spec())
        result = generate_study(path)
        assert len(result["generated"]) == 4
        plan_path = Path(result["generated"][0]["artifact"])
        plan = yaml.safe_load(plan_path.read_text())
        assert plan["metadata"]["study"] == "paraboloid-grid"
        assert plan["metadata"]["id"].startswith("paraboloid-grid--")
        assert plan["metadata"]["case_id"] == plan["metadata"]["id"].split("--")[1]
        # bind applied into the plan dict
        case_ids = {Path(g["artifact"]).parent.name: g for g in result["generated"]}
        plan_x1 = yaml.safe_load(
            (Path(case_ids["x1-y2"]["artifact"])).read_text())
        assert plan_x1["operating_points"]["x"] == 1.0
        assert plan_x1["operating_points"]["y"] == 2.0

    def test_generate_catches_semantic_errors(self, study_env):
        bad_case = {"case": {
            "id": "bogus-component",
            "spec": {"set": {"components[paraboloid].type": "nope/Missing"}},
        }}
        path = _write_study(study_env, _study_spec(extra_cases=[bad_case]))
        with pytest.raises(ValueError, match="bogus-component"):
            generate_study(path)


class TestRun:
    def test_grid_runs_and_extracts_outputs(self, study_env):
        path = _write_study(study_env, _study_spec())
        result = run_study(path, confirm=True, workers=1)
        assert result["batch"]["ran"] == 4
        assert result["batch"]["succeeded"] == 4

        state = StudyStore("paraboloid-grid").load_state()
        for entry in state["cases"].values():
            x, y = entry["params"]["x"], entry["params"]["y"]
            assert entry["status"] == "completed"
            assert entry["run_ref"]
            assert entry["outputs"]["f_xy"] == pytest.approx(
                _paraboloid_f(x, y), rel=1e-10)

        with open(result["cases_csv"]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 4
        assert {"case_id", "x", "y", "status", "run_ref", "f_xy"} <= set(rows[0])

    def test_resume_skips_completed(self, study_env):
        path = _write_study(study_env, _study_spec())
        first = run_study(path, max_cases=2, workers=1)
        assert first["batch"]["ran"] == 2
        assert first["remaining"] == 2
        rest = run_study(path, confirm=True, workers=1)
        assert rest["batch"]["ran"] == 2
        assert rest["remaining"] == 0

    def test_manual_case_insertion(self, study_env):
        manual = {"case": {
            "id": "far-corner",
            "params": {"x": 10.0, "y": -10.0},
            "spec": {"set": {"operating_points.x": 10.0,
                             "operating_points.y": -10.0}},
        }}
        path = _write_study(study_env, _study_spec(extra_cases=[manual]))
        run_study(path, confirm=True, workers=1)
        state = StudyStore("paraboloid-grid").load_state()
        entry = next(e for e in state["cases"].values()
                     if e["case_id"] == "far-corner")
        assert entry["source"] == "manual"
        assert entry["outputs"]["f_xy"] == pytest.approx(
            _paraboloid_f(10.0, -10.0), rel=1e-10)

    def test_study_provenance_recorded(self, study_env):
        path = _write_study(study_env, _study_spec())
        run_study(path, confirm=True, workers=1)

        from hangar.omd.db import init_analysis_db, query_entity, _get_conn

        init_analysis_db()
        study_entity = query_entity("study-paraboloid-grid/v1")
        assert study_entity is not None
        assert study_entity["entity_type"] == "study"
        assert json.loads(study_entity["metadata"])["study_id"] == "paraboloid-grid"

        conn = _get_conn()
        edges = conn.execute(
            "SELECT subject_id FROM prov_edges WHERE relation='partOf' "
            "AND object_id='study-paraboloid-grid/v1'").fetchall()
        run_refs = {e["run_ref"] for e in
                    StudyStore("paraboloid-grid").load_state()["cases"].values()}
        assert {row[0] for row in edges} == run_refs

    def test_case_plan_lands_in_plan_store(self, study_env):
        path = _write_study(study_env, _study_spec())
        run_study(path, max_cases=1, workers=1)

        from hangar.omd.db import plan_store_dir

        stored = list(plan_store_dir().glob("paraboloid-grid--*/v1.yaml"))
        assert len(stored) == 1
        plan = yaml.safe_load(stored[0].read_text())
        assert plan["metadata"]["study"] == "paraboloid-grid"

    def test_missing_base_plan_fails_case_not_study(self, study_env):
        broken = {"case": {"id": "broken",
                           "spec": {"plan": "nowhere/plan.yaml"}}}
        path = _write_study(study_env, _study_spec(extra_cases=[broken]))
        result = run_study(path, confirm=True, workers=1)
        assert result["batch"]["failed"] == 1
        assert result["batch"]["succeeded"] == 4
        state = StudyStore("paraboloid-grid").load_state()
        entry = next(e for e in state["cases"].values()
                     if e["case_id"] == "broken")
        assert entry["status"] == "error"
        assert "not found" in entry["error"]

    @pytest.mark.slow
    def test_parallel_workers(self, study_env):
        path = _write_study(study_env, _study_spec())
        result = run_study(path, confirm=True, workers=2)
        assert result["batch"]["succeeded"] == 4
