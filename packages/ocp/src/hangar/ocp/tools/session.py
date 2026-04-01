"""Session, provenance, artifact, and observability tools for OCP.

Adapts the OAS session tools to use the OCP session manager.
Provenance tools (start_session, log_decision, export_session_graph) are
shared across all hangar tool servers.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated

from hangar.sdk.auth import get_current_user
from hangar.sdk.helpers import _get_viewer_base_url, _resolve_run_id
from hangar.sdk.telemetry import get_run_logs
from hangar.sdk.provenance.middleware import _get_session_id, _prov_session_id, set_server_session_id
from hangar.sdk.provenance.db import (
    _next_seq,
    get_session_graph,
    record_cross_reference,
    record_decision,
    record_session,
    session_exists,
    update_session_project,
)

from hangar.ocp.state import sessions as _sessions, artifacts as _artifacts


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
    """Start a new provenance session for this OCP workflow.

    Returns ``{session_id, started_at, joined}``.
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
        "Category: 'architecture_choice', 'mission_params', 'dv_selection', "
        "'constraint_choice', 'result_interpretation', 'convergence_assessment'",
    ],
    reasoning: Annotated[str, "Explanation of why this decision was made"],
    selected_action: Annotated[str, "The action or value chosen"],
    prior_call_id: Annotated[str | None, "call_id from a preceding tool result"] = None,
    confidence: Annotated[str, "Confidence level: 'high', 'medium', or 'low'"] = "medium",
) -> dict:
    """Record a reasoning/decision step in the provenance log."""
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
    source_call_id: Annotated[str, "call_id from the source tool's _provenance field"],
    source_tool: Annotated[str, "Name of the source tool server (e.g. 'oas', 'ocp', 'pyc')"],
    target_tool: Annotated[str, "Name of the target tool server that will consume this data"],
    target_call_id: Annotated[str | None, "call_id from the target tool (if known)"] = None,
    variables: Annotated[dict | None, "Data being passed between tools"] = None,
    notes: Annotated[str, "Description of the data handoff"] = "",
) -> dict:
    """Record a cross-tool data dependency in the provenance graph.

    Call this when passing results from one tool server to another.
    Creates a visible edge in the provenance DAG connecting the two tool calls.

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
    session_id: Annotated[str | None, "Session ID to export (None = current)"] = None,
) -> dict:
    """Export the provenance graph for a session as JSON."""
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


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


async def reset(
    session_id: Annotated[str | None, "Session to reset, or None for all"] = None,
) -> dict:
    """Reset OCP sessions and cached problems."""
    from hangar.sdk.provenance.flush import flush_session_graph

    user = get_current_user()

    if session_id is None:
        try:
            current_sid = _get_session_id()
            if current_sid and current_sid != "default":
                flush_session_graph(current_sid, user=user)
        except Exception:
            pass
        _sessions.reset()
        return {"status": "All sessions reset", "cleared": "all"}
    else:
        session = _sessions.get(session_id)
        try:
            flush_session_graph(session_id, user=user, project=session.project)
        except Exception:
            pass
        session.clear()
        return {"status": f"Session '{session_id}' reset", "cleared": session_id}


async def configure_session(
    session_id: Annotated[str, "Session to configure"] = "default",
    default_detail_level: Annotated[str | None, "'summary' | 'standard'"] = None,
    validation_severity_threshold: Annotated[str | None, "'error' | 'warning' | 'info'"] = None,
    auto_visualize: Annotated[list[str] | None, "Plot types to auto-generate"] = None,
    telemetry_mode: Annotated[str | None, "'off' | 'logging' | 'otel'"] = None,
    project: Annotated[str | None, "Project name for artifact organization"] = None,
    visualization_output: Annotated[str | None, "'inline' | 'file' | 'url'"] = None,
    retention_max_count: Annotated[int | None, "Max artifacts per session"] = None,
) -> dict:
    """Configure per-session defaults."""
    session = _sessions.get(session_id)

    updates: dict = {}
    if default_detail_level is not None:
        updates["default_detail_level"] = default_detail_level
    if validation_severity_threshold is not None:
        updates["validation_severity_threshold"] = validation_severity_threshold
    if auto_visualize is not None:
        updates["auto_visualize"] = auto_visualize
    if telemetry_mode is not None:
        updates["telemetry_mode"] = telemetry_mode
    if project is not None:
        updates["project"] = project
    if visualization_output is not None:
        updates["visualization_output"] = visualization_output
    if retention_max_count is not None:
        updates["retention_max_count"] = retention_max_count

    if updates:
        session.configure(**updates)

    if project is not None:
        try:
            prov_sid = _get_session_id()
            update_session_project(prov_sid, project)
        except Exception:
            pass

    return {
        "session_id": session_id,
        "project": session.project,
        "status": "configured",
        "current_defaults": session.defaults.to_dict(),
    }


async def set_requirements(
    requirements: Annotated[
        list[dict],
        "List of requirement dicts: {path, operator, value, label}",
    ],
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Set requirements checked against every analysis result."""
    session = _sessions.get(session_id)
    session.set_requirements(requirements)
    return {
        "session_id": session_id,
        "requirements_set": len(requirements),
        "requirements": requirements,
    }


