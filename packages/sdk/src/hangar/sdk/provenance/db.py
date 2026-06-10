"""SQLite provenance database schema and operations.

Migrated from: OpenAeroStruct/oas_mcp/provenance/db.py
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_db_path: Path | None = None
_local = threading.local()


# ---------------------------------------------------------------------------
# JSON serialiser that handles numpy types (canonical home: sdk.serialization)
# ---------------------------------------------------------------------------

from hangar.sdk.serialization import (  # noqa: E402
    NumpyEncoder as _NumpyEncoder,  # noqa: F401 -- re-export for callers
    json_dumps as _dumps,
    sanitize_for_json as _sanitize_for_json,  # noqa: F401 -- re-export for callers
)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, creating it if necessary."""
    conn = getattr(_local, "conn", None)
    # Invalidate cached connection if the db path has changed (e.g., test isolation)
    cached_path = getattr(_local, "conn_path", None)
    if conn is None or cached_path != _db_path:
        if _db_path is None:
            raise RuntimeError("Provenance DB not initialised — call init_db() first.")
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = sqlite3.connect(str(_db_path), check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        _local.conn_path = _db_path
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    notes        TEXT,
    oas_session_id TEXT,
    started_at   TEXT NOT NULL,
    user         TEXT DEFAULT '',
    project      TEXT DEFAULT 'default',
    tool         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id      TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    tool_name    TEXT NOT NULL,
    inputs_json  TEXT,
    outputs_json TEXT,
    status       TEXT NOT NULL DEFAULT 'ok',
    error_msg    TEXT,
    started_at   TEXT NOT NULL,
    duration_s   REAL,
    tool         TEXT DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id     TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    decision_type   TEXT NOT NULL,
    reasoning       TEXT,
    prior_call_id   TEXT,
    selected_action TEXT,
    confidence      TEXT DEFAULT 'medium',
    recorded_at     TEXT NOT NULL,
    tool            TEXT DEFAULT '',
    metadata_json   TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS cross_references (
    ref_id          TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    source_call_id  TEXT NOT NULL,
    source_tool     TEXT NOT NULL,
    target_call_id  TEXT,
    target_tool     TEXT NOT NULL,
    variables_json  TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS requirements (
    session_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    path        TEXT NOT NULL,
    operator    TEXT NOT NULL,
    value_json  TEXT,
    label       TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS seq_counters (
    session_id TEXT PRIMARY KEY,
    last_seq   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_decisions_session  ON decisions(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_cross_refs_session ON cross_references(session_id);
CREATE INDEX IF NOT EXISTS idx_requirements_session ON requirements(session_id, seq);
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: Path | str | None = None) -> None:
    """Initialise (or re-point) the provenance database.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  If *None*, uses ``$HANGAR_PROV_DB``
        (or legacy ``$OAS_PROV_DB``), then falls back to
        ``$HANGAR_DATA_DIR/.provenance/sessions.db`` (co-located with
        artifacts).  If the legacy ``~/.oas_provenance/sessions.db``
        exists but the new default does not, the legacy location is used
        and a warning is logged.  Parent directories are created
        automatically.
    """
    global _db_path

    if db_path is None:
        from hangar.sdk.env import _hangar_env

        env_val = _hangar_env("HANGAR_PROV_DB", "OAS_PROV_DB")
        if env_val:
            db_path = Path(env_val)
        else:
            from hangar.sdk.artifacts.store import _default_data_dir

            new_default = _default_data_dir() / ".provenance" / "sessions.db"
            old_default = Path.home() / ".oas_provenance" / "sessions.db"

            if old_default.exists() and not new_default.exists():
                logger.warning(
                    "Provenance DB found at legacy location %s but not at new default %s. "
                    "Using legacy location. Set HANGAR_PROV_DB=%s to silence this warning, "
                    "or move the file to the new location.",
                    old_default, new_default, old_default,
                )
                db_path = old_default
            else:
                db_path = new_default
    new_path = Path(db_path)

    # Close the existing per-thread connection before switching paths so that
    # SQLite releases any file locks.  _get_conn() will create a fresh one.
    old_conn = getattr(_local, "conn", None)
    if old_conn is not None:
        try:
            old_conn.close()
        except Exception:
            pass
        _local.conn = None
        _local.conn_path = None

    _db_path = new_path
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    conn.executescript(_DDL)
    # Migrate existing DBs that lack newer columns.
    try:
        conn.execute("SELECT user FROM sessions LIMIT 0")
    except Exception:
        conn.execute("ALTER TABLE sessions ADD COLUMN user TEXT DEFAULT ''")
    try:
        conn.execute("SELECT project FROM sessions LIMIT 0")
    except Exception:
        conn.execute("ALTER TABLE sessions ADD COLUMN project TEXT DEFAULT 'default'")
    # Migrate: add tool column to all three tables.
    for table in ("sessions", "tool_calls", "decisions"):
        try:
            conn.execute(f"SELECT tool FROM {table} LIMIT 0")
        except Exception:
            logger.info("Migrating %s: adding tool column", table)
            conn.execute(f"ALTER TABLE {table} ADD COLUMN tool TEXT DEFAULT ''")
    # Migrate: add metadata_json to decisions (carries conclusion payloads).
    try:
        conn.execute("SELECT metadata_json FROM decisions LIMIT 0")
    except Exception:
        logger.info("Migrating decisions: adding metadata_json column")
        conn.execute("ALTER TABLE decisions ADD COLUMN metadata_json TEXT")
    conn.commit()


def record_session(
    session_id: str,
    notes: str = "",
    oas_session_id: str | None = None,
    user: str = "",
    project: str = "default",
    tool: str = "",
) -> None:
    """Insert a new provenance session record (ignore if already exists)."""
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO sessions(session_id, notes, oas_session_id, started_at, user, project, tool)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, notes, oas_session_id, datetime.now(timezone.utc).isoformat(), user, project, tool),
    )
    conn.commit()


def _ensure_session(session_id: str, user: str = "", project: str = "default", tool: str = "") -> None:
    """Auto-create a session row if one does not already exist.

    Satisfies the FK constraint on tool_calls and decisions without requiring
    an explicit start_session() call.
    """
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO sessions(session_id, notes, oas_session_id, started_at, user, project, tool)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, "auto-created", None, datetime.now(timezone.utc).isoformat(), user, project, tool),
    )
    conn.commit()


