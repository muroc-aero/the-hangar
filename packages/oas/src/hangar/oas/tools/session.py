"""Session, provenance, artifact, and observability tools.

Migrated from:
  - OpenAeroStruct/oas_mcp/tools/session_tools.py
  - OpenAeroStruct/oas_mcp/tools/artifacts.py
  - OpenAeroStruct/oas_mcp/tools/observability.py
  - OpenAeroStruct/oas_mcp/provenance/tools.py
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import numpy as np

from hangar.sdk.auth import get_current_user
from hangar.sdk.helpers import _get_viewer_base_url, _resolve_run_id, _suppress_output
from hangar.sdk.state import artifacts as _artifacts, sessions as _sessions
from hangar.sdk.telemetry import get_run_logs
from hangar.sdk.viz.plotting import PLOT_TYPES, generate_n2, generate_plot
from hangar.sdk.viz.widget import extract_plot_data
from hangar.sdk.provenance.middleware import _get_session_id, _prov_session_id, set_server_session_id
from hangar.sdk.provenance.db import (
    _dumps,
    _next_seq,
    get_session_graph,
    list_sessions,
    record_cross_reference,
    record_decision,
    record_session,
    session_exists,
    update_session_project,
)

from hangar.oas.validators import validate_safe_name


# ---------------------------------------------------------------------------
# Provenance tools
# ---------------------------------------------------------------------------
# start_session, log_decision, export_session_graph


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

    Returns ``{session_id, started_at, joined}``.  Call this at the beginning of a
    workflow to group all subsequent tool calls under a named session.

    Pass an existing ``session_id`` to join a session created by another tool
    server (e.g., for cross-tool workflows where OAS and OCP share provenance).
    """
    joined = False
    if session_id is not None and session_exists(session_id):
        joined = True
    elif session_id is None:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"

    started_at = datetime.now(timezone.utc).isoformat()
    if not joined:
        record_session(session_id, notes=notes, user=get_current_user())
    # Set module-level var so all subsequent tool calls (separate asyncio tasks)
    # are recorded under this session.
    set_server_session_id(session_id)
    # Also set ContextVar for test isolation (has priority over module-level).
    _prov_session_id.set(session_id)
    return {"session_id": session_id, "started_at": started_at, "joined": joined}


