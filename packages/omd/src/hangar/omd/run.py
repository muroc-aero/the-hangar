"""Plan execution: load, materialize, run, record.

Orchestrates the full pipeline from plan YAML to recorded results
in the analysis database with PROV-Agent provenance tracking.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hangar.omd.plan_schema import load_and_validate
from hangar.omd.materializer import materialize, apply_solvers_post_setup
from hangar.omd.recorder import import_recorder_data
from hangar.omd.db import (
    init_analysis_db,
    plan_store_dir,
    recordings_dir,
    record_entity,
    record_activity,
    add_prov_edge,
)

logger = logging.getLogger(__name__)


def run_plan(
    plan_path: Path,
    mode: str = "analysis",
    recording_level: str = "driver",
    db_path: Path | None = None,
) -> dict:
    """Load, materialize, execute, and record an analysis plan.

    Args:
        plan_path: Path to assembled plan.yaml.
        mode: "analysis" (run_model) or "optimize" (run_driver).
        recording_level: "minimal", "driver", "solver", or "full".
        db_path: Path to analysis DB. If None, uses default.

    Returns:
        Structured result dict with:
        - run_id: unique identifier
        - status: "converged" | "failed" | "completed"
        - summary: key results dict
        - errors: list of error dicts if any
    """
    plan_path = Path(plan_path)

    # Initialize DB
    init_analysis_db(db_path)

    # Load and validate plan
    plan, errors = load_and_validate(plan_path)
    if errors:
        return {
            "run_id": None,
            "status": "failed",
            "summary": {},
            "errors": errors,
        }

    # Generate IDs
    run_id = _generate_run_id()
    plan_id = plan.get("metadata", {}).get("id", "unknown")
    plan_version = plan.get("metadata", {}).get("version", 0)
    plan_entity_id = f"{plan_id}/v{plan_version}"
    activity_id = f"act-execute-{run_id}"

    # Record plan entity -- use plan store path if available
    content_hash = plan.get("metadata", {}).get("content_hash")
    store_path = plan_store_dir() / plan_id / f"v{plan_version}.yaml"
    plan_storage_ref = str(store_path) if store_path.exists() else str(plan_path)
    record_entity(
        entity_id=plan_entity_id,
        entity_type="plan",
        created_by="have-agent",
        plan_id=plan_id,
        version=plan_version,
        content_hash=content_hash,
        storage_ref=plan_storage_ref,
    )

    # Replan provenance: link to parent version if this is a revision
    parent_version = plan.get("metadata", {}).get("parent_version")
    if parent_version:
        parent_entity_id = f"{plan_id}/v{parent_version}"
        add_prov_edge("wasDerivedFrom", plan_entity_id, parent_entity_id)

    # Record execute activity start
    started_at = datetime.now(timezone.utc).isoformat()
    record_activity(
        activity_id=activity_id,
        activity_type="execute",
        agent="omd",
        started_at=started_at,
        status="running",
    )

    # Provenance: activity used plan
    add_prov_edge("used", activity_id, plan_entity_id)

    # Materialize with persistent recorder path
    rec_dir = recordings_dir()
    rec_dir.mkdir(parents=True, exist_ok=True)
    recorder_path = rec_dir / f"{run_id}.sql"

    try:
        prob, metadata = materialize(plan, recording_level,
                                     recorder_path=recorder_path)
        apply_solvers_post_setup(prob, metadata)
    except Exception as exc:
        _record_failure(activity_id, run_id, plan_id, plan_entity_id, str(exc))
        return {
            "run_id": run_id,
            "status": "failed",
            "summary": {},
            "errors": [{"path": "materialize", "message": str(exc)}],
        }

    # Execute
    try:
        if mode == "optimize":
            prob.run_driver()
        else:
            prob.run_model()

        prob.record("final")
        prob.cleanup()
    except Exception as exc:
        prob.cleanup()
        _record_failure(activity_id, run_id, plan_id, plan_entity_id, str(exc))
        return {
            "run_id": run_id,
            "status": "failed",
            "summary": {},
            "errors": [{"path": "execute", "message": str(exc)}],
        }

    # Import recorder data
    recorder_path = metadata.get("recorder_path")
    recorder_info = {"case_count": 0, "storage_bytes": 0}
    if recorder_path and Path(recorder_path).exists():
        try:
            recorder_info = import_recorder_data(Path(recorder_path), run_id)
        except Exception as exc:
            logger.warning("Failed to import recorder data: %s", exc)

    # Extract summary results
    summary = _extract_summary(prob, metadata, mode)
    summary["recording"] = recorder_info

    # Determine status
    status = "completed"
    if mode == "optimize":
        try:
            if hasattr(prob.driver, "result") and prob.driver.result is not None:
                status = "converged" if prob.driver.result.success else "failed"
        except Exception:
            pass

    # Record run entity
    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="omd",
        plan_id=plan_id,
        storage_ref=str(recorder_path) if recorder_path else None,
    )

    # Provenance: run wasGeneratedBy execute
    add_prov_edge("wasGeneratedBy", run_id, activity_id)

    # Update activity as completed
    record_activity(
        activity_id=activity_id,
        activity_type="execute",
        agent="omd",
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        status="completed",
    )

    return {
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "errors": [],
    }


def format_convergence_table(recorder_path: Path) -> str | None:
    """Format a convergence summary table from recorder data.

    Reads driver cases and produces a text table showing objective
    and constraint values per iteration. Returns None if fewer than
    2 driver cases are available.

    Args:
        recorder_path: Path to OpenMDAO recorder file.

    Returns:
        Formatted table string, or None if not enough data.
    """
    import openmdao.api as om
    import numpy as np

    try:
        reader = om.CaseReader(str(recorder_path))
        driver_cases = reader.list_cases("driver", recurse=False, out_stream=None)
    except Exception:
        return None

    if len(driver_cases) < 2:
        return None

    # Sample iterations for display (show at most 10 rows)
    n = len(driver_cases)
    if n <= 10:
        indices = list(range(n))
    else:
        # Always show first, last, and evenly-spaced middle
        step = max(1, (n - 1) // 8)
        indices = list(range(0, n, step))
        if indices[-1] != n - 1:
            indices.append(n - 1)

    # Find the objective variable (first scalar that changes)
    first_case = reader.get_case(driver_cases[0])
    last_case = reader.get_case(driver_cases[-1])

    first_outputs = first_case.list_outputs(out_stream=None, return_format="dict")
    last_outputs = last_case.list_outputs(out_stream=None, return_format="dict")

    obj_name = None
    for name in first_outputs:
        if name not in last_outputs:
            continue
        v0 = first_outputs[name].get("val", first_outputs[name].get("value"))
        v1 = last_outputs[name].get("val", last_outputs[name].get("value"))
        if v0 is not None and v1 is not None:
            a0 = np.atleast_1d(v0)
            a1 = np.atleast_1d(v1)
            if a0.size == 1 and a1.size == 1:
                f0, f1 = float(a0.flat[0]), float(a1.flat[0])
                if f0 != f1:
                    obj_name = name
                    break

    if obj_name is None:
        return None

    # Build table
    lines = ["Optimization progress:"]
    header = f"  {'Iter':>5}  {'Objective':>18}  {'Variable':>s}"
    lines.append(header.replace("Variable", obj_name.split(".")[-1]))
    lines.append(f"  {'----':>5}  {'------------------':>18}")

    for idx in indices:
        case = reader.get_case(driver_cases[idx])
        outputs = case.list_outputs(out_stream=None, return_format="dict")
        val = outputs.get(obj_name, {}).get("val")
        if val is None:
            val = outputs.get(obj_name, {}).get("value")
        if val is not None:
            fval = float(np.atleast_1d(val).flat[0])
            lines.append(f"  {idx:>5}  {fval:>18.6e}")

    return "\n".join(lines)
    # Update activity as completed
    record_activity(
        activity_id=activity_id,
        activity_type="execute",
        agent="omd",
        started_at=started_at,
        completed_at=datetime.now(timezone.utc).isoformat(),
        status="completed",
    )

    return {
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "errors": [],
    }


def _generate_run_id() -> str:
    """Generate a sortable, collision-resistant run ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"run-{ts}-{suffix}"


