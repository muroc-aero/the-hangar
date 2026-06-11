"""omd runner adapter for the SDK study layer.

Registers the ``"omd"`` runner with :mod:`hangar.sdk.study`. A case spec
for this runner:

.. code-block:: yaml

    plan: lane_b/fuel_mdo/plan.yaml   # base plan, relative to study.yaml
    mode: optimize                    # analysis | optimize
    recording_level: driver           # optional
    timeout_seconds: 1800             # optional
    set:                              # plan patches (filled by matrix bind
      components[mission].config.mission_params.mission_range_NM: 500.0
    initial:                          # per-DV initial values (warm start)
      cruise.hybridization: 0.05

Multistart presets (ctx["preset"]) carry the same ``set`` / ``initial``
shape and are applied on top of the case spec.

Each case materializes as a real plan artifact under the study store
(``cases/{case_id}/plan.yaml``) before running, so generated plans can be
reviewed without spending compute (see ``omd-cli study generate``). Output
columns are extracted from the run's final case in the analysis DB using
the study's ``outputs: [{name, path}]`` declarations; paths use the same
promoted-variable names the recorder stores (e.g. ``ac|weights|MTOW``,
``descent.fuel_used_final``).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from copy import deepcopy
from pathlib import Path

import yaml

from hangar.sdk.study import register_runner, set_by_path

logger = logging.getLogger(__name__)

_ID_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.\-]+")


def _fresh_db_connection() -> None:
    """Drop any sqlite connection inherited across a fork, then init.

    Study workers are forked from the orchestrator; an inherited sqlite
    connection must not be reused in the child. Rebinding the module's
    thread-local is child-only state, so the parent is unaffected.
    """
    import hangar.results_reader.db as rdb

    rdb._local = threading.local()
    from hangar.omd.db import init_analysis_db

    init_analysis_db()


def _case_plan_id(study_id: str, case_id: str) -> str:
    return _ID_SAFE_RE.sub("-", f"{study_id}--{case_id}")


def _resolve_base_plan(spec: dict, ctx: dict) -> Path:
    plan_ref = spec.get("plan")
    if not plan_ref:
        raise ValueError(
            "omd case spec needs a 'plan' (base plan path, relative to the "
            "study.yaml or absolute)")
    path = Path(plan_ref)
    if not path.is_absolute():
        study_dir = ctx.get("study_dir")
        candidates = [Path(study_dir) / path] if study_dir else []
        candidates.append(path)
        for cand in candidates:
            if cand.exists():
                return cand
        raise FileNotFoundError(
            f"base plan {plan_ref!r} not found (tried "
            f"{[str(c) for c in candidates]})")
    if not path.exists():
        raise FileNotFoundError(f"base plan not found: {path}")
    return path


def _build_case_plan(spec: dict, ctx: dict) -> dict:
    """Base plan + set patches + initial values + study metadata stamp."""
    base_path = _resolve_base_plan(spec, ctx)
    plan = yaml.safe_load(base_path.read_text()) or {}
    plan = deepcopy(plan)

    for path_expr, value in (spec.get("set") or {}).items():
        set_by_path(plan, path_expr, value)
    preset = ctx.get("preset") or {}
    for path_expr, value in (preset.get("set") or {}).items():
        set_by_path(plan, path_expr, value)

    # Warm starts / multistart brackets via the plan-level
    # design_variables[].initial mechanism (materializer applies them
    # after prob.setup()).
    initials = dict(spec.get("initial") or {})
    initials.update(preset.get("initial") or {})
    if initials:
        for dv in plan.get("design_variables", []):
            if dv.get("name") in initials:
                dv["initial"] = float(initials[dv["name"]])
        unknown = set(initials) - {
            dv.get("name") for dv in plan.get("design_variables", [])
        }
        if unknown:
            logger.warning(
                "case %s: initial values for non-DV names ignored: %s",
                ctx.get("case_id"), sorted(unknown))

    meta = plan.setdefault("metadata", {})
    meta["id"] = _case_plan_id(ctx["study_id"], ctx["case_id"])
    meta["version"] = int(ctx.get("study_version") or 1)
    meta["study"] = ctx["study_id"]
    meta["case_id"] = ctx["case_id"]
    meta.pop("content_hash", None)
    return plan


def generate_case(spec: dict, ctx: dict) -> Path:
    """Materialize the case's plan artifact (no run) and preflight it.

    Runs the schema + semantic validators so typos (unknown component
    types, unresolvable DV/constraint names, unbound axis paths that broke
    the plan shape) surface at generate/review time instead of mid-study.
    """
    plan = _build_case_plan(spec, ctx)

    from hangar.omd.plan_schema import validate_plan
    from hangar.omd.plan_validate import validate_plan_semantic
    from hangar.omd.registry import list_factories

    errors = validate_plan(plan)
    if errors:
        raise ValueError(f"case {ctx['case_id']!r} plan invalid: {errors}")
    findings = validate_plan_semantic(plan, registry_types=set(list_factories()))
    if findings:
        msgs = [f"{f.path}: {f.message}" for f in findings]
        raise ValueError(f"case {ctx['case_id']!r} plan semantic errors: {msgs}")

    preset_name = ctx.get("preset_name")
    fname = f"plan-{preset_name}.yaml" if preset_name else "plan.yaml"
    out = Path(ctx["artifact_dir"]) / fname
    out.write_text(yaml.safe_dump(plan, sort_keys=False))
    return out


def _record_study_provenance(run_id: str, ctx: dict) -> None:
    from hangar.omd.db import add_prov_edge, query_entity, record_entity

    study_entity_id = f"study-{ctx['study_id']}/v{ctx.get('study_version') or 1}"
    if query_entity(study_entity_id) is None:
        record_entity(
            entity_id=study_entity_id,
            entity_type="study",
            created_by="omd-study",
            plan_id=None,
            version=int(ctx.get("study_version") or 1),
            metadata=json.dumps({"study_id": ctx["study_id"]}),
        )
    add_prov_edge("partOf", run_id, study_entity_id)


def _extract_outputs(run_id: str, output_defs: list[dict]) -> dict:
    """Resolve declared output columns from the run's final case."""
    if not output_defs:
        return {}
    from hangar.omd.db import query_run_results, resolve_scalar

    final_data: dict = {}
    for case in query_run_results(run_id):
        if case.get("case_type") == "final":
            final_data = case.get("data") or {}
            break
    out: dict = {}
    for d in output_defs:
        val = resolve_scalar(final_data, d["path"]) if final_data else None
        out[d["name"]] = val
    return out


