"""Shared provenance MCP tools (start_session, log_decision, ...).

Every hangar tool server exposes the same four provenance tools; the
implementations used to be verbatim copies in each package's
``tools/session.py``. ``build_provenance_tools(sessions)`` returns the four
async tool functions bound to the calling package's session manager (used by
``export_session_graph`` to resolve the session's project for the graph
flush path).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated

from hangar.sdk.auth import get_current_user
from hangar.sdk.helpers import _get_viewer_base_url
from hangar.sdk.provenance.db import (
    _next_seq,
    record_cross_reference,
    record_decision,
    record_session,
    session_exists,
)
from hangar.sdk.provenance.middleware import (
    _get_session_id,
    _prov_session_id,
    set_server_session_id,
)


def build_provenance_tools(sessions) -> SimpleNamespace:
    """Return the four provenance tools bound to *sessions* (a SessionManager)."""

    async def start_session(
        notes: Annotated[str, "Optional notes describing this provenance session"] = "",
        session_id: Annotated[
            str | None,
            "Session ID to join (for cross-tool workflows). "
            "If None, a new session is created. If the ID already exists, "
            "this server joins the existing session.",
        ] = None,
    ) -> dict:
        """Start a new provenance session and set it as the current session.

        Returns ``{session_id, started_at, joined}``.  Call this at the
        beginning of a workflow to group all subsequent tool calls under a
        named session.

        Pass an existing ``session_id`` to join a session created by another
        tool server (for cross-tool workflows that share provenance).
        """
        joined = False
        if session_id is not None and session_exists(session_id):
            joined = True
        elif session_id is None:
            session_id = f"sess-{uuid.uuid4().hex[:12]}"

        started_at = datetime.now(timezone.utc).isoformat()
        if not joined:
            record_session(session_id, notes=notes, user=get_current_user())
        # Per-user active session so all subsequent tool calls (separate
        # asyncio tasks / requests) are recorded under this session.
        set_server_session_id(session_id)
        # Also set ContextVar for test isolation (has priority).
        _prov_session_id.set(session_id)
        return {"session_id": session_id, "started_at": started_at, "joined": joined}

    async def log_decision(
        decision_type: Annotated[
            str,
            "Category of decision (e.g. 'dv_selection', 'constraint_choice', "
            "'result_interpretation', 'convergence_assessment')",
        ],
        reasoning: Annotated[str, "Explanation of why this decision was made"],
        selected_action: Annotated[str, "The action or value chosen"],
        prior_call_id: Annotated[
            str | None,
            "call_id from the _provenance field of a preceding tool result that informed this decision",
        ] = None,
        confidence: Annotated[
            str, "Confidence level: 'high', 'medium', or 'low'"
        ] = "medium",
    ) -> dict:
        """Record a reasoning/decision step in the provenance log.

        Use this before major steps (choosing design variables, interpreting
        unexpected results) to create an audit trail. Returns ``{decision_id}``.
        """
        session_id = _get_session_id()
        decision_id = str(uuid.uuid4())
        seq = _next_seq(session_id)
        record_decision(
            decision_id=decision_id,
            session_id=session_id,
            seq=seq,
            decision_type=decision_type,
            reasoning=reasoning,
            prior_call_id=prior_call_id,
            selected_action=selected_action,
            confidence=confidence,
        )
        return {"decision_id": decision_id}

    async def link_cross_tool_result(
        source_call_id: Annotated[
            str,
            "call_id from the source tool's _provenance field",
        ],
        source_tool: Annotated[
            str,
            "Name of the source tool server (e.g. 'oas', 'ocp', 'pyc')",
        ],
        target_tool: Annotated[
            str,
            "Name of the target tool server that will consume this data",
        ],
        target_call_id: Annotated[
            str | None,
            "call_id from the target tool's _provenance field (if known)",
        ] = None,
        variables: Annotated[
            dict | None,
            "Data being passed between tools (e.g. {'CD': 0.032, 'structural_mass': 1500})",
        ] = None,
        notes: Annotated[
            str,
            "Description of the data handoff",
        ] = "",
    ) -> dict:
        """Record a cross-tool data dependency in the provenance graph.

        Call this when passing results from one tool server to another (e.g.,
        using OAS drag output as input to OCP mission analysis). Creates a
        visible edge in the provenance DAG connecting the two tool calls.

        Returns ``{ref_id}``.
        """
        session_id = _get_session_id()
        ref_id = str(uuid.uuid4())
        record_cross_reference(
            ref_id=ref_id,
            session_id=session_id,
            source_call_id=source_call_id,
            source_tool=source_tool,
            target_call_id=target_call_id,
            target_tool=target_tool,
            variables=variables,
            notes=notes,
        )
        return {"ref_id": ref_id}

    async def export_session_graph(
        session_id: Annotated[
            str | None,
            "Session ID to export (None = current session)",
        ] = None,
    ) -> dict:
        """Export the provenance graph for a session as a JSON dict.

        Returns ``{session_id, graph_path, viewer_url, node_count, edge_count}``
        where *graph_path* is the auto-generated file in the artifact
        directory. Load the JSON into the provenance viewer to visualise the
        DAG.
        """
        from hangar.sdk.provenance.flush import flush_session_graph

        sid = session_id or _get_session_id()

        user = get_current_user()
        try:
            session = sessions.get(sid)
            project = session.project
        except Exception:
            project = None

        flush_result = flush_session_graph(sid, user=user, project=project)

        viewer_url: str | None = None
        try:
            base = _get_viewer_base_url()
            if base:
                viewer_url = f"{base}/viewer?session_id={sid}"
        except Exception:
            pass

        unified_viewer_url: str | None = None
        try:
            from hangar.sdk.helpers import _get_unified_viewer_url
            ubase = _get_unified_viewer_url()
            if ubase:
                unified_viewer_url = f"{ubase}/viewer?session_id={sid}"
        except Exception:
            pass

        return {
            "session_id": sid,
            "graph_path": flush_result.get("path"),
            "viewer_url": viewer_url,
            "unified_viewer_url": unified_viewer_url,
            "node_count": flush_result.get("node_count", 0),
            "edge_count": flush_result.get("edge_count", 0),
        }

    return SimpleNamespace(
        start_session=start_session,
        log_decision=log_decision,
        link_cross_tool_result=link_cross_tool_result,
        export_session_graph=export_session_graph,
    )
