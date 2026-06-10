"""Session, provenance, artifact, and observability tools for OCP.

Adapts the OAS session tools to use the OCP session manager.
Provenance tools (start_session, log_decision, export_session_graph) are
shared across all hangar tool servers.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from hangar.sdk.auth import get_current_user
from hangar.sdk.helpers import _get_viewer_base_url, _resolve_run_id
from hangar.sdk.telemetry import get_run_logs
from hangar.sdk.provenance.middleware import _get_session_id
from hangar.sdk.provenance.db import (
    record_requirements,
    update_session_project,
)

from hangar.ocp.state import sessions as _sessions, artifacts as _artifacts


# ---------------------------------------------------------------------------
# Provenance tools
# ---------------------------------------------------------------------------


from hangar.sdk.provenance.tools import build_provenance_tools

# The four shared provenance tools, bound to this package's session manager.
_prov = build_provenance_tools(_sessions)
start_session = _prov.start_session
log_decision = _prov.log_decision
link_cross_tool_result = _prov.link_cross_tool_result
export_session_graph = _prov.export_session_graph


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
    try:
        record_requirements(_get_session_id(), requirements)
    except Exception:
        pass  # Best-effort; provenance DB may not be initialised
    return {
        "session_id": session_id,
        "requirements_set": len(requirements),
        "requirements": requirements,
    }


async def record_conclusion(
    run_id: Annotated[str, "Run ID of the chosen run that answers the study"],
    narrative: Annotated[
        str,
        "Short engineering summary of what this run means for the requirements",
    ] = "",
    session_id: Annotated[str | None, "Session hint for faster artifact lookup"] = None,
) -> dict:
    """Conclude a study: record what a chosen run means for the requirements.

    Call this at the end of a workflow once a run answers the question. The
    per-requirement verdicts are *auto-derived* by evaluating the session's
    persisted requirements (set via set_requirements / configure_session)
    against this run's results, so they cannot drift from the numbers. You supply
    only the chosen run and a short narrative.

    Writes a ``conclusion`` provenance record that flips the Concluding stage in
    the range-safety dashboard to populated. Returns
    ``{conclusion_id, run_id, verdict, narrative, metrics, requirements}`` where
    ``verdict`` is the overall ``meets`` / ``fails`` / ``partial`` / ``open``.
    """
    from hangar.sdk.provenance.conclusion import record_conclusion as _record

    run_id = await _resolve_run_id(run_id, session_id)
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found in artifact store.")

    results = artifact.get("results") or {}
    sid = (artifact.get("metadata") or {}).get("session_id") or _get_session_id()

    return await asyncio.to_thread(_record, sid, run_id, results, narrative)


# ---------------------------------------------------------------------------
# Artifact tools
# ---------------------------------------------------------------------------


async def list_artifacts(
    session_id: Annotated[str | None, "Filter by session ID"] = None,
    analysis_type: Annotated[str | None, "Filter by type: 'mission', 'optimization', 'sweep'"] = None,
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


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


async def visualize(
    run_id: Annotated[str, "Run ID to visualize"],
    plot_type: Annotated[
        str,
        "Plot type -- one of: mission_profile, takeoff_profile, weight_breakdown, "
        "performance_summary, energy_budget, sweep_chart, optimization_history",
    ],
    session_id: Annotated[str | None, "Session hint for faster artifact lookup"] = None,
    case_name: Annotated[str, "Human-readable label for the plot title"] = "",
    output: Annotated[
        str | None,
        "Override visualization output mode: "
        "'inline' = PNG image (default for claude.ai), "
        "'file' = save PNG to disk only, "
        "'url' = return dashboard URL. "
        "When None, uses session default.",
    ] = None,
) -> list:
    """Generate a visualization plot for an OpenConcept analysis run.

    Available plot types:
      mission_profile       -- 2x3 grid: altitude, V/S, TAS, throttle, fuel, battery SOC
      takeoff_profile       -- 1x3 grid: altitude, airspeed, throttle for takeoff phases
      weight_breakdown      -- horizontal bar chart of MTOW components
      performance_summary   -- table card with all key mission metrics
      energy_budget         -- dual-axis battery SOC + fuel used vs range (hybrid only)
      sweep_chart           -- metrics vs swept parameter (after run_parameter_sweep)
      optimization_history  -- objective summary + DV values (after run_optimization)

    Output modes (set per-call via 'output', or per-session via configure_session):
      inline  -- returns [metadata, ImageContent] (default, best for claude.ai)
      file    -- saves PNG to disk, returns [metadata] with file_path
      url     -- returns [metadata] with dashboard_url and plot_url

    Scoped to the authenticated user.
    """
    from hangar.ocp.viz.plotting import OCP_PLOT_TYPES, generate_ocp_plot

    if plot_type not in OCP_PLOT_TYPES:
        raise ValueError(
            f"Unknown plot_type {plot_type!r}. "
            f"Supported: {sorted(OCP_PLOT_TYPES)}"
        )

    if output is not None and output not in ("inline", "file", "url"):
        raise ValueError(
            f"Unknown output mode {output!r}. Use 'inline', 'file', or 'url'."
        )

    run_id = await _resolve_run_id(run_id, session_id)
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found.")

    # Resolve effective output mode
    artifact_meta = artifact.get("metadata", {})
    sid = artifact_meta.get("session_id", session_id or "default")
    session = _sessions.get(sid)
    effective_output = output or session.defaults.visualization_output

    # Compute save_dir
    _user = artifact_meta.get("user", user)
    _project = artifact_meta.get("project", "default")
    save_dir = str(_artifacts._data_dir / _user / _project / sid)

    results = artifact.get("results", {})

    plot_result = await asyncio.to_thread(
        generate_ocp_plot, plot_type, run_id, results, case_name, save_dir,
    )

    if effective_output == "file":
        return [plot_result.metadata]
    elif effective_output == "url":
        base_url = _get_viewer_base_url()
        if base_url:
            plot_result.metadata["dashboard_url"] = (
                f"{base_url}/dashboard?run_id={run_id}"
            )
            plot_result.metadata["plot_url"] = (
                f"{base_url}/plot?run_id={run_id}&plot_type={plot_type}"
            )
        return [plot_result.metadata]
    else:
        # Inline mode (default): metadata + ImageContent
        return [plot_result.metadata, plot_result.image]