def run_case(spec: dict, ctx: dict) -> dict:
    """Run one study case through the omd plan pipeline."""
    _fresh_db_connection()

    plan_path = generate_case(spec, ctx)

    # Keep the plan store copy fresh: run_plan only copies when missing,
    # which would leave a stale artifact after a case definition changed
    # under the same study version.
    from hangar.omd.db import plan_store_dir

    plan = yaml.safe_load(plan_path.read_text())
    plan_id = plan["metadata"]["id"]
    version = plan["metadata"]["version"]
    store_path = plan_store_dir() / plan_id / f"v{version}.yaml"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan_path, store_path)

    from hangar.omd.run import run_plan

    result = run_plan(
        plan_path,
        mode=spec.get("mode", "analysis"),
        recording_level=spec.get("recording_level", "driver"),
        timeout_seconds=spec.get("timeout_seconds"),
    )

    run_id = result.get("run_id")
    status = result.get("status", "failed")
    error = None
    if result.get("errors"):
        error = "; ".join(
            f"{e.get('path')}: {e.get('message')}" for e in result["errors"]
        )[:500]

    outputs: dict = {}
    if run_id:
        try:
            outputs = _extract_outputs(run_id, ctx.get("outputs") or [])
        except Exception as exc:
            logger.warning("case %s: output extraction failed: %s",
                           ctx.get("case_id"), exc)
        try:
            _record_study_provenance(run_id, ctx)
        except Exception as exc:
            logger.warning("case %s: study provenance edge failed: %s",
                           ctx.get("case_id"), exc)

    return {
        "status": status,
        "run_ref": run_id,
        "outputs": outputs,
        "error": error,
        "artifacts": {"plan": str(plan_path)},
    }


register_runner("omd", run_case, generate_case=generate_case)