def record_tool_call(
    call_id: str,
    session_id: str,
    seq: int,
    tool_name: str,
    inputs_json: str,
    outputs_json: str,
    status: str,
    error_msg: str | None,
    started_at: str,
    duration_s: float | None,
    tool: str = "",
) -> None:
    """Insert a tool-call record."""
    _ensure_session(session_id, tool=tool)
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO tool_calls
            (call_id, session_id, seq, tool_name, inputs_json, outputs_json,
             status, error_msg, started_at, duration_s, tool)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            call_id,
            session_id,
            seq,
            tool_name,
            inputs_json,
            outputs_json,
            status,
            error_msg,
            started_at,
            duration_s,
            tool,
        ),
    )
    conn.commit()


def record_decision(
    decision_id: str,
    session_id: str,
    seq: int,
    decision_type: str,
    reasoning: str,
    prior_call_id: str | None,
    selected_action: str,
    confidence: str = "medium",
    tool: str = "",
    metadata_json: str | None = None,
) -> None:
    """Insert a decision record.

    ``metadata_json`` carries an optional structured payload for decision types
    that need one (notably ``conclusion``, whose payload holds the per-requirement
    verdicts derived against a chosen run). Plain reasoning decisions leave it None.
    """
    _ensure_session(session_id, tool=tool)
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO decisions
            (decision_id, session_id, seq, decision_type, reasoning,
             prior_call_id, selected_action, confidence, recorded_at, tool, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            session_id,
            seq,
            decision_type,
            reasoning,
            prior_call_id,
            selected_action,
            confidence,
            datetime.now(timezone.utc).isoformat(),
            tool,
            metadata_json,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


def record_requirements(session_id: str, requirements: list[dict]) -> None:
    """Persist the session's requirement set with replace semantics.

    sdk requirements are ``{path, operator, value, label}`` dot-path assertions
    set via the ``set_requirements`` / ``configure_session`` tools. They live in
    the runtime SessionManager during a session; persisting them here lets the
    dashboard replay the Gather-Requirements / Report views for a finished
    session instead of leaving them empty.

    The full set is replaced on every call, mirroring the runtime semantics of
    ``Session.set_requirements`` (which overwrites the list wholesale).
    """
    _ensure_session(session_id)
    conn = _get_conn()
    conn.execute("DELETE FROM requirements WHERE session_id=?", (session_id,))
    now = datetime.now(timezone.utc).isoformat()
    for seq, req in enumerate(requirements or []):
        # ``value`` is the canonical comparison key; pyc historically uses
        # ``target`` for the same field, so accept either.
        value = req.get("value", req.get("target"))
        conn.execute(
            """
            INSERT INTO requirements
                (session_id, seq, path, operator, value_json, label, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                seq,
                str(req.get("path", "")),
                str(req.get("operator", "")),
                _dumps(value),
                req.get("label"),
                now,
            ),
        )
    conn.commit()


def get_requirements(session_id: str) -> list[dict]:
    """Return the persisted requirement set for *session_id* in set order.

    Each entry is ``{path, operator, value, label}`` — the same shape passed to
    ``set_requirements``. Returns an empty list if none were persisted (or the
    table predates this feature).
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT path, operator, value_json, label FROM requirements "
            "WHERE session_id=? ORDER BY seq",
            (session_id,),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "path": r["path"],
            "operator": r["operator"],
            "value": _try_json(r["value_json"]),
            "label": r["label"],
        }
        for r in rows
    ]


