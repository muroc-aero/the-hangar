"""Tests for the results-reader read seam."""

from __future__ import annotations

import pytest

from hangar.results_reader import init_analysis_db, query_entity_index
from hangar.results_reader.db import _get_conn


@pytest.fixture()
def seeded_db(tmp_path):
    """A fresh analysis DB with entities for two plans plus one unattached."""
    init_analysis_db(tmp_path / "analysis.db")
    conn = _get_conn()
    rows = [
        ("plan-a/v1", "plan", "2026-06-01T00:00:00+00:00", "test", "plan-a", 1),
        ("run-1", "run_record", "2026-06-02T00:00:00+00:00", "test", "plan-a", None),
        ("plan-b/v1", "plan", "2026-06-03T00:00:00+00:00", "test", "plan-b", 1),
        ("loose", "decision", "2026-06-04T00:00:00+00:00", "test", None, None),
    ]
    conn.executemany(
        "INSERT INTO entities "
        "(entity_id, entity_type, created_at, created_by, plan_id, version) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def test_index_returns_plan_attached_entities_only(seeded_db):
    index = query_entity_index()
    assert len(index) == 3
    assert {r["plan_id"] for r in index} == {"plan-a", "plan-b"}
    assert all(
        set(r) == {"plan_id", "entity_type", "version", "created_at"}
        for r in index
    )


def test_index_filters_by_plan(seeded_db):
    index = query_entity_index(plan_id="plan-a")
    assert {r["entity_type"] for r in index} == {"plan", "run_record"}


def test_index_reexported_from_omd_db(seeded_db):
    """The back-compat re-export in hangar.omd.db reaches the same seam."""
    pytest.importorskip("openmdao")
    from hangar.omd.db import query_entity_index as omd_index

    assert len(omd_index()) == 3


@pytest.fixture()
def run_db(tmp_path):
    """A fresh analysis DB with one run's cases and a small provenance DAG."""
    init_analysis_db(tmp_path / "analysis.db")
    conn = _get_conn()
    cases = [
        ("run-1", 0, "driver", '{"wing.twist_cp": [1.0, 2.0], '
         '"total_perf.CL_CD.CL": 0.6, "total_perf.CL_CD.CD": 0.03, '
         '"total_perf.fuelburn.fuelburn": 900.0}'),
        ("run-1", 1, "final", '{"wing.twist_cp": [1.5, 2.5], '
         '"total_perf.CL_CD.CL": 0.5, "total_perf.CL_CD.CD": 0.02, '
         '"total_perf.fuelburn.fuelburn": 800.0}'),
    ]
    conn.executemany(
        "INSERT INTO run_cases (run_id, iteration, case_type, timestamp, data) "
        "VALUES (?, ?, ?, '2026-06-01T00:00:00+00:00', ?)",
        cases,
    )
    conn.executemany(
        "INSERT INTO entities "
        "(entity_id, entity_type, created_at, created_by, plan_id) "
        "VALUES (?, ?, '2026-06-01T00:00:00+00:00', 'test', ?)",
        [("plan-a/v1", "plan", "plan-a"), ("run-1", "run_record", "plan-a")],
    )
    conn.execute(
        "INSERT INTO prov_edges (relation, subject_id, object_id, timestamp) "
        "VALUES ('wasGeneratedBy', 'run-1', 'plan-a/v1', "
        "'2026-06-01T00:00:00+00:00')"
    )
    conn.commit()


def test_query_run_results_orders_and_filters(run_db):
    from hangar.results_reader import query_run_results

    cases = query_run_results("run-1")
    assert [c["iteration"] for c in cases] == [0, 1]
    assert cases[1]["case_type"] == "final"

    filtered = query_run_results("run-1", variables=["wing.twist_cp"])
    assert set(filtered[0]["data"]) == {"wing.twist_cp"}


def test_resolve_scalar_matching_modes(run_db):
    from hangar.results_reader import query_run_results, resolve_scalar

    data = query_run_results("run-1")[-1]["data"]
    # Exact, suffix, and bare-label matching; arrays reduce to magnitude-max.
    assert resolve_scalar(data, "total_perf.CL_CD.CL") == pytest.approx(0.5)
    assert resolve_scalar(data, "fuelburn") == pytest.approx(800.0)
    assert resolve_scalar(data, "wing.twist_cp") == pytest.approx(2.5)
    assert resolve_scalar(data, "no.such.var") is None


def test_project_headline_objective_metrics_and_lod(run_db):
    from hangar.results_reader import project_headline

    plan = {"objective": {"name": "fuelburn", "units": "kg"}}
    headline = project_headline("run-1", plan=plan)
    by_label = {m["label"]: m for m in headline}

    # Objective first (from the final case), then curated metrics.
    assert headline[0]["role"] == "objective"
    assert headline[0]["value"] == pytest.approx(800.0)
    assert by_label["CL"]["value"] == pytest.approx(0.5)
    # Derived L_over_D matches the sdk envelope convention.
    assert by_label["L_over_D"]["value"] == pytest.approx(25.0)

    assert project_headline("no-such-run") == []


def test_query_provenance_dag_collects_plan_subgraph(run_db):
    from hangar.results_reader import query_provenance_dag

    dag = query_provenance_dag("plan-a")
    ids = {e["entity_id"] for e in dag["entities"]}
    assert ids == {"plan-a/v1", "run-1"}
    assert len(dag["edges"]) == 1
    assert dag["edges"][0]["relation"] == "wasGeneratedBy"


def test_get_conn_requires_init(tmp_path, monkeypatch):
    import hangar.results_reader.db as rdb

    monkeypatch.setattr(rdb, "_db_path", None)
    with pytest.raises(RuntimeError, match="init_analysis_db"):
        rdb._get_conn()


def test_get_db_path_reflects_init(tmp_path):
    from hangar.results_reader import get_db_path

    init_analysis_db(tmp_path / "x.db")
    assert get_db_path() == tmp_path / "x.db"
