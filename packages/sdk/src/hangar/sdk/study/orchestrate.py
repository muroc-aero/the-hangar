"""Runner registry and the study orchestration loop.

A runner is a callable ``run_case(spec, ctx) -> dict`` returning at least
``{"status": str, "run_ref": str|None, "outputs": dict, "error": str|None}``.
Status values "converged" and "completed" count as success. ``ctx`` carries
``study_id``, ``case_id``, ``case_key``, ``artifact_dir``, the study's
``outputs`` column declarations, and (under multistart) the active
``preset`` payload.

Orchestration is deliberately checkpoint-first: every case completion is
written to the study store before the next result is processed, so a crash
or interrupt loses at most in-flight cases, and ``max_cases`` runs a pilot
batch for human/agent review before committing to the full grid.

Workers run in a ``multiprocessing`` pool (fork start method: registered
runners are inherited). A case's multistart presets run sequentially inside
one worker and only the picked-best attempt becomes the case result;
parallelism is across cases.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
import traceback
from pathlib import Path
from typing import Callable

from hangar.sdk.study.expand import StudyCase, expand_cases
from hangar.sdk.study.review import review_study
from hangar.sdk.study.schema import load_study
from hangar.sdk.study.store import StudyStore

logger = logging.getLogger(__name__)

SUCCESS_STATUSES = frozenset({"converged", "completed"})

_RUNNERS: dict[str, dict[str, Callable]] = {}


class StudyGuardError(RuntimeError):
    """Raised when a run would exceed the review threshold unconfirmed.

    Carries the review payload so callers (CLI, MCP) can show the case
    count and compute estimate instead of a bare refusal.
    """

    def __init__(self, message: str, review: dict) -> None:
        super().__init__(message)
        self.review = review


def register_runner(
    name: str,
    run_case: Callable[[dict, dict], dict],
    generate_case: Callable[[dict, dict], Path] | None = None,
) -> None:
    """Register a runner. ``generate_case`` (optional) materializes the
    case's input artifact (e.g. an omd plan YAML) without running it."""
    _RUNNERS[name] = {"run": run_case, "generate": generate_case}


def _discover_runner(name: str) -> bool:
    """Try to load a runner via the ``hangar.study_runners`` entry-point group.

    Each runner package advertises a module whose import registers its
    runner (e.g. ``oas = "hangar.oas.study_runner"``), so studies can mix
    tools without the caller hand-importing every adapter.
    """
    from importlib import import_module, metadata

    for ep in metadata.entry_points(group="hangar.study_runners"):
        if ep.name != name:
            continue
        try:
            import_module(ep.value)
        except Exception as exc:
            raise KeyError(
                f"runner {name!r} found as entry point {ep.value!r} but "
                f"failed to import: {type(exc).__name__}: {exc}") from exc
        return name in _RUNNERS
    return False


def list_available_runners() -> dict[str, str]:
    """Registered runners plus discoverable-but-unloaded entry points."""
    from importlib import metadata

    out = {name: "registered" for name in _RUNNERS}
    for ep in metadata.entry_points(group="hangar.study_runners"):
        out.setdefault(ep.name, f"entry point ({ep.value})")
    return out


def get_runner(name: str) -> dict[str, Callable]:
    if name not in _RUNNERS and not _discover_runner(name):
        raise KeyError(
            f"no runner registered for {name!r} (available: "
            f"{sorted(list_available_runners()) or 'none'}). Install the "
            "tool package that provides it, or import its runner module "
            "(e.g. hangar.omd.study_runner for 'omd').")
    return _RUNNERS[name]


def _pick_best(attempts: list[dict], pick: dict) -> dict:
    """Choose the best multistart attempt.

    Success with a finite pick-output beats any failure; ties break on the
    pick mode (min/max). Falls back to the first attempt when nothing
    succeeded.
    """
    output = pick.get("output")
    mode = pick.get("mode", "min")

    def metric(attempt: dict) -> float | None:
        val = (attempt.get("outputs") or {}).get(output)
        try:
            val = float(val)
        except (TypeError, ValueError):
            return None
        if val != val or val in (float("inf"), float("-inf")):
            return None
        return val

    ranked = [
        (metric(a), a) for a in attempts
        if a.get("status") in SUCCESS_STATUSES and metric(a) is not None
    ]
    if not ranked:
        return attempts[0]
    sign = 1.0 if mode == "min" else -1.0
    return min(ranked, key=lambda pair: sign * pair[0])[1]


