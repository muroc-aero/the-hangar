"""Plan validation, assembly, and execution tools."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from hangar.sdk.envelope.response import make_envelope, make_error_envelope
from hangar.sdk.errors import UserInputError
from hangar.sdk.telemetry import make_telemetry
from hangar.sdk.validation.checks import ValidationFinding, findings_to_dict

from hangar.omd.tools._helpers import resolve_plan_dir, resolve_plan_path, view_urls

_RUN_MODES = ("analysis", "optimize")
_RECORDING_LEVELS = ("minimal", "driver", "solver", "full")


def _semantic_findings(plan: dict) -> list[dict]:
    """Run the semantic preflight and return findings as dicts."""
    from hangar.omd.plan_validate import validate_plan_semantic
    from hangar.omd.registry import list_factories

    findings = validate_plan_semantic(plan, registry_types=set(list_factories()))
    return [f.to_dict() for f in findings]


async def validate_plan(
    plan_path: Annotated[str, "Path to assembled plan YAML (workspace-relative or absolute)"],
    semantic: Annotated[bool, "Also run semantic checks (component types, DV/constraint/objective name resolution)"] = True,
) -> dict:
    """Validate an analysis plan YAML against the schema and semantic checks.

    Returns ``{valid, plan_id}`` on success or ``{valid: False, errors: [...]}``
    where each error has ``path``, ``message``, and optional ``suggestions``.
    """
    from hangar.omd.plan_schema import load_and_validate

    path = resolve_plan_path(plan_path)
    plan, errors = await asyncio.to_thread(load_and_validate, path)
    if errors:
        return {"valid": False, "errors": errors}

    if semantic and plan is not None:
        findings = await asyncio.to_thread(_semantic_findings, plan)
        if findings:
            return {"valid": False, "errors": findings}

    return {"valid": True, "plan_id": plan.get("metadata", {}).get("id")}


async def assemble_plan(
    plan_dir: Annotated[str, "Plan directory with modular YAML files (workspace-relative or absolute)"],
    output: Annotated[str | None, "Output path for the assembled plan (default: <plan_dir>/plan.yaml)"] = None,
) -> dict:
    """Assemble a modular plan directory into a canonical, versioned plan.yaml.

    Returns ``{version, content_hash, output_path, errors}``; a non-empty
    ``errors`` list means the assembled plan failed validation.
    """
    from hangar.omd.assemble import assemble_plan as _assemble

    src = resolve_plan_dir(plan_dir)
    out = Path(output).expanduser() if output else None
    result = await asyncio.to_thread(_assemble, src, output=out)
    if result.get("output_path") is not None:
        result["output_path"] = str(result["output_path"])
    return result


def _run_findings(result: dict, mode: str) -> list[ValidationFinding]:
    """Convergence and optimization-sanity findings for the run envelope."""
    findings: list[ValidationFinding] = []
    status = str(result.get("status", "unknown"))
    converged = status in ("converged", "completed", "complete", "success")
    findings.append(ValidationFinding(
        check_id="run_status",
        category="numerics",
        severity="error",
        confidence="high",
        passed=converged,
        message=f"Run finished with status {status!r}",
        remediation="" if converged else
        "Inspect errors/summary; check solver options and operating point.",
    ))
    if mode == "optimize":
        case_count = (result.get("summary", {}).get("recording") or {}).get("case_count", 0)
        suspicious = 0 < case_count <= 2
        findings.append(ValidationFinding(
            check_id="optimizer_iterations",
            category="numerics",
            severity="warning",
            confidence="medium",
            passed=not suspicious,
            message=(
                f"Optimizer recorded {case_count} driver iterations"
                + (" -- convergence in 1-2 iterations usually means DV bounds "
                   "are wrong or DVs are not being applied" if suspicious else "")
            ),
        ))
    return findings


async def run_plan(
    plan_path: Annotated[str, "Path to assembled plan YAML (workspace-relative or absolute)"],
    mode: Annotated[str, "Execution mode: 'analysis' (run once) or 'optimize' (run driver)"] = "analysis",
    recording_level: Annotated[str, "Recorder verbosity: minimal, driver, solver, full"] = "driver",
    timeout_seconds: Annotated[int | None, "Wallclock timeout; the run aborts if exceeded"] = None,
    stability: Annotated[bool, "Also compute stability derivatives after analysis (OAS aero plans)"] = False,
) -> dict:
    """Materialize and run an analysis plan (schema + semantic preflight included).

    Returns a versioned envelope; ``results`` carries ``run_id``, ``status``,
    ``summary``, and ``urls`` (problem DAG, plots, N2, range-safety dashboard).
    Use the run_id with get_results / generate_plots / get_run_summary /
    record_conclusion.
    """
    from hangar.omd.plan_schema import load_and_validate
    from hangar.omd.run import run_plan as _run_plan

    t0 = time.perf_counter()
    if mode not in _RUN_MODES:
        raise UserInputError(f"mode must be one of {_RUN_MODES} (got {mode!r})")
    if recording_level not in _RECORDING_LEVELS:
        raise UserInputError(
            f"recording_level must be one of {_RECORDING_LEVELS} (got {recording_level!r})"
        )

    path = resolve_plan_path(plan_path)
    inputs = {
        "plan_path": str(path),
        "mode": mode,
        "recording_level": recording_level,
        "timeout_seconds": timeout_seconds,
        "stability": stability,
    }

    # Pre-flight: schema + semantic, so typos fail fast with suggestions
    # (parity with `omd-cli run`).
    plan, schema_errors = await asyncio.to_thread(load_and_validate, path)
    if schema_errors:
        return make_error_envelope(
            "run_plan", "USER_INPUT_ERROR",
            "Plan failed schema validation (run aborted)",
            details={"errors": schema_errors}, inputs=inputs,
        )
    semantic_errors = await asyncio.to_thread(_semantic_findings, plan or {})
    if semantic_errors:
        return make_error_envelope(
            "run_plan", "USER_INPUT_ERROR",
            "Plan failed semantic validation (run aborted)",
            details={"errors": semantic_errors}, inputs=inputs,
        )
    plan_id = ((plan or {}).get("metadata") or {}).get("id")

    result = await asyncio.to_thread(
        _run_plan, path, mode=mode, recording_level=recording_level,
        timeout_seconds=timeout_seconds, compute_stab=stability,
    )

    if result.get("errors"):
        code = "SOLVER_CONVERGENCE_ERROR" if result.get("run_id") else "USER_INPUT_ERROR"
        return make_error_envelope(
            "run_plan", code,
            f"Run failed with status {result.get('status', 'failed')!r}",
            details={"errors": result["errors"], "run_id": result.get("run_id")},
            inputs=inputs,
        )

    run_id = result["run_id"]
    results = {
        "run_id": run_id,
        "status": result.get("status"),
        "summary": result.get("summary", {}),
        "urls": view_urls(run_id=run_id, plan_id=plan_id),
    }
    validation = findings_to_dict(_run_findings(result, mode))
    telem = make_telemetry(time.perf_counter() - t0, False)
    return make_envelope("run_plan", run_id, inputs, results, validation, telem)


async def run_polar(
    plan_path: Annotated[str, "Path to assembled plan YAML for an OAS aero/aerostruct plan"],
    alpha_start: Annotated[float, "Starting angle of attack (deg)"] = -5.0,
    alpha_end: Annotated[float, "Ending angle of attack (deg)"] = 15.0,
    num_alpha: Annotated[int, "Number of alpha points to evaluate"] = 21,
) -> dict:
    """Sweep angle of attack and compute a drag polar (parameter sweep mode).

    Returns an envelope whose ``results`` carry ``alpha_deg``, ``CL``, ``CD``,
    ``L_over_D`` arrays and ``best_L_over_D``.
    """
    from hangar.omd.polar import run_polar as _run_polar

    t0 = time.perf_counter()
    if num_alpha < 2:
        raise UserInputError(f"num_alpha must be >= 2 (got {num_alpha})")
    if alpha_end <= alpha_start:
        raise UserInputError(
            f"alpha_end ({alpha_end}) must be greater than alpha_start ({alpha_start})"
        )

    path = resolve_plan_path(plan_path)
    inputs = {
        "plan_path": str(path),
        "alpha_start": alpha_start,
        "alpha_end": alpha_end,
        "num_alpha": num_alpha,
    }
    results = await asyncio.to_thread(
        _run_polar, path,
        alpha_start=alpha_start, alpha_end=alpha_end, num_alpha=num_alpha,
    )
    telem = make_telemetry(time.perf_counter() - t0, False)
    return make_envelope("run_polar", None, inputs, results, None, telem)