async def log_decision(
    decision_type: Annotated[
        str,
        "Category of decision (e.g. 'dv_selection', 'mesh_resolution', 'constraint_choice', 'result_interpretation')",
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

    Use this before major steps (choosing design variables, setting mesh
    resolution, interpreting unexpected results) to create an audit trail.
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
    where *graph_path* is the auto-generated file in the artifact directory.
    Load the JSON into the provenance viewer to visualise the DAG.
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
# reset, configure_session, set_requirements


async def reset(
    session_id: Annotated[str | None, "Session to reset, or None to reset all sessions"] = None,
) -> dict:
    """Reset sessions and cached OpenMDAO problems.

    Before clearing, the provenance graph is flushed to disk for each
    active session so that a complete record is preserved.

    If session_id is provided, only that session is cleared.  If None, all
    sessions are cleared.
    """
    from hangar.sdk.provenance.flush import flush_session_graph

    user = get_current_user()

    if session_id is None:
        # Flush the current session before clearing all
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
    default_detail_level: Annotated[
        str | None,
        "Default detail level for get_detailed_results: 'summary' | 'standard'",
    ] = None,
    validation_severity_threshold: Annotated[
        str | None,
        "Minimum severity to include in validation block: 'error' | 'warning' | 'info'",
    ] = None,
    auto_visualize: Annotated[
        list[str] | None,
        "Plot types to auto-generate after each analysis (empty list = none). "
        "E.g. ['lift_distribution', 'drag_polar']",
    ] = None,
    telemetry_mode: Annotated[
        str | None,
        "Override telemetry mode for this session: 'off' | 'logging' | 'otel'",
    ] = None,
    requirements: Annotated[
        list[dict] | None,
        "Set requirements checked against every analysis result. "
        "Each requirement: {path, operator, value, label}. "
        "Operators: ==, !=, <, <=, >, >=. "
        "Example: [{\"path\": \"CL\", \"operator\": \">=\", \"value\": 0.4, \"label\": \"min_CL\"}]",
    ] = None,
    project: Annotated[
        str | None,
        "Project name for organising artifacts under {OAS_DATA_DIR}/{user}/{project}/",
    ] = None,
    visualization_output: Annotated[
        str | None,
        "Default output mode for visualize(): "
        "'inline' = PNG image (default, best for claude.ai), "
        "'file' = save PNG to disk only (no [image] noise in CLI), "
        "'url' = return dashboard/plot URLs (best for remote/VPS CLI)",
    ] = None,
    retention_max_count: Annotated[
        int | None,
        "Maximum number of artifacts to keep per session. "
        "Oldest artifacts are automatically deleted after each analysis when exceeded. "
        "None = unlimited (default).",
    ] = None,
) -> dict:
    """Configure per-session defaults to reduce repeated arguments.

    Settings persist until reset() is called or the server restarts.

    Parameters
    ----------
    default_detail_level:
        Default detail level when get_detailed_results is called.
    validation_severity_threshold:
        Filter validation findings below this severity from responses.
        'error' = show only errors; 'warning' = show errors+warnings; 'info' = show all.
    auto_visualize:
        List of plot_type values to auto-generate after each analysis.
        Plots are returned in the 'auto_plots' key of the response envelope.
    telemetry_mode:
        Override the server-wide OAS_TELEMETRY_MODE for this session.
    requirements:
        Dot-path requirements checked after every analysis in this session.
        Failed requirements appear as "error" findings in the validation block.
    visualization_output:
        Default output mode for all visualize() calls in this session.
        'inline' = return metadata + ImageContent (default, for claude.ai).
        'file' = save PNG to disk, return metadata with file_path (CLI-friendly).
        'url' = return metadata with dashboard_url and plot_url (for VPS CLI).
    """
    session = _sessions.get(session_id)

    updates: dict = {}
    if default_detail_level is not None:
        if default_detail_level not in ("summary", "standard"):
            raise ValueError("default_detail_level must be 'summary' or 'standard'")
        updates["default_detail_level"] = default_detail_level

    if validation_severity_threshold is not None:
        if validation_severity_threshold not in ("error", "warning", "info"):
            raise ValueError("validation_severity_threshold must be 'error', 'warning', or 'info'")
        updates["validation_severity_threshold"] = validation_severity_threshold

    if auto_visualize is not None:
        unknown = [p for p in auto_visualize if p not in PLOT_TYPES]
        if unknown:
            raise ValueError(
                f"Unknown plot type(s) in auto_visualize: {unknown}. "
                f"Supported: {sorted(PLOT_TYPES)}"
            )
        updates["auto_visualize"] = auto_visualize

    if telemetry_mode is not None:
        if telemetry_mode not in ("off", "logging", "otel"):
            raise ValueError("telemetry_mode must be 'off', 'logging', or 'otel'")
        updates["telemetry_mode"] = telemetry_mode

    if project is not None:
        validate_safe_name(project, "project")
        updates["project"] = project

    if visualization_output is not None:
        if visualization_output not in ("inline", "file", "url"):
            raise ValueError(
                "visualization_output must be 'inline', 'file', or 'url'"
            )
        updates["visualization_output"] = visualization_output

    if retention_max_count is not None:
        if retention_max_count < 1:
            raise ValueError("retention_max_count must be >= 1")
        updates["retention_max_count"] = retention_max_count

    if updates:
        session.configure(**updates)

    # Sync project to provenance DB so flush_session_graph can resolve it.
    if project is not None:
        try:
            prov_sid = _get_session_id()
            update_session_project(prov_sid, project)
        except Exception:
            pass  # Best-effort; provenance DB may not be initialised

    if requirements is not None:
        session.set_requirements(requirements)

    return {
        "session_id": session_id,
        "project": session.project,
        "status": "configured",
        "current_defaults": session.defaults.to_dict(),
        "requirements_count": len(session.requirements),
    }


async def set_requirements(
    requirements: Annotated[
        list[dict],
        "List of requirement dicts: {path, operator, value, label}. "
        "Operators: ==, !=, <, <=, >, >=. "
        "Example: [{\"path\": \"surfaces.wing.failure\", \"operator\": \"<\", \"value\": 1.0}]",
    ],
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Set requirements that are automatically checked against every analysis result.

    Requirements use dot-path notation to access nested result values and
    compare them using standard operators.  Failed requirements appear as
    'error' severity findings in the validation block of each response.

    Example requirements:
      {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"}
      {"path": "surfaces.wing.failure", "operator": "<", "value": 1.0, "label": "no_failure"}
      {"path": "L_over_D", "operator": ">", "value": 10.0, "label": "min_LD"}
    """
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
# list_artifacts, get_artifact, get_artifact_summary, delete_artifact


async def list_artifacts(
    session_id: Annotated[str | None, "Filter by session ID, or None to list all sessions"] = None,
    analysis_type: Annotated[
        str | None,
        "Filter by type: 'aero', 'aerostruct', 'drag_polar', 'stability', 'optimization'",
    ] = None,
    project: Annotated[str | None, "Filter by project name (default: all projects)"] = None,
) -> dict:
    """List saved analysis artifacts with optional filters.

    Returns a count and a list of index entries (run_id, session_id,
    analysis_type, timestamp, surfaces, tool_name).  Does not load the
    full results payload --- use get_artifact for that.

    Results are scoped to the authenticated user --- you cannot list other users' artifacts.
    """
    user = get_current_user()
    entries = await asyncio.to_thread(_artifacts.list, session_id, analysis_type, user, project)
    return {"count": len(entries), "artifacts": entries}


async def get_artifact(
    run_id: Annotated[str, "Run ID returned by an analysis tool"],
    session_id: Annotated[
        str | None, "Session that owns this artifact --- speeds up lookup when provided"
    ] = None,
) -> dict:
    """Retrieve a saved artifact (metadata + full results) by run_id.

    Scoped to the authenticated user --- you cannot access other users' artifacts.
    """
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Artifact '{run_id}' not found")
    return artifact


async def get_artifact_summary(
    run_id: Annotated[str, "Run ID returned by an analysis tool"],
    session_id: Annotated[str | None, "Session that owns this artifact"] = None,
) -> dict:
    """Retrieve artifact metadata only (no results payload) --- much smaller response.

    Returns: run_id, session_id, analysis_type, timestamp, surfaces,
    tool_name, parameters.

    Scoped to the authenticated user.
    """
    user = get_current_user()
    summary = await asyncio.to_thread(_artifacts.get_summary, run_id, session_id, user)
    if summary is None:
        raise ValueError(f"Artifact '{run_id}' not found")
    return summary


async def delete_artifact(
    run_id: Annotated[str, "Run ID to delete"],
    session_id: Annotated[str | None, "Session that owns this artifact"] = None,
) -> dict:
    """Permanently delete a saved artifact from disk.

    Scoped to the authenticated user --- you cannot delete other users' artifacts.
    """
    user = get_current_user()
    deleted = await asyncio.to_thread(_artifacts.delete, run_id, session_id, user)
    if not deleted:
        raise ValueError(f"Artifact '{run_id}' not found")
    return {"status": "deleted", "run_id": run_id}


# ---------------------------------------------------------------------------
# Observability tools
# ---------------------------------------------------------------------------
# get_run, pin_run, unpin_run, get_detailed_results, visualize, get_n2_html, get_last_logs


async def get_run(
    run_id: Annotated[str, "Run ID to inspect"],
    session_id: Annotated[str | None, "Session hint for faster lookup"] = None,
) -> dict:
    """Return a full manifest for a run: inputs, outputs, validation, cache state.

    This is the primary 'what do I know about this run?' endpoint for agents.
    It answers: what inputs were used, what came out, did it pass validation,
    is the problem still cached, and what plot types are available.

    Scoped to the authenticated user.
    """
    run_id = await _resolve_run_id(run_id, session_id)
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found in artifact store.")

    meta = artifact.get("metadata", {})
    results = artifact.get("results", {})
    sid = meta.get("session_id", session_id or "default")
    session = _sessions.get(sid)

    # Cache status
    surface_names = meta.get("surfaces", [])
    analysis_type = meta.get("analysis_type", "aero")
    cache_info = session.cache_status(surface_names, analysis_type)
    cache_info["pinned"] = session.is_pinned(run_id)

    # Determine which detail levels are available
    has_standard = bool(results.get("standard_detail"))
    has_mesh = bool(session.get_mesh_snapshot(run_id))

    # Plot types available given what's stored
    if analysis_type == "drag_polar":
        available_plots = ["drag_polar"]
    elif analysis_type == "optimization":
        available_plots = ["lift_distribution", "opt_history"]
        final_r = results.get("final_results", {})
        if "fuelburn" in final_r or "structural_mass" in final_r:
            available_plots.append("stress_distribution")
        opt_hist = results.get("optimization_history", {})
        if opt_hist.get("initial_dvs") or opt_hist.get("dv_history"):
            available_plots.extend(["opt_dv_evolution", "opt_comparison"])
        if has_mesh or has_standard:
            available_plots.append("planform")
    else:
        available_plots = ["lift_distribution"]
        if analysis_type == "aerostruct":
            available_plots.append("stress_distribution")
        if has_mesh or has_standard:
            available_plots.append("planform")
    conv = session.get_convergence(run_id)
    if not conv:
        conv = results.get("convergence") or artifact.get("convergence")
    if conv:
        available_plots.append("convergence")

    return {
        "run_id": run_id,
        "tool_name": meta.get("tool_name"),
        "analysis_type": analysis_type,
        "timestamp": meta.get("timestamp"),
        "user": meta.get("user"),
        "project": meta.get("project"),
        "name": meta.get("name"),
        "surfaces": surface_names,
        "inputs": meta.get("parameters", {}),
        "outputs_summary": {
            k: v for k, v in results.items()
            if k not in ("standard_detail", "convergence") and not isinstance(v, (list, dict))
        },
        "cache_state": cache_info,
        "detail_levels_available": {
            "summary": True,
            "standard": has_standard,
        },
        "available_plots": available_plots,
    }


async def pin_run(
    run_id: Annotated[str, "Run ID whose cached problem to pin"],
    surfaces: Annotated[list[str], "Surface names used in this run"],
    analysis_type: Annotated[str, "Analysis type: 'aero' or 'aerostruct'"] = "aero",
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Pin a cached OpenMDAO problem so it won't be evicted during multi-step workflows.

    Use this after an analysis run when you plan to call get_detailed_results()
    or visualize() later --- it guarantees the live problem stays in memory.
    Call unpin_run() when done to release memory.
    """
    session = _sessions.get(session_id)
    pinned = session.pin_run(run_id, surfaces, analysis_type)
    return {
        "run_id": run_id,
        "pinned": pinned,
        "message": (
            f"Run '{run_id}' pinned --- cached problem will not be evicted."
            if pinned
            else f"No cached problem found for run '{run_id}' (surfaces={surfaces}, type={analysis_type})."
        ),
    }


async def unpin_run(
    run_id: Annotated[str, "Run ID to unpin"],
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Release a pin on a cached OpenMDAO problem, allowing it to be evicted."""
    session = _sessions.get(session_id)
    released = session.unpin_run(run_id)
    return {
        "run_id": run_id,
        "released": released,
        "message": (
            f"Pin for run '{run_id}' released."
            if released
            else f"No pin found for run '{run_id}'."
        ),
    }


async def get_detailed_results(
    run_id: Annotated[str, "Run ID to retrieve details for"],
    detail_level: Annotated[
        str,
        "Detail level: 'standard' = sectional Cl, stress, mesh (persisted); "
        "'summary' = just the top-level results dict",
    ] = "standard",
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Retrieve detailed results for a past run.

    'standard' detail includes spanwise sectional Cl, von Mises stress
    distributions, and mesh coordinates --- captured at run time and
    persisted in the artifact so they survive cache eviction.

    'summary' returns only the top-level scalars (CL, CD, etc.).

    Scoped to the authenticated user.
    """
    run_id = await _resolve_run_id(run_id, session_id)
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found.")

    results = artifact.get("results", {})

    if detail_level == "summary":
        return {
            "run_id": run_id,
            "detail_level": "summary",
            "results": {
                k: v for k, v in results.items()
                if not isinstance(v, (list, dict)) or k in ("surfaces",)
            },
        }
    elif detail_level == "standard":
        standard = results.get("standard_detail", {})
        return {
            "run_id": run_id,
            "detail_level": "standard",
            "sectional_data": standard.get("sectional_data", {}),
            "mesh_snapshot": standard.get("mesh_snapshot", {}),
        }
    else:
        raise ValueError(
            f"Unknown detail_level {detail_level!r}. Use 'summary' or 'standard'."
        )


async def visualize(
    run_id: Annotated[str, "Run ID to visualize"],
    plot_type: Annotated[
        str,
        "Plot type --- one of: lift_distribution, drag_polar, stress_distribution, "
        "convergence, planform, opt_history, opt_dv_evolution, opt_comparison, n2, "
        "deflection_profile, weight_breakdown, failure_heatmap, twist_chord_overlay, "
        "mesh_3d, multipoint_comparison",
    ],
    session_id: Annotated[str | None, "Session hint for faster artifact lookup"] = None,
    case_name: Annotated[str, "Human-readable label for the plot title"] = "",
    output: Annotated[
        str | None,
        "Override visualization output mode for this call: "
        "'inline' = PNG image (default for claude.ai), "
        "'file' = save PNG to disk only (no [image] noise in CLI), "
        "'url' = return dashboard URL (best for remote/VPS CLI). "
        "When None, uses session default (set via configure_session).",
    ] = None,
) -> list:
    """Generate a visualisation plot and return a base64-encoded PNG (or HTML for n2).

    Response includes:
      plot_type, run_id, format, width_px, height_px, image_hash, image_base64

    Use image_hash for client-side caching --- if the hash matches a cached image,
    there is no need to re-render.

    Available plot types:
      lift_distribution       --- spanwise Cl bar chart or per-surface CL
      drag_polar              --- CL vs CD and L/D vs alpha (requires drag polar run)
      stress_distribution     --- spanwise von Mises stress and failure index
      convergence             --- solver residual history (if captured)
      planform                --- wing planform top view with optional deflection overlay
      opt_history             --- optimizer objective convergence (optimization runs only)
      opt_dv_evolution        --- design variable evolution over iterations (optimization only)
      opt_comparison          --- before/after DV comparison: initial vs optimized values
      n2                      --- interactive N2/DSM diagram (saves HTML to disk)
      deflection_profile      --- spanwise vertical deflection (aerostruct only)
      weight_breakdown        --- structural mass components bar chart (aerostruct only)
      failure_heatmap         --- failure index colour map over planform (aerostruct only)
      twist_chord_overlay     --- twist and chord profiles vs span
      mesh_3d                 --- 3D wireframe mesh with optional deflection overlay
      multipoint_comparison   --- side-by-side cruise vs maneuver results

    Output modes (set per-call via 'output' param, or per-session via configure_session):
      inline  --- returns [metadata, ImageContent] (default, best for claude.ai)
      file    --- saves PNG to disk, returns [metadata] with file_path (no [image] noise in CLI)
      url     --- returns [metadata] with dashboard_url and plot_url (clickable links for CLI)

    Scoped to the authenticated user.
    """
    if plot_type not in PLOT_TYPES:
        raise ValueError(
            f"Unknown plot_type {plot_type!r}. "
            f"Supported: {sorted(PLOT_TYPES)}"
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

    # Resolve effective output mode: per-call override > session default
    artifact_meta = artifact.get("metadata", {})
    sid = artifact_meta.get("session_id", session_id or "default")
    session = _sessions.get(sid)
    effective_output = output or session.defaults.visualization_output

    # Compute save_dir --- always save when mode is "file" or "url", also for "inline"
    _user = artifact_meta.get("user", user)
    _project = artifact_meta.get("project", "default")
    save_dir = str(_artifacts._data_dir / _user / _project / sid)

    # N2 diagram --- needs a live OpenMDAO Problem, not artifact data
    if plot_type == "n2":
        analysis_type = artifact_meta.get("analysis_type", "aero")
        surfaces = artifact_meta.get("surfaces", [])

        # Optimization runs wrap an underlying aero or aerostruct analysis
        if analysis_type == "optimization":
            analysis_type = artifact.get("results", {}).get("analysis_type", "aero")

        prob = session.get_cached_problem(surfaces, analysis_type) if session else None
        if prob is None:
            # Attempt rebuild from persisted surface dicts
            from hangar.oas.builders import rebuild_problem_for_n2

            persisted_surface_dicts = artifact.get("results", {}).get("_surface_dicts")
            if persisted_surface_dicts is None:
                raise ValueError(
                    f"No cached OpenMDAO Problem for run '{run_id}' and this "
                    "artifact was saved before surface-dict persistence was added. "
                    "Re-run the analysis, then call visualize again."
                )
            parameters = artifact_meta.get("parameters", {})
            prob = await asyncio.to_thread(
                _suppress_output,
                rebuild_problem_for_n2,
                persisted_surface_dicts,
                analysis_type,
                parameters,
            )
        output_dir = _artifacts._data_dir / _user / _project / sid
        n2_result = await asyncio.to_thread(generate_n2, prob, run_id, case_name, output_dir)
        return [n2_result.metadata]

    results = artifact.get("results", {})
    artifact_type = artifact_meta.get("analysis_type", "")

    # For optimization runs, the aerodynamic results live inside `final_results`.
    # Merge them into plot_results so lift_distribution / stress_distribution work.
    if artifact_type == "optimization":
        final_r = results.get("final_results", {})
        plot_results = dict(final_r)
    else:
        plot_results = dict(results)

    standard = results.get("standard_detail", {})

    # For planform, prefer session-stored mesh snapshot (faster), fall back to artifact
    mesh_snap = session.get_mesh_snapshot(run_id) or standard.get("mesh_snapshot", {})
    mesh_data = {"mesh_snapshot": mesh_snap} if mesh_snap else {}
    # Provide a mesh array from the first surface snapshot.
    # Prefer the full mesh (for mesh_3d); fall back to LE/TE (for planform).
    for surf_name, surf_mesh in mesh_snap.items():
        full_mesh = surf_mesh.get("mesh")
        if full_mesh is not None:
            mesh_data["mesh"] = full_mesh
        else:
            le = surf_mesh.get("leading_edge")
            te = surf_mesh.get("trailing_edge")
            if le and te:
                mesh_data["mesh"] = np.array([le, te]).tolist()
        # Also pass def_mesh if available in mesh_snapshot
        def_mesh = surf_mesh.get("def_mesh")
        if def_mesh is not None:
            mesh_data["def_mesh"] = def_mesh
        # Pass structural FEM data for mesh_3d tube/wingbox rendering
        for struct_key in ("radius", "thickness", "fem_origin", "fem_model_type",
                           "spar_thickness", "skin_thickness"):
            if struct_key in surf_mesh:
                mesh_data[struct_key] = surf_mesh[struct_key]
        break

    conv_data = session.get_convergence(run_id)
    if not conv_data:
        conv_data = results.get("convergence") or artifact.get("convergence") or {}

    # Inject sectional_data into results for lift_distribution / stress plots
    if standard.get("sectional_data"):
        # Merge sectional_data into per-surface dicts
        for surf_name, sect in standard["sectional_data"].items():
            if surf_name in plot_results.get("surfaces", {}):
                plot_results["surfaces"][surf_name]["sectional_data"] = sect
        plot_results["sectional_data"] = standard.get("sectional_data", {})

    # Build optimization_history for opt_* plot types
    opt_history: dict | None = None
    if artifact_type == "optimization" or plot_type.startswith("opt_"):
        raw_hist = results.get("optimization_history", {})
        opt_history = {
            **raw_hist,
            # Expose final DVs alongside initial for opt_comparison
            "final_dvs": results.get("optimized_design_variables", {}),
        }

    plot_result = await asyncio.to_thread(
        generate_plot,
        plot_type, run_id, plot_results, conv_data, mesh_data, case_name, opt_history,
        save_dir,
    )
    # Attach structured plot data so MCP Apps widget can render interactive Plotly charts.
    # Text/image clients (Claude) are unaffected --- they use the PNG image as before.
    plot_result.metadata["plot_data"] = extract_plot_data(
        plot_type, plot_results, conv_data, mesh_data, opt_history
    )

    # Branch return based on output mode
    if effective_output == "file":
        # File mode: metadata only (PNG already saved to disk), no ImageContent noise
        return [plot_result.metadata]
    elif effective_output == "url":
        # URL mode: add dashboard and plot URLs for clickable access in CLI
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
        # Inline mode (default): metadata + ImageContent for claude.ai
        return [plot_result.metadata, plot_result.image]


async def get_n2_html(
    run_id: Annotated[str, "Run ID whose N2 diagram to fetch"],
    session_id: Annotated[str | None, "Session hint for faster artifact lookup"] = None,
) -> list:
    """Fetch the saved N2 HTML file for a run.

    Called on-demand (e.g. by the widget download button) after visualize() has
    already generated the file.  Returns the full HTML as TextContent so the
    caller can save or display it.

    Raises ValueError if the artifact is not found or the N2 file has not been
    generated yet (call visualize(run_id, 'n2') first).
    """
    from mcp.types import TextContent

    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id)
    if artifact is None:
        raise ValueError(f"Run '{run_id}' not found.")

    artifact_meta = artifact.get("metadata", {})
    user = artifact_meta.get("user", get_current_user())
    project = artifact_meta.get("project", "default")
    sid = artifact_meta.get("session_id", session_id or "default")

    n2_path = _artifacts._data_dir / user / project / sid / f"n2_{run_id}.html"
    if not n2_path.exists():
        raise ValueError(
            f"N2 HTML file not found at {n2_path}. "
            "Call visualize(run_id, 'n2') first to generate it."
        )
    html = n2_path.read_text(encoding="utf-8")
    return [TextContent(type="text", text=html)]


async def get_last_logs(
    run_id: Annotated[str, "Run ID to retrieve server-side logs for"],
) -> dict:
    """Retrieve server-side log records captured during a run.

    Agents cannot access server stderr, so this exposes recent log lines
    through MCP for debugging convergence issues, unexpected outputs, etc.

    Returns a list of log records with time, level, message, and logger name.
    Returns empty list if no logs were captured for this run_id.
    """
    run_id = await _resolve_run_id(run_id)
    logs = get_run_logs(run_id)
    if logs is None:
        logs = []
    return {
        "run_id": run_id,
        "log_count": len(logs),
        "logs": logs,
    }