def _run_one_case(args: tuple) -> dict:
    """Worker: run one case (all multistart presets) and return its result."""
    case_dict, ctx, presets, pick = args
    t0 = time.perf_counter()
    attempts: list[dict] = []
    try:
        runner = get_runner(case_dict["runner"])["run"]
        variants = presets or {None: None}
        for preset_name, payload in variants.items():
            attempt_ctx = dict(ctx)
            if preset_name is not None:
                attempt_ctx["preset"] = payload
                attempt_ctx["preset_name"] = preset_name
            try:
                result = runner(dict(case_dict["spec"]), attempt_ctx)
            except Exception as exc:
                result = {"status": "error", "run_ref": None, "outputs": {},
                          "error": f"{type(exc).__name__}: {exc}"}
                logger.debug("case %s preset %s raised:\n%s",
                             case_dict["case_id"], preset_name,
                             traceback.format_exc())
            result["preset"] = preset_name
            attempts.append(result)
        best = _pick_best(attempts, pick or {})
    except Exception as exc:
        best = {"status": "error", "run_ref": None, "outputs": {},
                "error": f"{type(exc).__name__}: {exc}", "preset": None}
        attempts = [best]
    return {
        "case_key": case_dict["case_key"],
        "case_id": case_dict["case_id"],
        "result": best,
        "attempts": [
            {"preset": a.get("preset"), "status": a.get("status"),
             "run_ref": a.get("run_ref"), "error": a.get("error")}
            for a in attempts
        ],
        "wall_time_s": time.perf_counter() - t0,
    }


def _pending_cases(
    cases: list[StudyCase],
    state: dict,
    retry_failed: bool,
) -> list[StudyCase]:
    rerun = {"pending", "running"}
    if retry_failed:
        rerun |= {"failed", "error", "timeout"}
    return [
        c for c in cases
        if (state["cases"].get(c.case_key) or {}).get("status", "pending") in rerun
    ]