def get_conclusion(session_id: str) -> dict | None:
    """Return the latest recorded conclusion for *session_id*, or None.

    A conclusion is a ``decision`` row with ``decision_type='conclusion'`` whose
    ``metadata_json`` holds the auto-derived per-requirement verdicts and overall
    verdict for a chosen run (written by ``provenance.conclusion.record_conclusion``).
    The returned dict is the parsed payload plus ``conclusion_id`` / ``created_at``.
    Returns None if the session has no conclusion (or the column predates this
    feature).
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT decision_id, recorded_at, metadata_json FROM decisions "
            "WHERE session_id=? AND decision_type='conclusion' "
            "AND metadata_json IS NOT NULL ORDER BY seq DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        meta = json.loads(row["metadata_json"])
    except (json.JSONDecodeError, TypeError):
        meta = {}
    meta.setdefault("conclusion_id", row["decision_id"])
    meta["created_at"] = row["recorded_at"]
    return meta


def _next_seq(session_id: str) -> int:
    """Atomically claim the next sequence number for *session_id*.

    Uses a per-session counter row claimed via a single UPSERT statement, so
    concurrent claimants (threads, or processes sharing the DB file) cannot
    read the same MAX(seq) and collide. The counter seeds itself from the
    existing tool_calls/decisions rows so legacy DBs continue where they
    left off.
    """
    conn = _get_conn()
    with conn:
        row = conn.execute(
            """
            INSERT INTO seq_counters (session_id, last_seq)
            VALUES (
                :sid,
                (SELECT COALESCE(MAX(s), -1) + 1 FROM (
                    SELECT MAX(seq) AS s FROM tool_calls WHERE session_id = :sid
                    UNION ALL
                    SELECT MAX(seq) AS s FROM decisions WHERE session_id = :sid
                ))
            )
            ON CONFLICT(session_id) DO UPDATE SET last_seq = last_seq + 1
            RETURNING last_seq
            """,
            {"sid": session_id},
        ).fetchone()
    return int(row[0])


def get_session_graph(session_id: str) -> dict:
    """Return a graph dict ``{session, nodes, edges}`` for the HTML viewer.

    Edge logic
    ----------
    * ``tool_call → decision``  when ``decision.prior_call_id == tool_call.call_id``
      (label: "informs")
    * ``decision → tool_call``  when a decision's seq immediately precedes the next
      tool call with no intervening decision (label: "decides")
    * ``tool_call[n] → tool_call[n+1]``  when no decision sits between them
      (label: "sequence")
    """
    conn = _get_conn()

    session_row = conn.execute(
        "SELECT * FROM sessions WHERE session_id=?", (session_id,)
    ).fetchone()

    tool_rows = conn.execute(
        "SELECT * FROM tool_calls WHERE session_id=? ORDER BY seq",
        (session_id,),
    ).fetchall()

    decision_rows = conn.execute(
        "SELECT * FROM decisions WHERE session_id=? ORDER BY seq",
        (session_id,),
    ).fetchall()

    # Build nodes
    nodes: list[dict] = []
    for r in tool_rows:
        node = {
            "id": r["call_id"],
            "type": "tool_call",
            "seq": r["seq"],
            "tool_name": r["tool_name"],
            "status": r["status"],
            "error_msg": r["error_msg"],
            "started_at": r["started_at"],
            "duration_s": r["duration_s"],
            "inputs": _try_json(r["inputs_json"]),
            "outputs": _try_json(r["outputs_json"]),
        }
        try:
            node["tool"] = r["tool"]
        except (IndexError, KeyError):
            pass
        nodes.append(node)
    for r in decision_rows:
        node = {
            "id": r["decision_id"],
            "type": "decision",
            "seq": r["seq"],
            "decision_type": r["decision_type"],
            "reasoning": r["reasoning"],
            "prior_call_id": r["prior_call_id"],
            "selected_action": r["selected_action"],
            "confidence": r["confidence"],
            "recorded_at": r["recorded_at"],
        }
        try:
            node["tool"] = r["tool"]
        except (IndexError, KeyError):
            pass
        nodes.append(node)

    # Sort nodes by seq for edge computation
    nodes.sort(key=lambda n: n["seq"])

    # Index nodes by call_id/decision_id
    id_to_node = {n["id"]: n for n in nodes}

    # Build edges
    edges: list[dict] = []
    tc_by_id = {r["call_id"]: dict(r) for r in tool_rows}
    dec_by_prior = {}
    for r in decision_rows:
        if r["prior_call_id"]:
            dec_by_prior.setdefault(r["prior_call_id"], []).append(dict(r))

    # Edge type 1: tool_call → decision (informs)
    for call_id, decisions in dec_by_prior.items():
        for d in decisions:
            edges.append(
                {
                    "source": call_id,
                    "target": d["decision_id"],
                    "label": "informs",
                }
            )

    # Edge types 2 & 3: build from sorted node sequence
    tool_nodes = [n for n in nodes if n["type"] == "tool_call"]
    decision_nodes_by_id = {n["id"]: n for n in nodes if n["type"] == "decision"}

    for i, tn in enumerate(tool_nodes):
        if i + 1 >= len(tool_nodes):
            break
        next_tn = tool_nodes[i + 1]

        # Check if a decision falls between tn.seq and next_tn.seq
        between_decisions = [
            n for n in nodes
            if n["type"] == "decision" and tn["seq"] < n["seq"] < next_tn["seq"]
        ]

        if between_decisions:
            # Edge type 2: decision → next tool_call (decides)
            for d in between_decisions:
                edges.append(
                    {
                        "source": d["id"],
                        "target": next_tn["id"],
                        "label": "decides",
                    }
                )
        else:
            # Edge type 3: tool_call[n] → tool_call[n+1] (sequence)
            edges.append(
                {
                    "source": tn["id"],
                    "target": next_tn["id"],
                    "label": "sequence",
                }
            )

    # Edge type 4: cross-tool references.
    # In per-tool viewers, source or target may live in another tool's DB,
    # so skip edges where either endpoint is missing from the local graph.
    try:
        xref_rows = conn.execute(
            "SELECT * FROM cross_references WHERE session_id=?", (session_id,)
        ).fetchall()
        for xr in xref_rows:
            src = xr["source_call_id"]
            tgt = xr["target_call_id"]
            if src not in id_to_node or (tgt and tgt not in id_to_node):
                continue
            edges.append(
                {
                    "source": src,
                    "target": tgt,
                    "label": "cross_tool",
                    "source_tool": xr["source_tool"],
                    "target_tool": xr["target_tool"],
                    "variables": _try_json(xr["variables_json"]),
                    "notes": xr["notes"],
                }
            )
    except Exception:
        pass  # table may not exist in older DBs

    session_meta = dict(session_row) if session_row else {"session_id": session_id}
    return {"session": session_meta, "nodes": nodes, "edges": edges}


def build_session_elements(session_id: str) -> dict:
    """Build Cytoscape elements for a session's tool-call/decision graph.

    Returns ``{"nodes": [...], "edges": [...]}`` where each element is a
    Cytoscape-native ``{"data": {...}}`` dict, using the same normalized
    shape as the omd provenance builder
    (``hangar.omd.provenance.build_provenance_elements``): every node carries
    a ``kind`` style key (``tool_call`` / ``decision``) and a ``label``;
    every edge carries ``source`` / ``target`` / ``relation``. This lets the
    range-safety dashboard render the execution graph for any sdk-backed tool
    (oas / ocp / pyc) with the same Cytoscape style it uses for omd.

    Dangling edges (endpoints outside the local session, e.g. cross-tool
    references in a per-tool DB) are dropped.
    """
    graph = get_session_graph(session_id)

    nodes: list[dict] = []
    for n in graph["nodes"]:
        data = dict(n)
        if n.get("type") == "tool_call":
            data["label"] = n.get("tool_name") or n["id"]
        else:
            label = n.get("decision_type") or "decision"
            reasoning = n.get("reasoning")
            if reasoning:
                label = f"{label}\n{str(reasoning)[:140]}"
            data["label"] = label
        data["kind"] = n.get("type")
        nodes.append({"data": data})

    node_ids = {nd["data"]["id"] for nd in nodes}
    edges: list[dict] = []
    for e in graph["edges"]:
        src, tgt = e.get("source"), e.get("target")
        if src not in node_ids or tgt not in node_ids:
            continue
        data = dict(e)
        data["relation"] = e.get("label")
        edges.append({"data": data})

    return {"nodes": nodes, "edges": edges}


def update_session_project(session_id: str, project: str) -> None:
    """Update the project field for an existing session."""
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET project = ? WHERE session_id = ?",
        (project, session_id),
    )
    conn.commit()


def get_session_meta(session_id: str) -> dict | None:
    """Return session metadata, or *None* if the session does not exist."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT session_id, user, project, notes, started_at FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def session_exists(session_id: str) -> bool:
    """Return True if a session with the given ID exists in the provenance DB."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row is not None


def get_session_owner(session_id: str) -> str:
    """Return the user who owns *session_id*, or ``""`` if unset/not found."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT user FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row["user"] if row else ""


