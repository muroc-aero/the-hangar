"""Session, provenance, artifact, and observability tools.

Mirrors the OAS session tools, adapted for pyCycle.
Most of the implementation is reused from hangar.sdk.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated

from hangar.sdk.auth import get_current_user
from hangar.sdk.helpers import _get_viewer_base_url, _resolve_run_id, _suppress_output
from hangar.sdk.state import artifacts as _artifacts, sessions as _sessions
from hangar.sdk.telemetry import get_run_logs
from hangar.sdk.viz.plotting import PLOT_TYPES, generate_n2, generate_plot
from hangar.sdk.provenance.middleware import _get_session_id, _prov_session_id, set_server_session_id
from hangar.sdk.provenance.db import (
    _next_seq,
    list_sessions,
    record_decision,
    record_session,
    session_exists,
    update_session_project,
)


# ---------------------------------------------------------------------------
# Provenance tools
# ---------------------------------------------------------------------------

async def start_session(
    notes: Annotated[str, "Optional notes describing this provenance session"] = "",
    session_id: Annotated[
        str | None,
        "Session ID to join (for cross-tool workflows). "
        "If None, a new session is created.",
    ] = None,
) -> dict:
    """Start a new provenance session.

    Returns ``{session_id, started_at, joined}``.  Call at workflow start
    to group all subsequent tool calls under a named session.

    Pass an existing ``session_id`` to join a session created by another tool
    server (e.g., for cross-tool workflows where pyCycle and OAS share provenance).
    """
    joined = False
    if session_id is not None and session_exists(session_id):
        joined = True
    elif session_id is None:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"

    started_at = datetime.now(timezone.utc).isoformat()
    if not joined:
        record_session(session_id, notes=notes, user=get_current_user())
    set_server_session_id(session_id)
    _prov_session_id.set(session_id)
    return {"session_id": session_id, "started_at": started_at, "joined": joined}


async def log_decision(
    decision_type: Annotated[
        str,
        "Category: 'archetype_selection', 'parameter_choice', 'result_interpretation', "
        "'dv_selection', 'constraint_choice', 'convergence_assessment'",
    ],
    reasoning: Annotated[str, "Explanation of why this decision was made"],
    selected_action: Annotated[str, "The action or value chosen"],
    prior_call_id: Annotated[str | None, "call_id from a preceding tool result"] = None,
    confidence: Annotated[str, "Confidence: 'high', 'medium', or 'low'"] = "medium",
) -> dict:
    """Record a reasoning/decision step in the provenance log.

    Returns ``{decision_id}``.
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


async def export_session_graph(
    session_id: Annotated[
        str | None,
        "Session ID to export (None = current session)",
    ] = None,
) -> dict:
    """Export the provenance graph for a session as a JSON dict.

    Returns ``{session_id, graph_path, viewer_url, node_count, edge_count}``
    where *graph_path* is the auto-generated file in the artifact directory.
    """
    from hangar.sdk.provenance.flush import flush_session_graph

    sid = session_id or _get_session_id()

    user = get_current_user()
    try:
        session = _sessions.get(sid)
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

    return {
        "session_id": sid,
        "graph_path": flush_result.get("path"),
        "viewer_url": viewer_url,
        "node_count": flush_result.get("node_count", 0),
        "edge_count": flush_result.get("edge_count", 0),
    }


# ---------------------------------------------------------------------------
# Session configuration
# ---------------------------------------------------------------------------

async def configure_session(
    session_id: Annotated[str, "Session to configure"] = "default",
    project: Annotated[str | None, "Project name for artifact grouping"] = None,
    detail_level: Annotated[str | None, "Default detail level: 'standard' or 'full'"] = None,
) -> dict:
    """Configure per-session defaults."""
    session = _sessions.get(session_id)
    if project is not None:
        session.project = project
        prov_sid = _get_session_id()
        update_session_project(prov_sid, project)
    if detail_level is not None:
        session.defaults.detail_level = detail_level
    return {"session_id": session_id, "project": session.project}


async def set_requirements(
    requirements: Annotated[
        list[dict],
        "List of requirements: [{label, path, operator, target}, ...]. "
        "path uses dot notation into results (e.g. 'performance.TSFC'). "
        "operator: '<', '<=', '>', '>=', '==', '!='.",
    ],
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Set user requirements that are checked against every analysis result."""
    session = _sessions.get(session_id)
    session.requirements = requirements
    return {"session_id": session_id, "requirements_count": len(requirements)}


async def reset(
    session_id: Annotated[str, "Session to reset"] = "default",
) -> dict:
    """Clear all engines and cached state for the session.

    Call between unrelated experiments to start fresh.
    """
    session = _sessions.get(session_id)
    session.clear()
    if hasattr(session, "engines"):
        session.engines.clear()
    return {"status": "reset", "session_id": session_id}


# ---------------------------------------------------------------------------
# Artifact management
# ---------------------------------------------------------------------------

async def list_artifacts(
    session_id: Annotated[str | None, "Filter by session"] = None,
    analysis_type: Annotated[str | None, "Filter: 'design', 'off_design', 'sweep'"] = None,
    project: Annotated[str | None, "Filter by project"] = None,
) -> dict:
    """Browse saved analysis runs."""
    items = _artifacts.list(
        session_id=session_id,
        analysis_type=analysis_type,
        project=project,
    )
    return {"count": len(items), "artifacts": items}


async def get_artifact(
    run_id: Annotated[str, "Run ID from a previous analysis"],
) -> dict:
    """Retrieve full metadata + results for a past run."""
    return _artifacts.get(run_id)


async def get_artifact_summary(
    run_id: Annotated[str, "Run ID from a previous analysis"],
) -> dict:
    """Retrieve metadata only (lightweight) for a past run."""
    return _artifacts.get(run_id, summary_only=True)


async def delete_artifact(
    run_id: Annotated[str, "Run ID to delete"],
) -> dict:
    """Remove a saved artifact."""
    _artifacts.delete(run_id)
    return {"deleted": run_id}


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

async def get_run(
    run_id: Annotated[str, "Run ID from a previous analysis"],
    session_id: Annotated[str | None, "Session hint (speeds lookup)"] = None,
) -> dict:
    """Full manifest: inputs, outputs, validation, telemetry."""
    artifact = _artifacts.get(run_id)
    if artifact is None:
        return {"error": f"Run {run_id} not found."}
    return {
        "run_id": run_id,
        "inputs": artifact.get("parameters"),
        "outputs": artifact.get("results"),
        "validation": artifact.get("validation"),
        "telemetry": artifact.get("telemetry"),
    }


async def pin_run(
    run_id: Annotated[str, "Run ID to pin"],
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Pin a run to prevent cache/artifact eviction."""
    session = _sessions.get(session_id)
    session._pinned.add(run_id)
    return {"pinned": run_id}


async def unpin_run(
    run_id: Annotated[str, "Run ID to unpin"],
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Release a pinned run."""
    session = _sessions.get(session_id)
    session._pinned.discard(run_id)
    return {"unpinned": run_id}


async def get_last_logs(
    run_id: Annotated[str, "Run ID"],
) -> dict:
    """Retrieve server-side log records for a run."""
    logs = get_run_logs(run_id)
    return {"run_id": run_id, "logs": logs}
