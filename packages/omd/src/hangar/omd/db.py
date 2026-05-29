"""SQLite analysis database for provenance and run case storage.

Implements the PROV-Agent model with entities, activities, provenance
edges, and run case data. Follows the connection management pattern
from hangar.sdk.provenance.db.

The read-only layer (connection management, schema, the soft catalog of
entity types / provenance relations, and the query_* functions) lives in
``hangar.results_reader.db`` so it can be consumed without OpenMDAO as a
transitive dependency. This module re-exports that layer for back-compat
and adds the write-side operations on top of the shared connection state.
The module-level ``_db_path`` is owned by ``hangar.results_reader.db``;
the writers below reach the same connection through the re-exported
``_get_conn``, so there is a single source of truth for DB state.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

# Read seam: connection management, schema, soft catalog, query_* funcs.
# Re-exported here so existing imports (``from hangar.omd.db import ...``)
# keep working unchanged.
from hangar.results_reader.db import (  # noqa: F401
    _DDL,
    KNOWN_ENTITY_TYPES,
    KNOWN_PROV_RELATIONS,
    _get_conn,
    _now,
    get_db_path,
    init_analysis_db,
    query_entity,
    query_provenance_dag,
    query_run_results,
)

logger = logging.getLogger(__name__)


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
    parent_id: str | None = None,
) -> None:
    """Record a versioned artifact entity.

    Args:
        entity_id: Unique entity identifier (e.g., "plan-ttbw/v2").
        entity_type: One of: plan, run_record, assessment, surface_def,
            operating_point, solver_config, opt_setup, decision,
            aero_results, struct_results, convergence_info, model_structure.
        created_by: Agent that created it (e.g., "omd", "have-agent").
        plan_id: Parent plan identifier (None for top-level).
        version: Version number.
        content_hash: SHA256 of content.
        storage_ref: Filesystem path or reference.
        metadata: Optional JSON string with extra metadata.
        parent_id: Containing entity ID for sub-entities (enables
            compound node grouping in the provenance DAG).
    """
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO entities "
        "(entity_id, entity_type, created_at, created_by, plan_id, version, "
        "content_hash, storage_ref, metadata, parent_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entity_id, entity_type, _now(), created_by, plan_id, version,
         content_hash, storage_ref, metadata, parent_id),
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
            wasAssociatedWith, wasAttributedTo, wasInformedBy, justifies,
            has_criterion, verifies, satisfies, violates, precedes,
            has_check, executes).
        subject_id: Source entity or activity ID.
        object_id: Target entity or activity ID.
    """
    if relation not in KNOWN_PROV_RELATIONS:
        logger.warning(
            "add_prov_edge: unknown relation %r (subject=%s, object=%s). "
            "Add it to KNOWN_PROV_RELATIONS if intentional.",
            relation, subject_id, object_id,
        )
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO prov_edges (relation, subject_id, object_id, timestamp) "
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