def list_sessions(user: str | None = None) -> list[dict]:
    """Return sessions with metadata.

    Parameters
    ----------
    user:
        If given, only return sessions owned by this user (or sessions with
        no user set, for backward compatibility with pre-OIDC data).
        ``None`` returns all sessions.
    """
    conn = _get_conn()
    if user is not None:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user = ? OR user = '' ORDER BY started_at DESC",
            (user,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        tc_count = conn.execute(
            "SELECT COUNT(*) FROM tool_calls WHERE session_id=?", (r["session_id"],)
        ).fetchone()[0]
        dec_count = conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE session_id=?", (r["session_id"],)
        ).fetchone()[0]
        try:
            concl_count = conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE session_id=? "
                "AND decision_type='conclusion'", (r["session_id"],)
            ).fetchone()[0]
        except Exception:
            concl_count = 0
        d["tool_call_count"] = tc_count
        d["decision_count"] = dec_count
        d["conclusion_count"] = concl_count
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Cross-tool references
# ---------------------------------------------------------------------------


def record_cross_reference(
    ref_id: str,
    session_id: str,
    source_call_id: str,
    source_tool: str,
    target_call_id: str | None,
    target_tool: str,
    variables: dict | None = None,
    notes: str = "",
) -> None:
    """Record a cross-tool data dependency."""
    _ensure_session(session_id)
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO cross_references
            (ref_id, session_id, source_call_id, source_tool,
             target_call_id, target_tool, variables_json, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ref_id,
            session_id,
            source_call_id,
            source_tool,
            target_call_id,
            target_tool,
            _dumps(variables) if variables else None,
            notes,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_cross_references(session_id: str) -> list[dict]:
    """Return all cross-tool references for a session."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM cross_references WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "ref_id": r["ref_id"],
            "session_id": r["session_id"],
            "source_call_id": r["source_call_id"],
            "source_tool": r["source_tool"],
            "target_call_id": r["target_call_id"],
            "target_tool": r["target_tool"],
            "variables": _try_json(r["variables_json"]),
            "notes": r["notes"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _try_json(s: str | None) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s
