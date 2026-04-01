"""Read-only aggregation layer for multiple per-tool provenance SQLite databases.

Each tool server writes to its own SQLite DB.  This reader opens all of
them in read-only mode and merges sessions/graphs across tools, giving
the unified viewer a single API to query.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class MultiDBProvenanceReader:
    """Read-only access to multiple per-tool provenance databases.

    Parameters
    ----------
    db_paths:
        Mapping of tool name to SQLite database path, e.g.
        ``{"oas": Path("/data/oas/provenance.db"), ...}``.
    """

    def __init__(self, db_paths: dict[str, Path]) -> None:
        self._db_paths = db_paths
        self._local = threading.local()

    def _get_conn(self, tool: str) -> sqlite3.Connection:
        """Return a per-thread read-only connection for *tool*."""
        conns: dict[str, sqlite3.Connection] = getattr(self._local, "conns", {})

        if tool not in conns:
            path = self._db_paths[tool]
            if not path.exists():
                raise FileNotFoundError(f"Provenance DB not found: {path}")
            conn = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, check_same_thread=False, timeout=10,
            )
            conn.row_factory = sqlite3.Row
            conns[tool] = conn
            self._local.conns = conns

        return conns[tool]

    def _query(self, tool: str, sql: str, params: tuple = ()) -> list[dict]:
        """Run a read-only query against a single tool's DB."""
        try:
            conn = self._get_conn(tool)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except (FileNotFoundError, sqlite3.OperationalError):
            return []

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def list_sessions(self, user: str | None = None) -> list[dict]:
        """Merge sessions from all tool DBs, sorted by started_at desc."""
        all_sessions: dict[str, dict] = {}

        for tool in self._db_paths:
            if user is not None:
                sql = (
                    "SELECT * FROM sessions WHERE user = ? OR user = '' "
                    "ORDER BY started_at DESC"
                )
                rows = self._query(tool, sql, (user,))
            else:
                sql = "SELECT * FROM sessions ORDER BY started_at DESC"
                rows = self._query(tool, sql)

            for row in rows:
                sid = row["session_id"]
                if sid not in all_sessions:
                    all_sessions[sid] = {
                        **row,
                        "tools": [tool],
                        "tool_call_count": 0,
                        "decision_count": 0,
                    }
                else:
                    if tool not in all_sessions[sid]["tools"]:
                        all_sessions[sid]["tools"].append(tool)

                # Count tool calls and decisions from this tool's DB
                tc_rows = self._query(
                    tool,
                    "SELECT COUNT(*) as cnt FROM tool_calls WHERE session_id=?",
                    (sid,),
                )
                dec_rows = self._query(
                    tool,
                    "SELECT COUNT(*) as cnt FROM decisions WHERE session_id=?",
                    (sid,),
                )
                tc_count = tc_rows[0]["cnt"] if tc_rows else 0
                dec_count = dec_rows[0]["cnt"] if dec_rows else 0
                all_sessions[sid]["tool_call_count"] += tc_count
                all_sessions[sid]["decision_count"] += dec_count

        result = sorted(
            all_sessions.values(),
            key=lambda s: s.get("started_at", ""),
            reverse=True,
        )
        return result

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------

    def get_session_graph(self, session_id: str) -> dict:
        """Build a merged provenance DAG across all tool DBs for one session.

        Nodes from each tool are tagged with their ``tool`` field.  Cross-tool
        reference edges are collected from all DBs.
        """
        nodes: list[dict] = []
        seen_ids: set[str] = set()
        session_meta: dict = {"session_id": session_id}

        for tool in self._db_paths:
            # Session metadata (take the first non-empty one)
            s_rows = self._query(
                tool,
                "SELECT * FROM sessions WHERE session_id=?",
                (session_id,),
            )
            if s_rows and session_meta.get("started_at") is None:
                session_meta = s_rows[0]

            # Tool calls
            tc_rows = self._query(
                tool,
                "SELECT * FROM tool_calls WHERE session_id=? ORDER BY seq",
                (session_id,),
            )
            for r in tc_rows:
                cid = r["call_id"]
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                node = {
                    "id": cid,
                    "type": "tool_call",
                    "seq": r["seq"],
                    "tool_name": r["tool_name"],
                    "status": r.get("status", "ok"),
                    "error_msg": r.get("error_msg"),
                    "started_at": r.get("started_at", ""),
                    "duration_s": r.get("duration_s"),
                    "inputs": _try_json(r.get("inputs_json")),
                    "outputs": _try_json(r.get("outputs_json")),
                    "tool": r.get("tool", tool),
                }
                nodes.append(node)

            # Decisions
            dec_rows = self._query(
                tool,
                "SELECT * FROM decisions WHERE session_id=? ORDER BY seq",
                (session_id,),
            )
            for r in dec_rows:
                did = r["decision_id"]
                if did in seen_ids:
                    continue
                seen_ids.add(did)
                node = {
                    "id": did,
                    "type": "decision",
                    "seq": r["seq"],
                    "decision_type": r["decision_type"],
                    "reasoning": r.get("reasoning"),
                    "prior_call_id": r.get("prior_call_id"),
                    "selected_action": r.get("selected_action"),
                    "confidence": r.get("confidence", "medium"),
                    "recorded_at": r.get("recorded_at", ""),
                    "tool": r.get("tool", tool),
                }
                nodes.append(node)

        # Sort nodes by timestamp for correct cross-tool ordering.
        # Within a single tool DB, seq is reliable, but across DBs each
        # tool has its own seq counter starting at 0.  Use started_at/
        # recorded_at as primary sort key, seq as tiebreaker within a tool.
        def _sort_key(n):
            ts = n.get("started_at") or n.get("recorded_at") or ""
            return (ts, n.get("tool", ""), n["seq"])
        nodes.sort(key=_sort_key)

        # Build edges (same logic as db.py get_session_graph)
        edges: list[dict] = []

        # Index
        tc_nodes = [n for n in nodes if n["type"] == "tool_call"]
        dec_by_prior: dict[str, list[dict]] = {}
        for n in nodes:
            if n["type"] == "decision" and n.get("prior_call_id"):
                dec_by_prior.setdefault(n["prior_call_id"], []).append(n)

        # Edge type 1: tool_call -> decision (informs)
        for call_id, decisions in dec_by_prior.items():
            for d in decisions:
                edges.append({
                    "source": call_id,
                    "target": d["id"],
                    "label": "informs",
                })

        # Edge types 2 & 3
        for i, tn in enumerate(tc_nodes):
            if i + 1 >= len(tc_nodes):
                break
            next_tn = tc_nodes[i + 1]
            between = [
                n for n in nodes
                if n["type"] == "decision" and tn["seq"] < n["seq"] < next_tn["seq"]
            ]
            if between:
                for d in between:
                    edges.append({
                        "source": d["id"],
                        "target": next_tn["id"],
                        "label": "decides",
                    })
            else:
                edges.append({
                    "source": tn["id"],
                    "target": next_tn["id"],
                    "label": "sequence",
                })

        # Edge type 4: cross-tool references from all DBs
        for tool in self._db_paths:
            xref_rows = self._query(
                tool,
                "SELECT * FROM cross_references WHERE session_id=?",
                (session_id,),
            )
            for xr in xref_rows:
                edges.append({
                    "source": xr["source_call_id"],
                    "target": xr["target_call_id"],
                    "label": "cross_tool",
                    "source_tool": xr["source_tool"],
                    "target_tool": xr["target_tool"],
                    "variables": _try_json(xr.get("variables_json")),
                    "notes": xr.get("notes", ""),
                })

        return {"session": session_meta, "nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Session ownership
    # ------------------------------------------------------------------

    def get_session_owner(self, session_id: str) -> str:
        """Return the user who owns a session, checking all DBs."""
        for tool in self._db_paths:
            rows = self._query(
                tool,
                "SELECT user FROM sessions WHERE session_id=?",
                (session_id,),
            )
            if rows and rows[0].get("user"):
                return rows[0]["user"]
        return ""


def _try_json(s: str | None) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def parse_db_spec(spec: str) -> dict[str, Path]:
    """Parse a ``HANGAR_VIEWER_DBS`` env var into a tool-name-to-path dict.

    Format: ``"oas=/data/oas/provenance.db,ocp=/data/ocp/provenance.db,..."``
    """
    result: dict[str, Path] = {}
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"Invalid DB spec entry (expected tool=path): {entry!r}")
        tool, path_str = entry.split("=", 1)
        result[tool.strip()] = Path(path_str.strip())
    return result
