"""Study tools: review, batched execution, progress, and results.

The MCP surface is deliberately incremental: ``run_study`` requires an
explicit ``max_cases`` batch size, so an agent must review first
(``review_study`` reports the case count and compute estimate) and commit
compute in reviewable slices, polling ``get_study_status`` between
batches. Full unattended sweeps stay on the CLI
(``omd-cli study run --yes``).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from hangar.sdk.envelope.response import make_envelope, make_error_envelope
from hangar.sdk.errors import UserInputError
from hangar.sdk.telemetry import make_telemetry

from hangar.omd.tools._helpers import resolve_plan_path, rs_dashboard_base

# One MCP call must stay bounded: a batch may not exceed this many cases.
_MAX_BATCH = 25


def _study_urls(study_id: str) -> dict:
    urls: dict[str, str] = {}
    rs = rs_dashboard_base()
    if rs:
        # The dashboard selects a study by ``plan_id`` (the {source}:{id}
        # study key); ``studyfs:`` routes to the case-table view. (It also
        # accepts ``study`` as a back-compat alias.)
        urls["range_safety_study"] = f"{rs}/?plan_id=studyfs:{study_id}"
    return urls


def _resolve_study_path(study_path: str) -> Path:
    # Same workspace-relative resolution as plan paths, so MCP-only agents
    # can author a study.yaml via write_plan and run it by relative path.
    return resolve_plan_path(study_path)


async def review_study(
    study_path: Annotated[str, "Path to study YAML (workspace-relative or absolute)"],
) -> dict:
    """Review a study before running: case count, compute, wall estimate.

    ALWAYS call this before run_study. Returns ``n_cases``, ``n_pending``,
    matrix axis sizes, multistart run multiplier, the estimated wall time,
    and warnings (including combinatorial-blowup flags). A study whose
    expansion exceeds ``execution.guard_max_cases`` fails here with the
    reason.
    """
    from hangar.sdk.study import StudyStore, expand_cases, load_study, review_study as _review

    path = _resolve_study_path(study_path)
    spec, errors = await asyncio.to_thread(load_study, path)
    if errors:
        return {"valid": False, "errors": errors}
    try:
        cases = await asyncio.to_thread(expand_cases, spec)
    except ValueError as exc:
        return {"valid": False, "errors": [{"path": "cases", "message": str(exc)}]}

    state = None
    try:
        state = StudyStore(spec["metadata"]["id"]).load_state()
    except Exception:
        pass
    review = _review(spec, cases, state=state)
    review["valid"] = True
    review["urls"] = _study_urls(review["study_id"])
    return review


async def run_study(
    study_path: Annotated[str, "Path to study YAML (workspace-relative or absolute)"],
    max_cases: Annotated[
        int,
        "Number of pending cases to run in this batch (1-25). Studies run "
        "incrementally over MCP: run a pilot batch, inspect with "
        "get_study_status / get_study_results, then continue. Completed "
        "cases are checkpointed and skipped on the next call.",
    ],
    workers: Annotated[int | None, "Worker processes (default: execution.workers)"] = None,
    retry_failed: Annotated[bool, "Also re-run previously failed cases"] = False,
) -> dict:
    """Run the next batch of a study's pending cases (checkpointed, resumable).

    Returns an envelope whose results carry the batch outcome
    (ran/succeeded/failed), overall progress, remaining case count, and the
    cases.csv path. Call review_study first to size the batch.
    """
    import hangar.omd.study_runner  # noqa: F401  (registers the omd runner)
    from hangar.sdk.study import run_study as _run_study

    t0 = time.perf_counter()
    if not 1 <= max_cases <= _MAX_BATCH:
        raise UserInputError(
            f"max_cases must be between 1 and {_MAX_BATCH} per MCP batch "
            f"(got {max_cases}); use omd-cli study run for unattended full "
            "sweeps")

    path = _resolve_study_path(study_path)
    inputs = {"study_path": str(path), "max_cases": max_cases,
              "workers": workers, "retry_failed": retry_failed}
    try:
        result = await asyncio.to_thread(
            _run_study, path,
            max_cases=max_cases, workers=workers, retry_failed=retry_failed,
        )
    except ValueError as exc:
        return make_error_envelope(
            "run_study", "USER_INPUT_ERROR", str(exc), inputs=inputs)

    result["urls"] = _study_urls(result["study_id"])
    telem = make_telemetry(time.perf_counter() - t0, False)
    return make_envelope("run_study", result["study_id"], inputs, result, None, telem)


async def get_study_status(
    study_id: Annotated[str, "Study id (metadata.id of the study YAML)"],
) -> dict:
    """Progress for a study: done/total, per-status counts, mean case time.

    Cheap to poll between run_study batches; also linked from the
    range-safety dashboard study view.
    """
    from hangar.sdk.study import StudyStore

    store = StudyStore(study_id)
    if not store.state_path.exists():
        raise UserInputError(
            f"no state for study {study_id!r}; run review_study/run_study "
            "first or check the id")
    summary = await asyncio.to_thread(store.status_summary)
    summary["urls"] = _study_urls(study_id)
    return summary


async def get_study_results(
    study_id: Annotated[str, "Study id (metadata.id of the study YAML)"],
    only_failed: Annotated[bool, "Only failed/errored cases"] = False,
    max_rows: Annotated[int, "Cap on returned case rows"] = 200,
) -> dict:
    """Case table for a study: params, status, run_ref, output columns.

    Each row links its ``run_ref`` back to the underlying run (usable with
    get_results / get_run_summary / generate_plots for omd cases).
    """
    from hangar.sdk.study import StudyStore

    store = StudyStore(study_id)
    if not store.state_path.exists():
        raise UserInputError(f"no state for study {study_id!r}")
    state = await asyncio.to_thread(store.load_state)
    rows = []
    for key, entry in state["cases"].items():
        if not entry.get("in_spec", True):
            continue
        if only_failed and entry.get("status") in ("converged", "completed"):
            continue
        rows.append({
            "case_id": entry["case_id"],
            "case_key": key,
            "runner": entry.get("runner"),
            "params": entry.get("params") or {},
            "status": entry.get("status"),
            "run_ref": entry.get("run_ref"),
            "outputs": entry.get("outputs") or {},
            "wall_time_s": entry.get("wall_time_s"),
            "error": entry.get("error"),
        })
    rows.sort(key=lambda r: r["case_id"])
    truncated = len(rows) > max_rows
    return {
        "study_id": study_id,
        "n_cases": len(rows),
        "truncated": truncated,
        "cases": rows[:max_rows],
        "cases_csv": str(store.csv_path),
        "urls": _study_urls(study_id),
    }
