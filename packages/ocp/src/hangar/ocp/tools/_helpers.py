"""OCP-specific tool helpers: finalization, auto-plots."""

from __future__ import annotations

import asyncio
import time

from hangar.sdk.artifacts.store import _make_run_id  # noqa: F401 -- re-export
from hangar.sdk.auth import get_current_user
from hangar.sdk.envelope.response import make_envelope
from hangar.sdk.validation.requirements import requirements_findings
from hangar.sdk.telemetry import make_telemetry

from hangar.ocp.state import artifacts as _artifacts
from hangar.ocp.validation import findings_to_dict
from hangar.ocp.summary import summarize_mission, summarize_optimization


_SUMMARIZERS = {
    "mission": lambda r, traj, ctx, prev: summarize_mission(r, traj, ctx, prev),
    "optimization": lambda r, _traj, ctx, _prev: summarize_optimization(r, ctx),
}


async def _finalize_analysis(
    tool_name: str,
    run_id: str,
    session,
    session_id: str,
    analysis_type: str,
    inputs: dict,
    results: dict,
    trajectory: dict | None,
    findings: list,
    t0: float,
    cache_hit: bool,
    run_name: str | None = None,
) -> dict:
    """Shared post-analysis: validate requirements, build telemetry, save artifact, build envelope."""
    # Inject failed requirements as validation findings
    findings.extend(requirements_findings(session.requirements, results))

    validation = findings_to_dict(findings)
    elapsed = time.perf_counter() - t0
    telem = make_telemetry(elapsed, cache_hit, 0, None)

    # Physics summary
    previous_results = session.get_last_results(analysis_type)
    summarize_fn = _SUMMARIZERS.get(analysis_type)
    summary = summarize_fn(results, trajectory, inputs, previous_results) if summarize_fn else None
    session.store_last_results(analysis_type, results)

    # Build results payload for artifact
    results_to_save = dict(results)
    if trajectory:
        results_to_save["trajectory"] = trajectory
    conv_data = session.get_convergence(run_id)
    if conv_data:
        results_to_save["convergence"] = conv_data

    user = get_current_user()
    _artifacts.save(
        session_id=session_id,
        analysis_type=analysis_type,
        tool_name=tool_name,
        surfaces=[],
        parameters=inputs,
        results=results_to_save,
        user=user,
        project=session.project,
        name=run_name,
        validation=validation,
        telemetry=telem,
        run_id=run_id,
    )

    # Auto-prune oldest artifacts if retention limit is configured
    if session.defaults.retention_max_count is not None:
        _artifacts.cleanup(
            user=user,
            project=session.project,
            session_id=session_id,
            max_count=session.defaults.retention_max_count,
            protected_run_ids=set(session._pinned),
        )

    envelope = make_envelope(tool_name, run_id, inputs, results, validation, telem)
    if summary is not None:
        envelope["summary"] = summary

    # Auto-visualize if configured
    await _apply_auto_plots(envelope, session, run_id, results_to_save)

    return envelope


async def _apply_auto_plots(
    envelope: dict,
    session,
    run_id: str,
    results: dict,
) -> None:
    """Generate auto-visualize plots and attach their hashes to the envelope."""
    plot_types = session.defaults.auto_visualize
    if not plot_types:
        return

    from hangar.ocp.viz.plotting import generate_ocp_plot

    auto_plots: dict[str, str | None] = {}
    for plot_type in plot_types:
        try:
            plot_result = await asyncio.to_thread(
                generate_ocp_plot, plot_type, run_id, results, "",
            )
            auto_plots[plot_type] = plot_result.metadata.get("image_hash")
        except Exception:
            pass  # don't let auto-plot errors block analysis results

    if auto_plots:
        envelope["auto_plots"] = auto_plots
