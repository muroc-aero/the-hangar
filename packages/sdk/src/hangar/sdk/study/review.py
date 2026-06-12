"""Pre-run study review: how many cases, how much compute, how long.

This is the blowup check for both humans and agents: review before run.
The estimate seeds from ``execution.est_case_seconds`` and switches to the
observed mean once cases have completed, so incremental runs (run a few,
review, continue) sharpen the forecast.
"""

from __future__ import annotations

from hangar.sdk.study.expand import StudyCase
from hangar.sdk.study.schema import DEFAULT_REVIEW_THRESHOLD


def _human_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def review_study(
    study: dict,
    cases: list[StudyCase],
    state: dict | None = None,
) -> dict:
    """Summarize the expanded study for human/agent review before running.

    Returns case counts (total / pending / per-runner), the run count with
    multistart variants, a wall-time estimate, warnings, and a preview of
    the first cases. Pass the current store state (if any) so completed
    cases are excluded from the pending estimate and the observed mean
    wall time replaces the spec's seed estimate.
    """
    execution = study.get("execution") or {}
    multistart = study.get("multistart") or {}
    n_presets = max(1, len(multistart.get("presets") or {}))
    workers = execution.get("workers", 1)
    threshold = execution.get("review_threshold", DEFAULT_REVIEW_THRESHOLD)

    state_cases = (state or {}).get("cases", {})
    done_keys = {
        key for key, entry in state_cases.items()
        if entry.get("status") not in (None, "pending", "running")
    }
    pending = [c for c in cases if c.case_key not in done_keys]

    by_runner: dict[str, int] = {}
    for case in cases:
        by_runner[case.runner] = by_runner.get(case.runner, 0) + 1

    # Estimate: observed mean from completed cases beats the spec seed.
    est_case_s = execution.get("est_case_seconds")
    est_source = "spec" if est_case_s else None
    walls = [
        float(e["wall_time_s"]) for e in state_cases.values()
        if e.get("wall_time_s")
    ]
    if walls:
        est_case_s = sum(walls) / len(walls)
        est_source = f"observed mean of {len(walls)} completed case(s)"

    n_runs_pending = len(pending) * n_presets
    est_wall_s = (n_runs_pending * est_case_s / max(1, workers)) if est_case_s else None

    warnings: list[str] = []
    if len(pending) > threshold:
        warnings.append(
            f"{len(pending)} pending cases exceed review_threshold={threshold}: "
            "run() requires confirm=True or an explicit max_cases batch")
    if est_case_s is None:
        warnings.append(
            "no est_case_seconds in execution and no completed cases yet; "
            "wall-time estimate unavailable -- consider a small max_cases "
            "pilot batch first")
    if n_presets > 1:
        warnings.append(
            f"multistart runs {n_presets} variants per case "
            f"({n_runs_pending} runs for {len(pending)} pending cases)")

    axes_summary = []
    for block in study.get("cases") or []:
        kind, body = next(iter(block.items()))
        if kind == "matrix":
            axes_summary.append({
                name: len(_axis_size(axis))
                for name, axis in (body.get("axes") or {}).items()
            })

    return {
        "study_id": (study.get("metadata") or {}).get("id"),
        "n_cases": len(cases),
        "n_pending": len(pending),
        "n_done": len(cases) - len(pending),
        "by_runner": by_runner,
        "n_presets": n_presets,
        "n_runs_pending": n_runs_pending,
        "workers": workers,
        "est_case_seconds": est_case_s,
        "est_source": est_source,
        "est_wall_seconds": est_wall_s,
        "est_wall_human": _human_duration(est_wall_s),
        "review_threshold": threshold,
        "warnings": warnings,
        "matrix_axes": axes_summary,
        "case_preview": [
            {"case_id": c.case_id, "runner": c.runner, "params": c.params,
             "source": c.source}
            for c in cases[:10]
        ],
    }


def _axis_size(axis: dict) -> list:
    from hangar.sdk.study.expand import _axis_values

    return _axis_values(axis)
