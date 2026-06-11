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
