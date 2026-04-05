"""SQLite analysis database for provenance and run case storage.

Implements the PROV-Agent model with entities, activities, provenance
edges, and run case data. Follows the connection management pattern
from hangar.sdk.provenance.db.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_db_path: Path | None = None
_local = threading.local()

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """\
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    plan_id TEXT,
    version INTEGER,
    content_hash TEXT,
    storage_ref TEXT
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    activity_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    agent TEXT NOT NULL,
    status TEXT
);

CREATE TABLE IF NOT EXISTS prov_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    relation TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_cases (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    iteration INTEGER,
    case_type TEXT,
    timestamp TEXT,
    data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_plan ON entities(plan_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_prov_subject ON prov_edges(subject_id);
CREATE INDEX IF NOT EXISTS idx_prov_object ON prov_edges(object_id);
CREATE INDEX IF NOT EXISTS idx_run_cases_run ON run_cases(run_id);
"""


# ---------------------------------------------------------------------------
# JSON encoder (handles numpy types)
# ---------------------------------------------------------------------------


class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.ndarray):
            return _sanitize(obj.tolist())
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            val = float(obj)
            if math.isinf(val) or math.isnan(val):
                return None
            return val
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def _sanitize(obj: Any) -> Any:
    """Replace inf/nan with None, recursing into containers."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, cls=_NumpyEncoder)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local connection."""
    if _db_path is None:
        raise RuntimeError("Analysis DB not initialized. Call init_analysis_db() first.")
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(_db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Data directory helpers
# ---------------------------------------------------------------------------


def omd_data_root() -> Path:
    """Return the root directory for all omd runtime data.

    Reads OMD_DATA_ROOT env var, or defaults to hangar_data/omd/.
    """
    return Path(os.environ.get("OMD_DATA_ROOT", "hangar_data/omd"))


def plan_store_dir() -> Path:
    """Return the plan store directory.

    Reads OMD_PLAN_STORE env var, or defaults to {omd_data_root}/plans/.
    """
    env = os.environ.get("OMD_PLAN_STORE")
    if env:
        return Path(env)
    return omd_data_root() / "plans"


def recordings_dir() -> Path:
    """Return the recordings directory for OpenMDAO recorder files.

    Reads OMD_RECORDINGS_DIR env var, or defaults to {omd_data_root}/recordings/.
    """
    env = os.environ.get("OMD_RECORDINGS_DIR")
    if env:
        return Path(env)
    return omd_data_root() / "recordings"


def n2_dir() -> Path:
    """Return the directory for N2 diagram HTML files.

    Defaults to {omd_data_root}/n2/.
    """
    return omd_data_root() / "n2"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def init_analysis_db(db_path: Path | None = None) -> None:
    """Initialize the analysis database.

    Creates the database file and tables if they don't exist.

    Args:
        db_path: Path to the SQLite database file. If None, uses
            OMD_DB_PATH env var or defaults to data/analysis_db/analysis.db.
    """
    global _db_path, _local
    _local = threading.local()

    if db_path is not None:
        _db_path = Path(db_path)
    else:
        env_path = os.environ.get("OMD_DB_PATH")
        if env_path:
            _db_path = Path(env_path)
        else:
            _db_path = Path("hangar_data/omd/analysis.db")

    _db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    conn.executescript(_DDL)
    # Migrate: add metadata column if missing (SQLite lacks IF NOT EXISTS for ALTER)
    try:
        conn.execute("ALTER TABLE entities ADD COLUMN metadata TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    logger.debug("Analysis DB initialized at %s", _db_path)


def get_db_path() -> Path | None:
    """Return the current database path, or None if not initialized."""
    return _db_path


# ---------------------------------------------------------------------------
# Entity operations
# ---------------------------------------------------------------------------


def record_entity(
    entity_id: str,
    entity_type: str,
    created_by: str,
    plan_id: str | None = None,
    version: int | None = None,
    content_hash: str | None = None,
    storage_ref: str | None = None,
    metadata: str | None = None,
) -> None:
    """Record a versioned artifact entity.

    Args:
        entity_id: Unique entity identifier (e.g., "plan-ttbw/v2").
        entity_type: One of: plan, run_record, assessment, validation_report.
        created_by: Agent that created it (e.g., "omd", "have-agent").
        plan_id: Parent plan identifier (None for top-level).
        version: Version number.
        content_hash: SHA256 of content.
        storage_ref: Filesystem path or reference.
        metadata: Optional JSON string with extra metadata (e.g.,
            component_type for run records).
    """
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO entities "
        "(entity_id, entity_type, created_at, created_by, plan_id, version, "
        "content_hash, storage_ref, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entity_id, entity_type, _now(), created_by, plan_id, version,
         content_hash, storage_ref, metadata),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Activity operations
# ---------------------------------------------------------------------------


def record_activity(
    activity_id: str,
    activity_type: str,
    agent: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    status: str = "completed",
) -> None:
    """Record a transformation activity.

    Args:
        activity_id: Unique activity identifier.
        activity_type: One of: draft, revise, validate, execute, assess, replan.
        agent: Who performed it (e.g., "omd", "range-safety", "have-agent").
        started_at: ISO timestamp (defaults to now).
        completed_at: ISO timestamp (defaults to now).
        status: "completed" or "failed".
    """
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO activities "
        "(activity_id, activity_type, started_at, completed_at, agent, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (activity_id, activity_type, started_at or _now(),
         completed_at or _now(), agent, status),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Provenance edge operations
# ---------------------------------------------------------------------------


def add_prov_edge(
    relation: str,
    subject_id: str,
    object_id: str,
) -> None:
    """Add a provenance edge.

    Args:
        relation: PROV relation type (wasGeneratedBy, used, wasDerivedFrom,
            wasAssociatedWith, wasAttributedTo).
        subject_id: Source entity or activity ID.
        object_id: Target entity or activity ID.
    """
    conn = _get_conn()
    conn.execute(
        "INSERT INTO prov_edges (relation, subject_id, object_id, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (relation, subject_id, object_id, _now()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Run case operations
# ---------------------------------------------------------------------------


def record_run_case(
    run_id: str,
    iteration: int,
    case_type: str,
    data: dict,
) -> None:
    """Record a single iteration's data from an OpenMDAO run.

    Args:
        run_id: Run entity ID.
        iteration: Iteration number.
        case_type: "driver", "solver", or "final".
        data: Variable name -> value mapping.
    """
    conn = _get_conn()
    conn.execute(
        "INSERT INTO run_cases (run_id, iteration, case_type, timestamp, data) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, iteration, case_type, _now(), _json_dumps(data)),
    )
    conn.commit()


def record_run_cases_batch(
    run_id: str,
    cases: list[dict],
) -> None:
    """Record multiple run cases in a single transaction.

    Args:
        run_id: Run entity ID.
        cases: List of dicts with keys: iteration, case_type, data.
    """
    conn = _get_conn()
    now = _now()
    conn.executemany(
        "INSERT INTO run_cases (run_id, iteration, case_type, timestamp, data) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (run_id, c["iteration"], c["case_type"], now, _json_dumps(c["data"]))
            for c in cases
        ],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------


def query_run_results(
    run_id: str,
    variables: list[str] | None = None,
) -> list[dict]:
    """Query run case data for a given run.

    Args:
        run_id: Run entity ID.
        variables: Optional list of variable names to filter.
            If None, returns all data.

    Returns:
        List of case dicts with iteration, case_type, and data fields.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT iteration, case_type, timestamp, data FROM run_cases "
        "WHERE run_id = ? ORDER BY iteration",
        (run_id,),
    ).fetchall()

    results = []
    for row in rows:
        data = json.loads(row["data"])
        if variables:
            data = {k: v for k, v in data.items() if k in variables}
        results.append({
            "iteration": row["iteration"],
            "case_type": row["case_type"],
            "timestamp": row["timestamp"],
            "data": data,
        })
    return results


def query_provenance_dag(plan_id: str) -> dict:
    """Extract the full provenance subgraph for a plan.

    Args:
        plan_id: Plan identifier to query.

    Returns:
        Dict with keys: entities (list), activities (list), edges (list).
    """
    conn = _get_conn()

    # Get all entities for this plan
    entity_rows = conn.execute(
        "SELECT * FROM entities WHERE plan_id = ? OR entity_id = ?",
        (plan_id, plan_id),
    ).fetchall()
    entities = [dict(r) for r in entity_rows]
    entity_ids = {e["entity_id"] for e in entities}

    # Get all edges involving these entities
    if entity_ids:
        placeholders = ",".join("?" * len(entity_ids))
        edge_rows = conn.execute(
            f"SELECT * FROM prov_edges WHERE subject_id IN ({placeholders}) "
            f"OR object_id IN ({placeholders})",
            list(entity_ids) + list(entity_ids),
        ).fetchall()
    else:
        edge_rows = []
    edges = [dict(r) for r in edge_rows]

    # Collect activity IDs referenced in edges
    activity_ids = set()
    for edge in edges:
        activity_ids.add(edge["subject_id"])
        activity_ids.add(edge["object_id"])
    activity_ids -= entity_ids

    # Get activities
    if activity_ids:
        placeholders = ",".join("?" * len(activity_ids))
        activity_rows = conn.execute(
            f"SELECT * FROM activities WHERE activity_id IN ({placeholders})",
            list(activity_ids),
        ).fetchall()
    else:
        activity_rows = []
    activities = [dict(r) for r in activity_rows]

    return {
        "entities": entities,
        "activities": activities,
        "edges": edges,
    }


def query_entity(entity_id: str) -> dict | None:
    """Get a single entity by ID.

    Returns:
        Entity dict or None if not found.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
    ).fetchone()
    return dict(row) if row else None