# ---------------------------------------------------------------------------
# Artifact tools
# ---------------------------------------------------------------------------


async def list_artifacts(
    session_id: Annotated[str | None, "Filter by session ID"] = None,
    analysis_type: Annotated[str | None, "Filter by type: 'mission', 'optimization'"] = None,
    project: Annotated[str | None, "Filter by project name"] = None,
) -> dict:
    """List saved analysis artifacts."""
    user = get_current_user()
    entries = await asyncio.to_thread(_artifacts.list, session_id, analysis_type, user, project)
    return {"count": len(entries), "artifacts": entries}


async def get_artifact(
    run_id: Annotated[str, "Run ID"],
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Retrieve a saved artifact by run_id."""
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Artifact '{run_id}' not found")
    return artifact


async def get_artifact_summary(
    run_id: Annotated[str, "Run ID"],
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Retrieve artifact metadata only (lightweight)."""
    user = get_current_user()
    summary = await asyncio.to_thread(_artifacts.get_summary, run_id, session_id, user)
    if summary is None:
        raise ValueError(f"Artifact '{run_id}' not found")
    return summary


async def delete_artifact(
    run_id: Annotated[str, "Run ID to delete"],
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Delete a saved artifact."""
    user = get_current_user()
    deleted = await asyncio.to_thread(_artifacts.delete, run_id, session_id, user)
    if not deleted:
        raise ValueError(f"Artifact '{run_id}' not found")
    return {"status": "deleted", "run_id": run_id}


# ---------------------------------------------------------------------------
# Observability tools
# ---------------------------------------------------------------------------


async def get_run(
    run_id: Annotated[str, "Run ID to inspect"],
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Return a full manifest for a run."""
    run_id = await _resolve_run_id(run_id, session_id)
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found")

    meta = artifact.get("metadata", {})
    results = artifact.get("results", {})

    return {
        "run_id": run_id,
        "tool_name": meta.get("tool_name"),
        "analysis_type": meta.get("analysis_type"),
        "timestamp": meta.get("timestamp"),
        "inputs": meta.get("parameters", {}),
        "outputs_summary": {
            k: v for k, v in results.items()
            if not isinstance(v, (dict, list))
        },
    }


async def pin_run(
    run_id: Annotated[str, "Run ID to pin"],
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Pin a cached problem to prevent eviction."""
    session = _sessions.get(session_id)
    pinned = session.pin_run(run_id)
    return {"run_id": run_id, "pinned": pinned}


async def unpin_run(
    run_id: Annotated[str, "Run ID to unpin"],
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Release a pin on a cached problem."""
    session = _sessions.get(session_id)
    released = session.unpin_run(run_id)
    return {"run_id": run_id, "released": released}


async def get_detailed_results(
    run_id: Annotated[str, "Run ID"],
    detail_level: Annotated[str, "'summary' or 'standard'"] = "standard",
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Retrieve detailed results for a past run."""
    run_id = await _resolve_run_id(run_id, session_id)
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found")

    results = artifact.get("results", {})

    if detail_level == "summary":
        return {
            "run_id": run_id,
            "detail_level": "summary",
            "results": {k: v for k, v in results.items() if not isinstance(v, (list, dict))},
        }
    else:
        return {
            "run_id": run_id,
            "detail_level": "standard",
            "results": results,
        }


async def get_last_logs(
    run_id: Annotated[str, "Run ID"],
) -> dict:
    """Retrieve server-side log records for a run."""
    run_id = await _resolve_run_id(run_id)
    logs = get_run_logs(run_id)
    return {"run_id": run_id, "log_count": len(logs or []), "logs": logs or []}
