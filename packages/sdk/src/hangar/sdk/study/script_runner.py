"""Generic script-step runner: any sdk-CLI tool registry becomes a study runner.

Every hangar tool CLI built on :mod:`hangar.sdk.cli` (oas, ocp, pyc) exposes
its tools as a registry of ``name -> async callable``. This module turns such
a registry into a study runner whose case input artifact is a workflow
script: the same ``[{tool, args}]`` JSON list the CLI's ``run-script`` mode
executes. The per-tool adapters are then one call each::

    # packages/oas/src/hangar/oas/study_runner.py
    from hangar.oas.cli import build_oas_registry
    from hangar.sdk.study.script_runner import make_script_runner

    make_script_runner("oas", build_oas_registry)

Case spec for a script runner:

.. code-block:: yaml

    script: scripts/polar_base.json   # step list, relative to study.yaml
    # or inline (steps need an "id" to be addressable from bind paths):
    steps:
      - {id: surf, tool: create_surface, args: {name: wing, num_y: 7}}
      - {id: analyze, tool: run_aero_analysis, args: {alpha: 2.0}}
    set:                              # patches (filled by matrix bind)
      steps[analyze].args.alpha: 4.0
    success_when:                     # optional; maps a result field to
      step: analyze                   # converged/failed (tools name their
      path: results.success           # flag differently). Default: all
                                      # steps ok -> "completed".
    run_ref_step: analyze             # optional; default: last run_id seen

Output column paths are ``"step_ref:dotted.path"`` into that step's result
envelope, e.g. ``analyze:results.CL`` (step_ref is a step id or 0-based
index). Multistart presets carry the same ``set`` shape and apply on top of
the case spec.

Steps run in-process and sequentially; ``$prev.run_id`` / ``$N.run_id``
interpolation works exactly as in ``run-script``. The first failing step
fails the case (no point spending compute on dependents). If the registry
has a ``reset`` tool it is called before each case/preset attempt, because
pool workers are reused across cases and tool session state would otherwise
leak between them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from hangar.sdk.study.expand import set_by_path
from hangar.sdk.study.orchestrate import register_runner

logger = logging.getLogger(__name__)

# Registries cache per process: pool workers are forked from the
# orchestrator and reused across cases, so each worker builds a tool's
# registry once. Keyed by runner name.
_REGISTRIES: dict[str, dict[str, Callable]] = {}


def _fresh_provenance_db() -> None:
    """Drop any sqlite connection inherited across a fork.

    Same pattern as the omd runner: rebinding the module's thread-local is
    child-only state, so the parent orchestrator is unaffected.
    """
    import hangar.sdk.provenance.db as pdb

    pdb._local = threading.local()


def _get_registry(name: str, builder: Callable[[], dict[str, Callable]]) -> dict:
    reg = _REGISTRIES.get(name)
    if reg is None:
        reg = builder()
        _REGISTRIES[name] = reg
    return reg


def _resolve_steps(spec: dict, ctx: dict) -> list[dict]:
    """Load the step list from the spec (inline ``steps`` or a ``script`` file)."""
    if spec.get("steps") is not None:
        steps = deepcopy(spec["steps"])
    elif spec.get("script"):
        path = Path(spec["script"])
        if not path.is_absolute():
            study_dir = ctx.get("study_dir")
            candidates = [Path(study_dir) / path] if study_dir else []
            candidates.append(path)
            path = next((c for c in candidates if c.exists()), None)
            if path is None:
                raise FileNotFoundError(
                    f"script {spec['script']!r} not found (tried "
                    f"{[str(c) for c in candidates]})")
        elif not path.exists():
            raise FileNotFoundError(f"script not found: {path}")
        steps = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(
            "script-runner case spec needs 'steps' (inline list) or "
            "'script' (path to a workflow JSON, relative to study.yaml)")

    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        raise ValueError("script must be a list of {tool, args} step objects")
    return steps


def _build_case_steps(spec: dict, ctx: dict) -> list[dict]:
    """Steps + spec ``set`` patches + preset ``set`` patches."""
    steps = _resolve_steps(spec, ctx)
    # set_by_path addresses list elements by id/name selector, so wrap the
    # list: bind paths look like steps[analyze].args.alpha.
    doc = {"steps": steps}
    for path_expr, value in (spec.get("set") or {}).items():
        set_by_path(doc, path_expr, value)
    preset = ctx.get("preset") or {}
    for path_expr, value in (preset.get("set") or {}).items():
        set_by_path(doc, path_expr, value)
    return doc["steps"]


def _validate_steps(steps: list[dict], registry: dict, case_id: str) -> None:
    problems = []
    for i, step in enumerate(steps):
        tool = step.get("tool")
        if not isinstance(tool, str) or not tool:
            problems.append(f"steps[{i}]: missing 'tool'")
            continue
        if tool not in registry:
            problems.append(
                f"steps[{i}]: unknown tool {tool!r} (available: "
                f"{sorted(registry)})")
        args = step.get("args", {})
        if not isinstance(args, dict):
            problems.append(f"steps[{i}] ({tool}): 'args' must be a mapping")
    if problems:
        raise ValueError(f"case {case_id!r} script invalid: {problems}")


def _find_step(steps: list[dict], ref: Any) -> int:
    """Resolve a step reference (id string or 0-based index) to an index."""
    if isinstance(ref, int) or (isinstance(ref, str) and ref.lstrip("-").isdigit()):
        idx = int(ref)
        if not 0 <= idx < len(steps):
            raise ValueError(f"step index {idx} out of range (0..{len(steps) - 1})")
        return idx
    for i, step in enumerate(steps):
        if step.get("id") == ref:
            return i
    raise ValueError(
        f"no step with id {ref!r} (ids: "
        f"{[s.get('id') for s in steps]})")


def _dig(node: Any, path: str) -> Any:
    """Descend a dotted path through dicts/lists; None when absent."""
    for token in path.split("."):
        if isinstance(node, dict):
            node = node.get(token)
        elif isinstance(node, list) and token.lstrip("-").isdigit():
            idx = int(token)
            node = node[idx] if -len(node) <= idx < len(node) else None
        else:
            return None
    return node


def _extract_outputs(
    steps: list[dict], results: list[dict], output_defs: list[dict],
) -> dict:
    """Resolve ``"step_ref:dotted.path"`` output columns from step results."""
    out: dict = {}
    for d in output_defs:
        name, path = d["name"], d["path"]
        try:
            ref, _, field = path.partition(":")
            if not field:
                raise ValueError(
                    f"output path {path!r} must be 'step_ref:dotted.path'")
            idx = _find_step(steps, ref)
            result = results[idx].get("result") if idx < len(results) else None
            out[name] = _dig(result, field)
        except Exception as exc:
            # Debug, not warning: in a cross-tool study every runner sees
            # the other runners' output columns and resolves them to None.
            logger.debug("output %s (%s): %s", name, path, exc)
            out[name] = None
    return out


async def _run_steps(registry: dict, steps: list[dict]) -> list[dict]:
    """Execute steps sequentially, stopping at the first failure.

    Mirrors the CLI run-script semantics ({ok, result} | {ok, error} per
    step) but takes the registry explicitly instead of the CLI's
    module-level singleton, so multiple runners can coexist in one process.
    """
    from hangar.sdk.cli.runner import interpolate_args

    results: list[dict] = []
    for i, step in enumerate(steps):
        tool, args = step["tool"], dict(step.get("args") or {})
        try:
            args = interpolate_args(args, results)
        except ValueError as exc:
            results.append({"step": i, "tool": tool, "ok": False,
                            "error": {"code": "USER_INPUT_ERROR",
                                      "message": str(exc)}})
            break
        fn = registry[tool]
        try:
            result = await fn(**args)
            results.append({"step": i, "tool": tool, "ok": True,
                            "result": result})
        except Exception as exc:
            err = exc.to_dict() if hasattr(exc, "to_dict") else {
                "code": "INTERNAL_ERROR", "message": str(exc)}
            results.append({"step": i, "tool": tool, "ok": False, "error": err})
            break
    return results


def _step_run_id(result: dict) -> str | None:
    payload = result.get("result")
    if isinstance(payload, dict):
        rid = payload.get("run_id")
        return rid if isinstance(rid, str) else None
    return None


def make_script_runner(
    name: str,
    registry_builder: Callable[[], dict[str, Callable]],
) -> tuple[Callable, Callable]:
    """Build and register a script-based study runner for a tool registry.

    Args:
        name: Runner name (``runner:`` value in study specs).
        registry_builder: Zero-arg callable returning the tool's
            ``name -> async callable`` map (each tool CLI already defines
            one for ``set_registry_builder``). Built lazily per process so
            heavy tool imports stay out of the orchestrator parent.

    Returns the ``(run_case, generate_case)`` pair, already registered via
    :func:`hangar.sdk.study.register_runner` under ``name``.
    """

    def generate_case(spec: dict, ctx: dict) -> Path:
        """Materialize the case's script artifact (no run) and preflight it."""
        steps = _build_case_steps(spec, ctx)
        registry = _get_registry(name, registry_builder)
        _validate_steps(steps, registry, ctx.get("case_id", "?"))

        preset_name = ctx.get("preset_name")
        fname = f"script-{preset_name}.json" if preset_name else "script.json"
        out = Path(ctx["artifact_dir"]) / fname
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(steps, indent=2), encoding="utf-8")
        return out

    def run_case(spec: dict, ctx: dict) -> dict:
        """Run one study case as an in-process workflow script."""
        _fresh_provenance_db()

        script_path = generate_case(spec, ctx)
        steps = json.loads(script_path.read_text(encoding="utf-8"))
        registry = _get_registry(name, registry_builder)

        async def _execute() -> list[dict]:
            # Pool workers are reused across cases: clear the tool's session
            # state so one case's surfaces/aircraft/engines can't leak into
            # the next.
            reset = registry.get("reset")
            if reset is not None:
                try:
                    await reset()
                except Exception as exc:
                    logger.debug("reset before case %s failed: %s",
                                 ctx.get("case_id"), exc)
            return await _run_steps(registry, steps)

        results = asyncio.run(_execute())

        failed = next((r for r in results if not r.get("ok")), None)
        error = None
        if failed is not None:
            err = failed.get("error") or {}
            error = (f"step {failed['step']} ({failed['tool']}): "
                     f"{err.get('code')}: {err.get('message')}")[:500]

        run_ref = None
        ref_step = spec.get("run_ref_step")
        if ref_step is not None:
            idx = _find_step(steps, ref_step)
            if idx < len(results):
                run_ref = _step_run_id(results[idx])
        else:
            for r in results:
                rid = _step_run_id(r)
                if rid:
                    run_ref = rid

        if failed is not None:
            status = "failed"
        else:
            cond = spec.get("success_when")
            if cond:
                idx = _find_step(steps, cond["step"])
                val = _dig(results[idx].get("result"),
                           cond.get("path", "results.success"))
                status = "converged" if val else "failed"
                if not val and error is None:
                    error = (f"success_when {cond.get('path')!r} on step "
                             f"{cond['step']!r} was {val!r}")
            else:
                status = "completed"

        outputs = _extract_outputs(steps, results, ctx.get("outputs") or [])
        return {
            "status": status,
            "run_ref": run_ref,
            "outputs": outputs,
            "error": error,
            "artifacts": {"script": str(script_path)},
        }

    register_runner(name, run_case, generate_case=generate_case)
    return run_case, generate_case
