"""Read-only access to the hangar analysis/provenance database.

This module is the read seam over the SQLite analysis DB that
``hangar.omd`` writes. It owns connection management, the schema (DDL),
the soft catalog of entity types and provenance relations, and the
read-only query functions. It is deliberately dependency-free (pure
stdlib) so consumers can read results and provenance without pulling in
OpenMDAO.

``hangar.omd.db`` re-exports everything here for back-compat and adds the
write-side operations (record_* / add_prov_edge) on top of the shared
connection state. The module-level ``_db_path`` lives here and is the
single source of truth: ``init_analysis_db`` sets it, ``_get_conn`` reads
it, and the omd writers reach the same connection through the re-exported
``_get_conn``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module state (single source of truth for the analysis DB connection)
# ---------------------------------------------------------------------------

_db_path: Path | None = None
_local = threading.local()

# ---------------------------------------------------------------------------
# Known entity types and prov_edge relations (soft catalog)
# ---------------------------------------------------------------------------
# The DB schema stores both fields as free-form TEXT, but we keep an
# authoritative list here so:
#   - Readers can map entity_type to badge styles in the Cytoscape view.
#   - add_prov_edge() can log a warning when an unknown relation is used,
#     surfacing typos without breaking existing callers.

KNOWN_ENTITY_TYPES: frozenset[str] = frozenset({
    "plan",
    "run_record",
    "assessment",
    "surface_def",
    "operating_point",
    "solver_config",
    "opt_setup",
    "decision",
    "aero_results",
    "struct_results",
    "convergence_info",
    "model_structure",
    # New in plan-authoring enhancements:
    "phase",
    "acceptance_criterion",
    "requirement",
    "plan_element",
    # Agent-recorded conclusion artifact (concluding stage): ties the chosen
    # run to the requirements it resolves (satisfies / violates edges).
    "conclusion",
})

KNOWN_PROV_RELATIONS: frozenset[str] = frozenset({
    # PROV-Agent core relations (used throughout omd today).
    "wasGeneratedBy",
    "used",
    "wasDerivedFrom",
    "wasAssociatedWith",
    "wasAttributedTo",
    "wasInformedBy",
    # New in plan-authoring enhancements:
    "justifies",
    "has_criterion",
    "verifies",
    "satisfies",
    "violates",
    "precedes",
    "has_check",
    "executes",
})

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
# Initialization
# ---------------------------------------------------------------------------


def init_analysis_db(db_path: Path | None = None) -> None:
    """Initialize the analysis database.

    Creates the database file and tables if they don't exist.

    Args:
        db_path: Path to the SQLite database file. If None, uses
            OMD_DB_PATH env var or defaults to hangar_data/omd/analysis.db.
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
    try:
        conn.execute("ALTER TABLE entities ADD COLUMN parent_id TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    # Migrate: add unique index on prov_edges to prevent duplicate edges.
    # First deduplicate existing rows (keep the earliest edge_id per triple).
    try:
        conn.execute(
            "CREATE UNIQUE INDEX idx_prov_edges_unique "
            "ON prov_edges(relation, subject_id, object_id)"
        )
    except (sqlite3.OperationalError, sqlite3.IntegrityError):
        # Index already exists, or duplicates prevent creation -- clean up.
        conn.execute(
            "DELETE FROM prov_edges WHERE edge_id NOT IN ("
            "  SELECT MIN(edge_id) FROM prov_edges"
            "  GROUP BY relation, subject_id, object_id"
            ")"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_prov_edges_unique "
            "ON prov_edges(relation, subject_id, object_id)"
        )
    conn.commit()
    logger.debug("Analysis DB initialized at %s", _db_path)


def get_db_path() -> Path | None:
    """Return the current database path, or None if not initialized."""
    return _db_path


# ---------------------------------------------------------------------------
# Query operations (read-only)
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


# ---------------------------------------------------------------------------
# Headline projection (read-time)
# ---------------------------------------------------------------------------
# omd stores a run's final case as a raw OpenMDAO recorder dump: ~100
# fully-qualified promoted-variable paths, mostly arrays, with the scalar
# headline values buried at deep dotted paths. The sdk artifact envelope, by
# contrast, already exposes named headline scalars (CL, CD, L_over_D, ...).
# `project_headline` conforms the omd shape to that clean form at read time,
# so a consumer reads one normalized contract from both patterns. It is purely
# additive: it does not touch how cases are stored or how plots are generated.

# Curated common performance metrics for the OAS factories, in display order.
# Each entry is (short_name, [path patterns in priority order], unit). The
# patterns are matched against the final-case keys; the first that resolves to
# a scalar wins. Tools without these keys simply contribute nothing here -- the
# plan-driven objective below is what makes the projection general.
_HEADLINE_METRICS: list[tuple[str, list[str], str]] = [
    ("CL", ["total_perf.CL_CD.CL", ".CL_CD.CL", "aero_funcs.CL.CL"], ""),
    ("CD", ["total_perf.CL_CD.CD", ".CL_CD.CD", "aero_funcs.CD.CD"], ""),
    ("CM", ["total_perf.moment.CM", ".moment.CM"], ""),
    ("fuelburn", ["total_perf.fuelburn.fuelburn", ".fuelburn"], "kg"),
    ("failure", ["struct_funcs.failure.failure", ".failure"], ""),
    (
        "structural_mass",
        ["structural_mass.structural_mass", ".structural_mass"],
        "kg",
    ),
    ("S_ref", ["total_perf.sum_areas.S_ref_total", ".S_ref"], "m^2"),
]

# Short-name -> unit hints for plan-declared objectives whose plan entry omits
# units. Plan-supplied units always take precedence over this table.
_UNIT_HINTS: dict[str, str] = {
    "fuelburn": "kg",
    "structural_mass": "kg",
    "alpha": "deg",
    "twist": "deg",
}


def _scalarize(value: object) -> float | None:
    """Reduce a recorder value to a scalar float, or None.

    Scalars pass through (NaN/inf rejected). For arrays the magnitude-max is
    used (worst-case), matching the constraint-assertion convention.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return f
    if isinstance(value, (list, tuple)):
        scalars = [_scalarize(v) for v in value]
        valid = [s for s in scalars if s is not None]
        if valid:
            return max(valid, key=abs)
    return None


def _resolve_path(data: dict, patterns: list[str]) -> float | None:
    """Resolve the first of ``patterns`` to a scalar in ``data``.

    For each pattern, tries exact key, then a key ending with the pattern,
    then the pattern as a substring. Returns the first scalar found.
    """
    for pattern in patterns:
        if pattern in data:
            v = _scalarize(data[pattern])
            if v is not None:
                return v
        for key, val in data.items():
            if key.endswith(pattern):
                v = _scalarize(val)
                if v is not None:
                    return v
        for key, val in data.items():
            if pattern in key:
                v = _scalarize(val)
                if v is not None:
                    return v
    return None


def resolve_scalar(data: dict, name: str) -> float | None:
    """Resolve a (possibly partial) variable name to a scalar in case data.

    A run's case data is keyed by fully-qualified OpenMDAO paths, but plans
    refer to variables by partial names (e.g. ``AS_point_0.fuelburn`` for the
    recorder key ``AS_point_0.total_perf.fuelburn.fuelburn``). This applies the
    same exact -> suffix -> substring matching the headline projection uses, so
    callers reading per-iteration trajectories resolve names the same way.
    Arrays reduce to their magnitude-max scalar; returns None if unresolved.
    """
    label = name.rsplit(".", 1)[-1]
    return _resolve_path(data, [name, "." + label, label])


def _final_case_data(run_id: str) -> dict:
    """Return the final case's data dict for a run (or the last case)."""
    cases = query_run_results(run_id)
    if not cases:
        return {}
    final = [c for c in cases if c.get("case_type") == "final"]
    chosen = final[-1] if final else cases[-1]
    return chosen.get("data") or {}


def project_headline(run_id: str, plan: dict | None = None) -> list[dict]:
    """Project a run's final case into ordered headline metrics.

    Returns a list of ``{"name", "label", "value", "unit", "role"}`` dicts,
    objective first (when the plan declares one), then curated performance
    metrics that resolve in the final case. ``L_over_D`` is derived from
    ``CL``/``CD`` when both are present (so omd runs match the sdk envelope,
    which exposes it directly). This is read-only and does not require
    OpenMDAO.

    The plan makes the projection tool-general: any factory's objective is
    surfaced by name, even one the curated metric table knows nothing about.
    """
    data = _final_case_data(run_id)
    if not data:
        return []

    headline: list[dict] = []
    seen: set[str] = set()

    # 1. Plan objective (general across tools).
    objective = (plan or {}).get("objective") or {}
    obj_name = objective.get("name")
    if obj_name:
        label = obj_name.rsplit(".", 1)[-1]
        value = resolve_scalar(data, obj_name)
        if value is not None:
            unit = objective.get("units") or _UNIT_HINTS.get(label, "")
            headline.append({
                "name": obj_name,
                "label": label,
                "value": value,
                "unit": unit,
                "role": "objective",
            })
            seen.add(label)

    # 2. Curated performance metrics present in the data.
    for short, patterns, unit in _HEADLINE_METRICS:
        if short in seen:
            continue
        value = _resolve_path(data, patterns)
        if value is not None:
            headline.append({
                "name": short,
                "label": short,
                "value": value,
                "unit": unit,
                "role": "metric",
            })
            seen.add(short)

    # 3. Derived lift-to-drag, to match the sdk envelope's L_over_D.
    cl = next((m["value"] for m in headline if m["label"] == "CL"), None)
    cd = next((m["value"] for m in headline if m["label"] == "CD"), None)
    if cl is not None and cd not in (None, 0) and "L_over_D" not in seen:
        headline.append({
            "name": "L_over_D",
            "label": "L_over_D",
            "value": cl / cd,
            "unit": "",
            "role": "metric",
        })

    return headline