def _extract_summary(prob, metadata: dict, mode: str) -> dict:
    """Extract key results from a solved problem."""
    import numpy as np

    point_name = metadata.get("point_name", "AS_point_0")
    summary: dict = {"mode": mode}

    # Generic output extraction (paraboloid, etc.)
    for output_name in metadata.get("output_names", []):
        try:
            val = prob.get_val(output_name)
            key = output_name.split(".")[-1]
            summary[key] = float(val.flat[0]) if hasattr(val, "flat") else float(val)
        except Exception:
            pass

    # OAS-specific outputs
    try:
        summary["CL"] = float(prob.get_val(f"{point_name}.CL")[0])
    except Exception:
        pass
    try:
        summary["CD"] = float(prob.get_val(f"{point_name}.CD")[0])
    except Exception:
        pass
    try:
        cl = summary.get("CL", 0)
        cd = summary.get("CD", 1)
        if cd > 0:
            summary["L_over_D"] = cl / cd
    except Exception:
        pass

    # Surface-specific results
    for surf_name in metadata.get("surface_names", []):
        # Structural mass: available on the geometry group output
        for mass_path in (
            f"{surf_name}.structural_mass",
            f"{point_name}.total_perf.{surf_name}_structural_mass",
        ):
            try:
                mass = float(np.sum(prob.get_val(mass_path)))
                summary[f"{surf_name}_structural_mass"] = mass
                break
            except Exception:
                pass
        # Failure index
        try:
            failure = float(np.max(prob.get_val(
                f"{point_name}.{surf_name}_perf.failure"
            )))
            summary[f"{surf_name}_failure"] = failure
        except Exception:
            pass

    return summary


def _record_failure(
    activity_id: str,
    run_id: str,
    plan_id: str,
    plan_entity_id: str,
    error_msg: str,
) -> None:
    """Record a failed run in the DB."""
    record_activity(
        activity_id=activity_id,
        activity_type="execute",
        agent="omd",
        completed_at=datetime.now(timezone.utc).isoformat(),
        status="failed",
    )
    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="omd",
        plan_id=plan_id,
    )
    add_prov_edge("wasGeneratedBy", run_id, activity_id)
