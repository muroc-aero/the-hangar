"""Session, provenance, artifact, and observability tools.

Mirrors the OAS session tools, adapted for pyCycle.
Most of the implementation is reused from hangar.sdk.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from hangar.sdk.auth import get_current_user
from hangar.sdk.helpers import _get_viewer_base_url, _resolve_run_id
from hangar.pyc.state import artifacts as _artifacts, sessions as _sessions
from hangar.sdk.telemetry import get_run_logs
from hangar.sdk.provenance.middleware import _get_session_id
from hangar.sdk.provenance.db import (
    record_requirements,
    update_session_project,
)


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
    try:
        record_requirements(_get_session_id(), requirements)
    except Exception:
        pass  # Best-effort; provenance DB may not be initialised
    return {"session_id": session_id, "requirements_count": len(requirements)}


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


async def reset(
    session_id: Annotated[str, "Session to reset"] = "default",
) -> dict:
    """Clear all engines and cached state for the session.

    Call between unrelated experiments to start fresh.
    """
    session = _sessions.get(session_id)
    session.clear()
    return {"status": "reset", "session_id": session_id}


# ---------------------------------------------------------------------------
# Artifact management
# ---------------------------------------------------------------------------

async def list_artifacts(
    session_id: Annotated[str | None, "Filter by session"] = None,
    analysis_type: Annotated[str | None, "Filter: 'design', 'off_design', 'sweep'"] = None,
    project: Annotated[str | None, "Filter by project"] = None,
) -> dict:
    """Browse saved analysis runs.

    Results are scoped to the authenticated user --- you cannot list other users' artifacts.
    """
    user = get_current_user()
    items = await asyncio.to_thread(
        _artifacts.list, session_id, analysis_type, user, project,
    )
    return {"count": len(items), "artifacts": items}


async def get_artifact(
    run_id: Annotated[str, "Run ID from a previous analysis"],
    session_id: Annotated[
        str | None, "Session that owns this artifact --- speeds up lookup when provided"
    ] = None,
) -> dict:
    """Retrieve full metadata + results for a past run.

    Scoped to the authenticated user --- you cannot access other users' artifacts.
    """
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
    if artifact is None:
        raise ValueError(f"Artifact '{run_id}' not found")
    return artifact


async def get_artifact_summary(
    run_id: Annotated[str, "Run ID from a previous analysis"],
    session_id: Annotated[str | None, "Session that owns this artifact"] = None,
) -> dict:
    """Retrieve metadata only (lightweight) for a past run.

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
# Observability
# ---------------------------------------------------------------------------

async def get_run(
    run_id: Annotated[str, "Run ID from a previous analysis"],
    session_id: Annotated[str | None, "Session hint (speeds lookup)"] = None,
) -> dict:
    """Full manifest: inputs, outputs, validation, telemetry.

    Scoped to the authenticated user.
    """
    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, session_id, user)
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


async def get_detailed_results(
    run_id: Annotated[str, "Run ID"],
    detail_level: Annotated[str, "'summary' or 'standard'"] = "standard",
    session_id: Annotated[str | None, "Session hint"] = None,
) -> dict:
    """Retrieve detailed results for a past run.

    In 'summary' mode, returns only scalar values (no nested dicts/lists).
    In 'standard' mode, returns the full results including flow_stations,
    components, and performance data.
    """
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
    logs = get_run_logs(run_id)
    return {"run_id": run_id, "logs": logs}


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

async def visualize(
    run_id: Annotated[str, "Run ID to visualize"],
    plot_type: Annotated[
        str,
        "Plot type -- one of: station_properties, ts_diagram, performance_summary, "
        "component_bars, design_vs_offdesign",
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
    """Generate a visualization plot for a pyCycle analysis run.

    Available plot types:
      station_properties    -- 2x2 grid of Pt, Tt, Mach, mass flow through the engine
      ts_diagram            -- T-s diagram of the Brayton cycle
      performance_summary   -- table card with all key engine metrics
      component_bars        -- bar chart comparing component PR, efficiency, power
      design_vs_offdesign   -- paired bars comparing design and off-design performance
                               (requires an off-design artifact)

    Output modes (set per-call via 'output', or per-session via configure_session):
      inline  -- returns [metadata, ImageContent] (default, best for claude.ai)
      file    -- saves PNG to disk, returns [metadata] with file_path
      url     -- returns [metadata] with dashboard_url and plot_url

    Scoped to the authenticated user.
    """
    from hangar.pyc.viz.plotting import PYC_PLOT_TYPES, generate_pyc_plot

    if plot_type not in PYC_PLOT_TYPES:
        raise ValueError(
            f"Unknown plot_type {plot_type!r}. "
            f"Supported: {sorted(PYC_PLOT_TYPES)}"
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
        generate_pyc_plot, plot_type, run_id, results, case_name, save_dir,
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
