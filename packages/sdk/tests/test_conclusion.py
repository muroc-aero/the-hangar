"""Tests for conclusion artifacts (concluding stage, sdk session sources).

Covers the pure verdict derivation, the persist/round-trip through the
``decisions.metadata_json`` column, idempotent re-conclusion, and the legacy-DB
migration that adds the column.
"""

from __future__ import annotations

import sqlite3
import uuid

from hangar.sdk.provenance.conclusion import derive_conclusion, record_conclusion
from hangar.sdk.provenance.db import (
    get_conclusion,
    init_db,
    record_requirements,
    record_session,
)


def _make_session(prefix="tc") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# derive_conclusion (pure)
# ---------------------------------------------------------------------------


def test_derive_all_satisfied_meets():
    reqs = [
        {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
        {"path": "failure", "operator": "<", "value": 1.0, "label": "no_failure"},
    ]
    out = derive_conclusion(reqs, {"CL": 0.5, "failure": 0.8}, narrative="looks good")
    assert out["verdict"] == "meets"
    assert out["narrative"] == "looks good"
    assert {r["id"]: r["verdict"] for r in out["requirements"]} == {
        "min_CL": "satisfies",
        "no_failure": "satisfies",
    }


def test_derive_one_violation_fails():
    reqs = [
        {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
        {"path": "failure", "operator": "<", "value": 1.0, "label": "no_failure"},
    ]
    out = derive_conclusion(reqs, {"CL": 0.5, "failure": 1.4})
    assert out["verdict"] == "fails"
    verdicts = {r["id"]: r["verdict"] for r in out["requirements"]}
    assert verdicts == {"min_CL": "satisfies", "no_failure": "violates"}


def test_derive_missing_path_is_open_partial():
    reqs = [
        {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
        {"path": "nope", "operator": ">", "value": 1.0, "label": "ghost"},
    ]
    out = derive_conclusion(reqs, {"CL": 0.5})
    # one satisfied, one unevaluable -> partial (no violation)
    assert out["verdict"] == "partial"
    verdicts = {r["id"]: r["verdict"] for r in out["requirements"]}
    assert verdicts == {"min_CL": "satisfies", "ghost": "open"}


def test_derive_no_requirements_is_open():
    out = derive_conclusion([], {"CL": 0.5})
    assert out["verdict"] == "open"
    assert out["requirements"] == []


def test_derive_snapshots_scalar_metrics_only():
    out = derive_conclusion([], {"CL": 0.5, "name": "wing", "_priv": 1, "arr": [1, 2]})
    assert out["metrics"] == {"CL": 0.5}  # strings/private/arrays excluded


# ---------------------------------------------------------------------------
# record_conclusion (persist + round-trip)
# ---------------------------------------------------------------------------


def test_record_and_get_conclusion_round_trip(tmp_path):
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    record_requirements(sid, [
        {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
    ])

    payload = record_conclusion(sid, "run-123", {"CL": 0.5}, narrative="ok")
    assert payload["verdict"] == "meets"
    assert payload["run_id"] == "run-123"
    assert payload["conclusion_id"] == "conclusion-run-123"

    got = get_conclusion(sid)
    assert got is not None
    assert got["verdict"] == "meets"
    assert got["run_id"] == "run-123"
    assert got["conclusion_id"] == "conclusion-run-123"
    assert got["created_at"]  # recorded_at surfaced


def test_record_conclusion_reads_persisted_requirements(tmp_path):
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    record_requirements(sid, [
        {"path": "failure", "operator": "<", "value": 1.0, "label": "no_failure"},
    ])
    # requirements not passed explicitly -> read from the DB
    payload = record_conclusion(sid, "run-x", {"failure": 1.5})
    assert payload["verdict"] == "fails"


def test_record_conclusion_idempotent_overwrites(tmp_path):
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    record_requirements(sid, [{"path": "CL", "operator": ">=", "value": 0.4}])

    record_conclusion(sid, "run-1", {"CL": 0.5})       # meets
    record_conclusion(sid, "run-1", {"CL": 0.1})       # re-conclude same run -> fails

    got = get_conclusion(sid)
    assert got["verdict"] == "fails"
    # only one conclusion row for the session (same decision_id reused)
    import hangar.sdk.provenance.db as _db
    conn = _db._get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE session_id=? AND decision_type='conclusion'",
        (sid,),
    ).fetchone()[0]
    assert n == 1


def test_get_conclusion_none_when_absent(tmp_path):
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    assert get_conclusion(sid) is None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_init_db_migrates_legacy_decisions_table(tmp_path):
    """A decisions table without metadata_json gets the column added."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, notes TEXT, oas_session_id TEXT,
            started_at TEXT, user TEXT DEFAULT '', project TEXT DEFAULT 'default',
            tool TEXT DEFAULT ''
        );
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY, session_id TEXT, seq INTEGER,
            decision_type TEXT, reasoning TEXT, prior_call_id TEXT,
            selected_action TEXT, confidence TEXT, recorded_at TEXT, tool TEXT DEFAULT ''
        );
        """
    )
    conn.commit()
    conn.close()

    init_db(db)  # should ALTER TABLE ... ADD COLUMN metadata_json

    sid = _make_session()
    record_session(sid)
    record_conclusion(sid, "run-1", {"CL": 0.5}, requirements=[
        {"path": "CL", "operator": ">=", "value": 0.4},
    ])
    assert get_conclusion(sid)["verdict"] == "meets"
