"""Plan execution: load, materialize, run, record.

Orchestrates the full pipeline from plan YAML to recorded results
in the analysis database with PROV-Agent provenance tracking.
"""

from __future__ import annotations

import json
import logging
import signal
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from hangar.omd.plan_schema import load_and_validate
from hangar.omd.materializer import materialize, apply_solvers_post_setup
from hangar.omd.recorder import import_recorder_data
from hangar.omd.db import (
    init_analysis_db,
    plan_store_dir,
    recordings_dir,
    n2_dir,
    record_entity,
    record_activity,
    add_prov_edge,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plan / result decomposition for rich provenance
# ---------------------------------------------------------------------------


def _decompose_plan(
    plan: dict,
    plan_entity_id: str,
    plan_id: str,
) -> None:
    """Extract sub-entities from a plan and persist them in the provenance DB.

    Creates surface_def, operating_point, solver_config, opt_setup, and
    decision entities as children of the plan entity.  Each sub-entity
    gets a ``wasDerivedFrom`` edge back to the plan entity so the
    provenance DAG renderer can display the decomposition.
    """
    sub_entity_ids: list[str] = []

    # Surfaces
    for comp in plan.get("components", []):
        for surf in comp.get("config", {}).get("surfaces", []):
            surf_name = surf.get("name", comp["id"])
            # Pick the fields worth showing; skip large arrays like mesh
            surf_meta = {}
            for k in ("name", "wing_type", "span", "root_chord", "num_x",
                       "num_y", "symmetry", "fem_model_type", "E", "G",
                       "yield_stress", "mrho", "with_viscous", "CD0",
                       "sweep", "dihedral", "taper"):
                if k in surf:
                    surf_meta[k] = surf[k]
            eid = f"{plan_entity_id}/surf/{surf_name}"
            record_entity(
                entity_id=eid,
                entity_type="surface_def",
                created_by="omd",
                plan_id=plan_id,
                metadata=json.dumps(surf_meta),
                parent_id=plan_entity_id,
            )
            sub_entity_ids.append(eid)

    # Operating points
    op = plan.get("operating_points")
    if op:
        if isinstance(op, dict) and "flight_points" in op:
            # Multipoint: record shared params + each flight point
            shared = op.get("shared", {})
            if shared:
                eid = f"{plan_entity_id}/op/shared"
                record_entity(
                    entity_id=eid,
                    entity_type="operating_point",
                    created_by="omd",
                    plan_id=plan_id,
                    metadata=json.dumps({"type": "shared", **shared}),
                    parent_id=plan_entity_id,
                )
                sub_entity_ids.append(eid)
            for idx, fp in enumerate(op["flight_points"]):
                label = fp.get("name", f"point_{idx}")
                eid = f"{plan_entity_id}/op/{label}"
                record_entity(
                    entity_id=eid,
                    entity_type="operating_point",
                    created_by="omd",
                    plan_id=plan_id,
                    metadata=json.dumps({"type": "flight_point", "index": idx, **fp}),
                    parent_id=plan_entity_id,
                )
                sub_entity_ids.append(eid)
        else:
            # Single-point
            eid = f"{plan_entity_id}/op"
            record_entity(
                entity_id=eid,
                entity_type="operating_point",
                created_by="omd",
                plan_id=plan_id,
                metadata=json.dumps(op),
                parent_id=plan_entity_id,
            )
            sub_entity_ids.append(eid)

    # Solvers
    solvers = plan.get("solvers")
    if solvers:
        solver_meta = {}
        nl = solvers.get("nonlinear", {})
        if nl:
            solver_meta["nonlinear_type"] = nl.get("type")
            solver_meta["nonlinear_options"] = nl.get("options", {})
        ln = solvers.get("linear", {})
        if ln:
            solver_meta["linear_type"] = ln.get("type")
        eid = f"{plan_entity_id}/solvers"
        record_entity(
            entity_id=eid,
            entity_type="solver_config",
            created_by="omd",
            plan_id=plan_id,
            metadata=json.dumps(solver_meta),
            parent_id=plan_entity_id,
        )
        sub_entity_ids.append(eid)

    # Optimization setup
    if plan.get("design_variables") or plan.get("objective"):
        opt_meta = {
            "optimizer_type": plan.get("optimizer", {}).get("type"),
            "optimizer_options": plan.get("optimizer", {}).get("options", {}),
            "objective": plan.get("objective"),
            "design_variables": plan.get("design_variables", []),
            "constraints": plan.get("constraints", []),
        }
        eid = f"{plan_entity_id}/opt"
        record_entity(
            entity_id=eid,
            entity_type="opt_setup",
            created_by="omd",
            plan_id=plan_id,
            metadata=json.dumps(opt_meta),
            parent_id=plan_entity_id,
        )
        sub_entity_ids.append(eid)

    # OCP-specific sub-entities: aircraft config, mission config, propulsion
    for comp in plan.get("components", []):
        comp_type = comp.get("type", "")
        if comp_type.startswith("ocp/"):
            config = comp.get("config", {})

            # Aircraft configuration
            template = config.get("aircraft_template")
            aircraft_meta = {"aircraft_template": template} if template else {}
            if aircraft_meta:
                eid = f"{plan_entity_id}/aircraft"
                record_entity(
                    entity_id=eid,
                    entity_type="aircraft_config",
                    created_by="omd",
                    plan_id=plan_id,
                    metadata=json.dumps(aircraft_meta),
                    parent_id=plan_entity_id,
                )
                sub_entity_ids.append(eid)

            # Mission configuration
            mission_params = config.get("mission_params", {})
            if mission_params:
                mission_meta = {
                    "mission_type": comp_type.replace("ocp/", ""),
                    "num_nodes": config.get("num_nodes"),
                    **mission_params,
                }
                eid = f"{plan_entity_id}/mission"
                record_entity(
                    entity_id=eid,
                    entity_type="mission_config",
                    created_by="omd",
                    plan_id=plan_id,
                    metadata=json.dumps(mission_meta),
                    parent_id=plan_entity_id,
                )
                sub_entity_ids.append(eid)

            # Propulsion configuration
            arch = config.get("architecture")
            if arch:
                eid = f"{plan_entity_id}/propulsion"
                record_entity(
                    entity_id=eid,
                    entity_type="propulsion_config",
                    created_by="omd",
                    plan_id=plan_id,
                    metadata=json.dumps({"architecture": arch}),
                    parent_id=plan_entity_id,
                )
                sub_entity_ids.append(eid)

    # Slot configurations
    for comp in plan.get("components", []):
        config = comp.get("config", {})
        slots = config.get("slots", {})
        comp_id = comp.get("id", "unknown")
        for slot_name, slot_cfg in slots.items():
            eid = f"{plan_entity_id}/slot/{comp_id}/{slot_name}"
            record_entity(
                entity_id=eid,
                entity_type="slot_config",
                created_by="omd",
                plan_id=plan_id,
                metadata=json.dumps({
                    "component_id": comp_id,
                    "slot_name": slot_name,
                    "provider": slot_cfg.get("provider"),
                    "config": slot_cfg.get("config", {}),
                }),
                parent_id=plan_entity_id,
            )
            sub_entity_ids.append(eid)

    # Link all sub-entities to the plan entity
    for sub_id in sub_entity_ids:
        add_prov_edge("wasDerivedFrom", sub_id, plan_entity_id)

    # Decisions are recorded during assembly (assemble.py _record_decisions)
    # so we skip them here to avoid duplicates.


@contextmanager
def _wallclock_timeout(seconds: int | None):
    """Context manager that raises TimeoutError after *seconds* wallclock time.

    Uses SIGALRM on Unix. If *seconds* is None, no timeout is applied.
    """
    if seconds is None:
        yield
        return

    def _handler(signum, frame):
        raise TimeoutError(
            f"Execution exceeded wallclock limit of {seconds}s"
        )

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(int(seconds))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def run_plan(
    plan_path: Path,
    mode: str = "analysis",
    recording_level: str = "driver",
    db_path: Path | None = None,
    timeout_seconds: int | None = None,
    compute_stab: bool = False,
) -> dict:
    """Load, materialize, execute, and record an analysis plan.

    Args:
        plan_path: Path to assembled plan.yaml.
        mode: "analysis" (run_model) or "optimize" (run_driver).
        recording_level: "minimal", "driver", "solver", or "full".
        db_path: Path to analysis DB. If None, uses default.
        timeout_seconds: Wallclock timeout in seconds. If None, uses
            the plan's optimizer.options.timeout_seconds, or no limit.

    Returns:
        Structured result dict with:
        - run_id: unique identifier
        - status: "converged" | "failed" | "completed" | "timeout"
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

    # Record plan entity -- ensure plan is always stored in the plan store
    content_hash = plan.get("metadata", {}).get("content_hash")
    store_path = plan_store_dir() / plan_id / f"v{plan_version}.yaml"
    if not store_path.exists():
        # Copy plan to the store so the artifact is preserved even if the
        # original file is in a temp directory or gets cleaned up.
        import shutil
        store_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan_path, store_path)
        logger.info("Copied plan to store: %s", store_path)
    plan_storage_ref = str(store_path)
    record_entity(
        entity_id=plan_entity_id,
        entity_type="plan",
        created_by="have-agent",
        plan_id=plan_id,
        version=plan_version,
        content_hash=content_hash,
        storage_ref=plan_storage_ref,
    )

    # Decompose plan into sub-entities for rich provenance
    _decompose_plan(plan, plan_entity_id, plan_id)

    # Replan provenance: link to parent version if this is a revision
    parent_version = plan.get("metadata", {}).get("parent_version")
    if parent_version:
        parent_entity_id = f"{plan_id}/v{parent_version}"
        add_prov_edge("wasDerivedFrom", plan_entity_id, parent_entity_id)

        # Record an explicit replan activity bridging the two versions
        replan_activity_id = f"act-replan-{plan_entity_id}"
        record_activity(
            activity_id=replan_activity_id,
            activity_type="replan",
            agent="have-agent",
            status="completed",
        )
        add_prov_edge("used", replan_activity_id, parent_entity_id)
        add_prov_edge("wasGeneratedBy", plan_entity_id, replan_activity_id)

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

    # Resolve timeout: CLI flag > plan YAML > default (none)
    if timeout_seconds is None:
        timeout_seconds = (
            plan.get("optimizer", {}).get("options", {}).get("timeout_seconds")
        )

    # Execute
    try:
        with _wallclock_timeout(timeout_seconds):
            if mode == "optimize":
                prob.run_driver()
            else:
                prob.run_model()

        try:
            prob.record("final")
        except Exception as exc:
            logger.warning("Failed to record final case: %s", exc)

        # Generate N2 diagram while problem is still live
        _generate_n2(prob, run_id)

        # Stability derivatives (optional, before cleanup)
        stab_results = None
        if compute_stab:
            try:
                from hangar.omd.stability import compute_stability
                stab_results = compute_stability(prob, metadata)
            except Exception as exc:
                logger.warning("Stability computation failed: %s", exc)

        # Extract model graph and solver info while problem is live
        model_graph = _extract_model_graph(prob)
        solver_info = _extract_solver_info(prob, metadata)

        # Build discipline graph for the problem DAG view
        component_type = None
        components = plan.get("components", [])
        if components:
            component_type = components[0].get("type")

        from hangar.omd.discipline_graph import build_discipline_graph
        discipline_graph = build_discipline_graph(
            component_type or "",
            metadata=metadata,
            solver_info=solver_info,
        )

        # Extract slot results and summary excerpt while prob is live
        # (needed for the model_structure entity and problem DAG)
        slots_summary: dict = {}
        summary_excerpt: dict = {}
        if metadata.get("component_family") == "ocp":
            active_slots = metadata.get("active_slots", {})
            if active_slots:
                phases = metadata.get("phases", ["climb", "cruise", "descent"])
                slots_summary = _extract_slot_results(
                    prob, active_slots, phases, comp_prefix=""
                )
            # Key mission metrics for problem DAG display
            try:
                import numpy as np
                phases = metadata.get("phases", ["climb", "cruise", "descent"])
                for phase in reversed(phases):
                    try:
                        val = prob.get_val(f"{phase}.fuel_used_final")
                        summary_excerpt["fuel_burn_kg"] = float(
                            np.atleast_1d(val).flat[0]
                        )
                        break
                    except Exception:
                        continue
                try:
                    oew = prob.get_val("climb.OEW", units="kg")
                    summary_excerpt["OEW_kg"] = float(
                        np.atleast_1d(oew).flat[0]
                    )
                except Exception:
                    pass
                try:
                    mtow = prob.get_val("ac|weights|MTOW", units="kg")
                    summary_excerpt["MTOW_kg"] = float(
                        np.atleast_1d(mtow).flat[0]
                    )
                except Exception:
                    pass
            except Exception:
                pass

        # Record model structure as a sub-entity of the run
        n2_path = n2_dir() / f"{run_id}.html"
        if n2_path.exists():
            model_meta = {
                "component_type": component_type,
                "model_graph": model_graph,
                "discipline_graph": discipline_graph,
                "solver_info": solver_info,
                "slot_results": slots_summary,
                "run_summary": summary_excerpt,
            }
            record_entity(
                entity_id=f"{run_id}/n2",
                entity_type="model_structure",
                created_by="omd",
                plan_id=plan_id,
                storage_ref=str(n2_path),
                metadata=json.dumps(model_meta, default=str),
                parent_id=run_id,
            )

        prob.cleanup()
    except TimeoutError as exc:
        prob.cleanup()
        msg = str(exc) or f"Wallclock timeout after {timeout_seconds}s"
        logger.warning("Run %s timed out: %s", run_id, msg)
        _record_failure(activity_id, run_id, plan_id, plan_entity_id, msg)
        return {
            "run_id": run_id,
            "status": "timeout",
            "summary": {},
            "errors": [{"path": "execute", "message": msg}],
        }
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
    if stab_results:
        summary["stability"] = stab_results

    # Determine status
    status = "completed"
    if mode == "optimize":
        try:
            if hasattr(prob.driver, "result") and prob.driver.result is not None:
                status = "converged" if prob.driver.result.success else "failed"
        except Exception:
            pass

    # Record run entity with component type metadata
    components = plan.get("components", [])
    component_type = components[0].get("type") if components else None
    run_meta_dict: dict = {}
    if component_type:
        run_meta_dict["component_type"] = component_type
    if len(components) > 1:
        run_meta_dict["component_types"] = {
            c["id"]: c["type"] for c in components
        }
    # Store slot provider types so the plot system can merge providers
    slots_cfg = (components[0].get("config", {}).get("slots", {})
                 if components else {})
    if slots_cfg:
        run_meta_dict["slot_providers"] = {
            slot_name: cfg.get("provider", "")
            for slot_name, cfg in slots_cfg.items()
        }
    run_metadata = json.dumps(run_meta_dict) if run_meta_dict else None

    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="omd",
        plan_id=plan_id,
        storage_ref=str(recorder_path) if recorder_path else None,
        metadata=run_metadata,
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

    # Record assessment entity with convergence metadata
    _record_assessment(run_id, plan_id, status, mode, summary, recorder_info)

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


def _extract_solver_info(prob, metadata: dict) -> dict:
    """Extract solver iteration info from a solved OpenMDAO Problem."""
    info: dict = {}
    point_names = metadata.get("point_names")
    if point_names is None:
        point_names = [metadata.get("point_name", "AS_point_0")]

    for point_name in point_names:
        try:
            coupled = prob.model._get_subsystem(f"{point_name}.coupled")
            if coupled is not None:
                nl = coupled.nonlinear_solver
                key_prefix = f"{point_name}." if len(point_names) > 1 else ""
                info[f"{key_prefix}solver_type"] = type(nl).__name__
                if hasattr(nl, "_iter_count"):
                    info[f"{key_prefix}iterations"] = nl._iter_count
                info[f"{key_prefix}convergence_status"] = "converged"
        except Exception:
            pass

    # Check if optimization ran
    try:
        if hasattr(prob.driver, "result") and prob.driver.result is not None:
            result = prob.driver.result
            info["optimizer_converged"] = result.success
            info["optimizer_iterations"] = getattr(result, "nit", None)
    except Exception:
        pass

    return info


def _extract_model_graph(prob) -> dict:
    """Extract a simplified group/variable graph from a live OpenMDAO Problem.

    Walks the top-level subsystems and one level of children for Groups.
    Returns a JSON-serializable dict with groups and connections.
    """
    import openmdao.api as om

    groups = []
    for system in prob.model.system_iter(include_self=False, recurse=False):
        node = {
            "name": system.name,
            "type": type(system).__name__,
            "pathname": system.pathname,
        }
        # Get promoted outputs (limit to key variables, skip internal)
        try:
            io_meta = system.get_io_metadata(iotypes=("output",), get_remote=False)
            outputs = [name.split(".")[-1] for name in io_meta.keys()]
            # Filter to interesting outputs (skip very internal ones)
            node["outputs"] = outputs[:20]
        except Exception:
            node["outputs"] = []

        try:
            io_meta = system.get_io_metadata(iotypes=("input",), get_remote=False)
            inputs = [name.split(".")[-1] for name in io_meta.keys()]
            node["inputs"] = inputs[:20]
        except Exception:
            node["inputs"] = []

        # One level of children for Groups
        if isinstance(system, om.Group):
            children = []
            for child in system.system_iter(include_self=False, recurse=False):
                children.append({
                    "name": child.name,
                    "type": type(child).__name__,
                    "pathname": child.pathname,
                })
            node["children"] = children

        groups.append(node)

    # Extract connections from the global connection map
    connections = []
    try:
        conn_map = prob.model._conn_global_abs_in2out
        for tgt, src in conn_map.items():
            # src may be a string or a tuple depending on OpenMDAO version
            if isinstance(src, tuple):
                src = src[0]
            connections.append({"src": src, "tgt": tgt})
    except Exception:
        pass

    return {"groups": groups, "connections": connections}


def _generate_run_id() -> str:
    """Generate a sortable, collision-resistant run ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"run-{ts}-{suffix}"


def _extract_summary(prob, metadata: dict, mode: str) -> dict:
    """Extract key results from a solved problem."""
    import numpy as np

    # Dispatch to OCP-specific extraction
    if metadata.get("component_family") == "ocp":
        return _extract_ocp_summary(prob, metadata, mode)

    # Composite plan: extract per-component results
    if metadata.get("_composite"):
        return _extract_composite_summary(prob, metadata, mode)

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

    # For multipoint, extract per-point results
    if metadata.get("multipoint"):
        point_names = metadata.get("point_names", [point_name])
        point_labels = metadata.get("point_labels", [])
        points_summary = {}
        for idx, pt in enumerate(point_names):
            label = point_labels[idx] if idx < len(point_labels) else pt
            pt_data = _extract_point_summary(prob, pt, metadata, np)
            points_summary[label] = pt_data
        summary["points"] = points_summary
        # Top-level values from point 0 for backwards compat
        if points_summary:
            first = next(iter(points_summary.values()))
            for key in ("CL", "CD", "L_over_D"):
                if key in first:
                    summary[key] = first[key]
            for surf_name in metadata.get("surface_names", []):
                for skey in (f"{surf_name}_structural_mass_kg",
                             f"{surf_name}_failure"):
                    if skey in first:
                        summary[skey] = first[skey]
    else:
        # Single-point extraction
        pt_data = _extract_point_summary(prob, point_name, metadata, np)
        summary.update(pt_data)

    return summary


# Per-phase profile variables to extract from OCP missions.
# Maps output key -> (OpenMDAO variable name, units).
_OCP_PROFILE_VARS: dict[str, tuple[str, str | None]] = {
    "altitude_m": ("fltcond|h", "m"),
    "velocity_ms": ("fltcond|Utrue", "m/s"),
    "mach": ("fltcond|M", None),
    "thrust_kN": ("thrust", "kN"),
    "drag_N": ("drag", "N"),
    "fuel_flow_kgs": ("fuel_flow", "kg/s"),
    "weight_kg": ("weight", "kg"),
}


def _extract_ocp_profiles(prob, phases: list[str], prefix: str = "") -> dict:
    """Extract per-phase profile arrays from a solved OCP mission.

    Parameters
    ----------
    prob : om.Problem
        Solved OpenMDAO problem.
    phases : list[str]
        Phase names (e.g. ["climb", "cruise", "descent"]).
    prefix : str
        Optional prefix for composite problems (e.g. "mission.").

    Returns
    -------
    dict
        ``{phase: {key: [values], ...}, ...}`` or empty if nothing found.
    """
    import numpy as np

    profiles: dict = {}
    for phase in phases:
        phase_data: dict = {}
        for key, (var, units) in _OCP_PROFILE_VARS.items():
            path = f"{prefix}{phase}.{var}"
            try:
                if units:
                    val = prob.get_val(path, units=units)
                else:
                    val = prob.get_val(path)
                phase_data[key] = np.atleast_1d(val).tolist()
            except (KeyError, Exception):
                pass
        if phase_data:
            profiles[phase] = phase_data
    return profiles


_SLOT_SUBSYS_MAP = {"propulsion": "propmodel", "drag": "drag", "weight": "weight"}


def _extract_slot_results(
    prob, active_slots: dict, phases: list[str], comp_prefix: str = ""
) -> dict:
    """Extract per-slot results from an OCP problem with slot providers.

    Parameters
    ----------
    prob : om.Problem
        Solved problem.
    active_slots : dict
        Slot config from the plan (e.g. {"drag": {"provider": "oas/vlm", ...}}).
    phases : list[str]
        OCP phase names.
    comp_prefix : str
        Path prefix for composite problems (e.g. "mission."). Empty for
        single-component problems.
    """
    import numpy as np

    first_phase = phases[0] if phases else "climb"
    slots_summary: dict = {}
    for slot_name, slot_cfg in active_slots.items():
        provider_name = slot_cfg.get("provider", "")
        slot_data: dict = {"provider": provider_name}
        try:
            from hangar.omd.slots import get_slot_provider
            provider_fn = get_slot_provider(provider_name)
            result_paths = getattr(provider_fn, "result_paths", {})
        except Exception:
            result_paths = {}
        subsys = _SLOT_SUBSYS_MAP.get(slot_name, slot_name)
        for var_name, internal_path in result_paths.items():
            for path_template in (
                f"{comp_prefix}{first_phase}.{internal_path}",
                f"{comp_prefix}{first_phase}.acmodel.{subsys}.{internal_path}",
                f"{comp_prefix}{first_phase}.{subsys}.{internal_path}",
            ):
                try:
                    val = prob.get_val(path_template)
                    slot_data[var_name] = float(
                        np.atleast_1d(val).flat[0]
                    )
                    break
                except Exception:
                    continue
        if len(slot_data) > 1:  # more than just "provider"
            slots_summary[slot_name] = slot_data
    return slots_summary


def _extract_ocp_summary(prob, metadata: dict, mode: str) -> dict:
    """Extract key results from a solved OpenConcept mission problem."""
    import numpy as np

    summary: dict = {"mode": mode}

    def _safe_get(path: str, units: str | None = None) -> float | None:
        try:
            if units:
                val = prob.get_val(path, units=units)
            else:
                val = prob.get_val(path)
            return float(np.atleast_1d(val).flat[0])
        except (KeyError, Exception):
            return None

    # Fuel burn from last flight phase
    phases = metadata.get("phases", ["climb", "cruise", "descent"])
    for phase in reversed(phases):
        val = _safe_get(f"{phase}.fuel_used_final")
        if val is not None:
            summary["fuel_burn_kg"] = val
            break

    # OEW (OpenConcept weight model outputs in lb, convert to kg)
    oew = _safe_get("climb.OEW", units="kg")
    if oew is not None:
        summary["OEW_kg"] = oew

    # MTOW
    mtow = _safe_get("ac|weights|MTOW", units="kg")
    if mtow is not None:
        summary["MTOW_kg"] = mtow

    # TOFL (full mission only)
    if metadata.get("has_takeoff"):
        tofl = _safe_get("rotate.range_final")
        if tofl is not None:
            summary["TOFL_m"] = tofl

    # Battery SOC (hybrid architectures)
    if metadata.get("has_battery"):
        for phase in reversed(phases):
            soc = _safe_get(f"{phase}.battery_SOC_final")
            if soc is not None:
                summary["battery_SOC_final"] = soc
                break

    # Architecture and mission info
    summary["architecture"] = metadata.get("architecture", "unknown")
    summary["mission_type"] = metadata.get("mission_type", "unknown")
    summary["num_nodes"] = metadata.get("num_nodes")

    # Per-phase profiles (altitude, speed, thrust, drag, etc.)
    profiles = _extract_ocp_profiles(prob, phases)
    if profiles:
        summary["profiles"] = profiles

    # Per-slot result extraction (single-component OCP with slots)
    active_slots = metadata.get("active_slots", {})
    if active_slots:
        slots_summary = _extract_slot_results(
            prob, active_slots, phases, comp_prefix=""
        )
        if slots_summary:
            summary["slots"] = slots_summary

    return summary


def _extract_composite_summary(prob, metadata: dict, mode: str) -> dict:
    """Extract results from a composite (multi-component) problem."""
    import numpy as np

    summary: dict = {"mode": mode, "_composite": True, "components": {}}

    for comp_id in metadata.get("component_ids", []):
        comp_meta = metadata.get("component_metadata", {}).get(comp_id, {})
        comp_type = metadata.get("component_types", {}).get(comp_id, "")
        comp_summary: dict = {}

        if comp_meta.get("component_family") == "ocp":
            # OCP: extract fuel burn, OEW, MTOW with component prefix
            def _safe_get(path, units=None):
                try:
                    full_path = f"{comp_id}.{path}"
                    if units:
                        val = prob.get_val(full_path, units=units)
                    else:
                        val = prob.get_val(full_path)
                    return float(np.atleast_1d(val).flat[0])
                except Exception:
                    return None

            phases = comp_meta.get("phases", ["climb", "cruise", "descent"])
            for phase in reversed(phases):
                val = _safe_get(f"{phase}.fuel_used_final")
                if val is not None:
                    comp_summary["fuel_burn_kg"] = val
                    break

            oew = _safe_get("climb.OEW", units="kg")
            if oew is not None:
                comp_summary["OEW_kg"] = oew

            mtow = _safe_get("ac|weights|MTOW", units="kg")
            if mtow is not None:
                comp_summary["MTOW_kg"] = mtow

            if comp_meta.get("has_takeoff"):
                tofl = _safe_get("rotate.range_final")
                if tofl is not None:
                    comp_summary["TOFL_m"] = tofl

            # Per-phase profiles
            comp_profiles = _extract_ocp_profiles(
                prob, phases, prefix=f"{comp_id}."
            )
            if comp_profiles:
                comp_summary["profiles"] = comp_profiles

        elif comp_type.startswith("oas/"):
            # OAS: extract CL, CD
            point_name = comp_meta.get("point_name", "aero_point_0")
            for var in ("CL", "CD"):
                try:
                    val = prob.get_val(f"{comp_id}.{point_name}.{var}")
                    comp_summary[var] = float(np.atleast_1d(val).flat[0])
                except Exception:
                    # Try surface-specific perf path
                    for surf in comp_meta.get("surface_names", []):
                        try:
                            val = prob.get_val(
                                f"{comp_id}.{point_name}.{surf}_perf.{var}"
                            )
                            comp_summary[var] = float(np.atleast_1d(val).flat[0])
                            break
                        except Exception:
                            pass
            cl = comp_summary.get("CL", 0)
            cd = comp_summary.get("CD", 1)
            if cd > 0:
                comp_summary["L_over_D"] = cl / cd

        else:
            # Generic: try output_names
            for output_name in comp_meta.get("output_names", []):
                try:
                    val = prob.get_val(f"{comp_id}.{output_name}")
                    key = output_name.split(".")[-1]
                    comp_summary[key] = float(
                        np.atleast_1d(val).flat[0]
                    )
                except Exception:
                    pass

        summary["components"][comp_id] = comp_summary

    # Per-slot result extraction
    for comp_id in metadata.get("component_ids", []):
        comp_meta = metadata.get("component_metadata", {}).get(comp_id, {})
        active_slots = comp_meta.get("active_slots", {})
        if not active_slots:
            continue
        phases = comp_meta.get("phases", ["climb", "cruise", "descent"])
        slots_summary = _extract_slot_results(
            prob, active_slots, phases, comp_prefix=f"{comp_id}."
        )
        if slots_summary:
            summary["slots"] = slots_summary

    return summary


def _extract_point_summary(
    prob, point_name: str, metadata: dict, np,
) -> dict:
    """Extract aero/struct results for a single analysis point."""
    data: dict = {}

    try:
        data["CL"] = float(prob.get_val(f"{point_name}.CL")[0])
    except Exception:
        pass
    try:
        data["CD"] = float(prob.get_val(f"{point_name}.CD")[0])
    except Exception:
        pass
    try:
        cl = data.get("CL", 0)
        cd = data.get("CD", 1)
        if cd > 0:
            data["L_over_D"] = cl / cd
    except Exception:
        pass

    # Fuelburn (aerostruct)
    try:
        data["fuelburn"] = float(prob.get_val(f"{point_name}.fuelburn")[0])
    except Exception:
        pass

    # Wing area (S_ref)
    for surf_name in metadata.get("surface_names", []):
        try:
            s_ref = float(prob.get_val(
                f"{point_name}.{surf_name}.S_ref", units="m**2"
            )[0])
            data[f"{surf_name}_S_ref_m2"] = s_ref
        except Exception:
            pass

    # Surface-specific results
    for surf_name in metadata.get("surface_names", []):
        for mass_path in (
            f"{surf_name}.structural_mass",
            f"{point_name}.total_perf.{surf_name}_structural_mass",
        ):
            try:
                mass = float(np.sum(prob.get_val(mass_path, units="kg")))
                data[f"{surf_name}_structural_mass_kg"] = mass
                break
            except Exception:
                pass
        try:
            failure = float(np.max(prob.get_val(
                f"{point_name}.{surf_name}_perf.failure"
            )))
            data[f"{surf_name}_failure"] = failure
        except Exception:
            pass

    return data


def _generate_n2(prob, run_id: str) -> None:
    """Generate an N2 (Design Structure Matrix) HTML diagram.

    Called while the OpenMDAO Problem is still live (before cleanup).
    Saves to hangar_data/omd/n2/{run_id}.html.
    """
    try:
        import openmdao.api as om

        out = n2_dir()
        out.mkdir(parents=True, exist_ok=True)
        html_path = out / f"{run_id}.html"
        om.n2(prob, outfile=str(html_path), show_browser=False, title=run_id)
        logger.info("N2 diagram saved to %s", html_path)
    except Exception as exc:
        logger.warning("Failed to generate N2 diagram: %s", exc)


def _record_assessment(
    run_id: str,
    plan_id: str,
    status: str,
    mode: str,
    summary: dict,
    recorder_info: dict | None = None,
) -> None:
    """Record an assessment entity and assess activity for a completed run.

    Creates an assess activity that used the run record, and an assessment
    entity with convergence metadata that appears in the provenance DAG.
    """
    assess_activity_id = f"act-assess-{run_id}"
    assessment_id = f"assessment-{run_id}"

    # Build assessment metadata
    assess_meta = {
        "status": status,
        "mode": mode,
    }
    if recorder_info:
        assess_meta["case_count"] = recorder_info.get("case_count", 0)
    # Pull key scalars from summary (OAS)
    for key in ("CL", "CD", "L_over_D"):
        if key in summary:
            assess_meta[key] = summary[key]
    # OCP scalars
    for key in ("fuel_burn_kg", "OEW_kg", "MTOW_kg", "TOFL_m", "battery_SOC_final"):
        if key in summary:
            assess_meta[key] = summary[key]
    # Slot results
    if "slots" in summary:
        assess_meta["slots"] = summary["slots"]
    # Composite: include per-component summaries
    if "components" in summary:
        assess_meta["components"] = summary["components"]

    record_activity(
        activity_id=assess_activity_id,
        activity_type="assess",
        agent="omd",
        status="completed",
    )

    record_entity(
        entity_id=assessment_id,
        entity_type="assessment",
        created_by="omd",
        plan_id=plan_id,
        metadata=json.dumps(assess_meta),
    )

    # Provenance edges: assess activity used the run, assessment was generated by it
    add_prov_edge("used", assess_activity_id, run_id)
    add_prov_edge("wasGeneratedBy", assessment_id, assess_activity_id)

    # Decompose results into sub-entities under the run
    aero_keys = {k: summary[k] for k in ("CL", "CD", "L_over_D") if k in summary}
    if aero_keys:
        record_entity(
            entity_id=f"{run_id}/aero",
            entity_type="aero_results",
            created_by="omd",
            plan_id=plan_id,
            metadata=json.dumps(aero_keys),
            parent_id=run_id,
        )

    # OCP mission results sub-entity
    ocp_keys = {k: summary[k] for k in
                ("fuel_burn_kg", "OEW_kg", "MTOW_kg", "TOFL_m", "battery_SOC_final")
                if k in summary}
    if ocp_keys:
        record_entity(
            entity_id=f"{run_id}/mission_results",
            entity_type="mission_results",
            created_by="omd",
            plan_id=plan_id,
            metadata=json.dumps(ocp_keys),
            parent_id=run_id,
        )

    struct_keys = {k: summary[k] for k in summary
                   if "structural_mass" in k or "failure" in k}
    if struct_keys:
        record_entity(
            entity_id=f"{run_id}/struct",
            entity_type="struct_results",
            created_by="omd",
            plan_id=plan_id,
            metadata=json.dumps(struct_keys),
            parent_id=run_id,
        )

    conv_meta = {"status": status, "mode": mode}
    if recorder_info:
        conv_meta["case_count"] = recorder_info.get("case_count", 0)
        conv_meta["storage_bytes"] = recorder_info.get("storage_bytes", 0)
    record_entity(
        entity_id=f"{run_id}/conv",
        entity_type="convergence_info",
        created_by="omd",
        plan_id=plan_id,
        metadata=json.dumps(conv_meta),
        parent_id=run_id,
    )

    # Per-slot result entities
    if "slots" in summary:
        for slot_name, slot_data in summary["slots"].items():
            record_entity(
                entity_id=f"{run_id}/slot/{slot_name}",
                entity_type="slot_results",
                created_by="omd",
                plan_id=plan_id,
                metadata=json.dumps(slot_data),
                parent_id=run_id,
            )


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

    # Record a failed assessment
    _record_assessment(
        run_id, plan_id, status="failed", mode="unknown",
        summary={"error": error_msg},
    )