def run_study(
    study_path: Path | str,
    max_cases: int | None = None,
    workers: int | None = None,
    confirm: bool = False,
    retry_failed: bool = False,
    store_root: Path | None = None,
    on_case_done: Callable[[dict, dict], None] | None = None,
) -> dict:
    """Expand, checkpoint, and run a study (or the next batch of it).

    Args:
        study_path: Path to study.yaml.
        max_cases: Run at most this many pending cases, then stop (the
            incremental/pilot mode). None means all pending cases.
        workers: Worker process count (overrides execution.workers).
        confirm: Required when running more pending cases than
            ``execution.review_threshold`` without a ``max_cases`` batch.
        retry_failed: Also re-run cases that previously failed/errored.
        store_root: Override the studies root (tests).
        on_case_done: Optional ``(case_result, progress_summary)`` callback
            fired after each case is checkpointed.

    Returns a summary dict: study_id, ran/succeeded/failed counts for this
    batch, overall progress counts, and the cases.csv path.

    Raises StudyGuardError (with the review payload attached) when the
    batch size needs explicit confirmation.
    """
    study_path = Path(study_path)
    study, errors = load_study(study_path)
    if errors:
        raise ValueError(f"study failed validation: {errors}")

    meta = study["metadata"]
    study_id, version = meta["id"], meta.get("version", 1)
    cases = expand_cases(study)

    store = StudyStore(study_id, root=store_root)
    store.save_spec(study_path.read_text(), version)
    state = store.sync_cases(cases, version)

    pending = _pending_cases(cases, state, retry_failed)
    rev = review_study(study, cases, state=state)
    execution = study.get("execution") or {}
    threshold = rev["review_threshold"]
    if max_cases is None and len(pending) > threshold and not confirm:
        raise StudyGuardError(
            f"{len(pending)} pending cases exceed review_threshold="
            f"{threshold} (est wall {rev['est_wall_human'] or 'unknown'}). "
            "Review the study, then re-run with confirm=True, or run an "
            "incremental batch via max_cases.",
            review=rev,
        )

    batch = pending if max_cases is None else pending[:max_cases]
    n_workers = workers or execution.get("workers", 1)
    multistart = study.get("multistart") or {}
    presets = multistart.get("presets") or None
    pick = multistart.get("pick") or {}
    outputs = study.get("outputs") or []

    work = []
    for case in batch:
        ctx = {
            "study_id": study_id,
            "study_version": version,
            "study_dir": str(study_path.parent),
            "case_id": case.case_id,
            "case_key": case.case_key,
            "params": case.params,
            "outputs": outputs,
            "artifact_dir": str(store.case_artifact_dir(case.case_id)),
        }
        store.update_case(case.case_key, status="running")
        work.append((case.to_dict(), ctx, presets, pick))

    ran = succeeded = failed = 0
    pool = None
    try:
        if n_workers == 1 or len(work) <= 1:
            iterator = map(_run_one_case, work)
        else:
            pool = mp.Pool(min(n_workers, len(work)))
            iterator = pool.imap_unordered(_run_one_case, work)

        for done in iterator:
            result = done["result"]
            status = result.get("status", "error")
            ran += 1
            if status in SUCCESS_STATUSES:
                succeeded += 1
            else:
                failed += 1
            store.update_case(
                done["case_key"],
                status=status,
                run_ref=result.get("run_ref"),
                outputs=result.get("outputs") or {},
                error=result.get("error"),
                wall_time_s=done["wall_time_s"],
                attempts=done["attempts"],
            )
            if on_case_done:
                on_case_done(done, store.status_summary())
    finally:
        if pool is not None:
            pool.close()
            pool.join()
        # Anything still marked running was interrupted; put it back.
        end_state = store.load_state()
        for key, entry in end_state["cases"].items():
            if entry.get("status") == "running":
                store.update_case(key, status="pending")

    summary = store.status_summary()
    return {
        "study_id": study_id,
        "version": version,
        "batch": {"ran": ran, "succeeded": succeeded, "failed": failed,
                  "requested": len(batch)},
        "progress": summary,
        "remaining": summary["total"] - summary["done"],
        "cases_csv": str(store.csv_path),
        "study_dir": str(store.dir),
    }


def generate_study(
    study_path: Path | str,
    store_root: Path | None = None,
) -> dict:
    """Materialize every case's input artifact without running anything.

    Uses each runner's optional ``generate_case`` hook (e.g. the omd runner
    writes the per-case plan YAMLs) so humans/agents can review the
    generated plans before committing compute. Returns
    ``{study_id, generated: [{case_id, artifact}], skipped: [...]}``.
    """
    study_path = Path(study_path)
    study, errors = load_study(study_path)
    if errors:
        raise ValueError(f"study failed validation: {errors}")

    meta = study["metadata"]
    store = StudyStore(meta["id"], root=store_root)
    store.save_spec(study_path.read_text(), meta.get("version", 1))
    cases = expand_cases(study)
    store.sync_cases(cases, meta.get("version", 1))

    generated, skipped = [], []
    for case in cases:
        gen = get_runner(case.runner).get("generate")
        if gen is None:
            skipped.append({"case_id": case.case_id, "runner": case.runner,
                            "reason": "runner has no generate hook"})
            continue
        ctx = {
            "study_id": meta["id"],
            "study_version": meta.get("version", 1),
            "study_dir": str(study_path.parent),
            "case_id": case.case_id,
            "case_key": case.case_key,
            "params": case.params,
            "outputs": study.get("outputs") or [],
            "artifact_dir": str(store.case_artifact_dir(case.case_id)),
        }
        path = gen(dict(case.spec), ctx)
        generated.append({"case_id": case.case_id, "artifact": str(path)})
    return {"study_id": meta["id"], "generated": generated, "skipped": skipped,
            "study_dir": str(store.dir)}
