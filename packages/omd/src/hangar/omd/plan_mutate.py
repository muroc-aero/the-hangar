"""Mutation primitives for interactive plan authoring.

These primitives operate on a modular YAML plan directory (the same
layout consumed by :mod:`hangar.omd.assemble`). Each primitive:

1. Loads the relevant section files from disk.
2. Applies the requested change.
3. Validates the resulting partial plan with
   :func:`hangar.omd.plan_schema.validate_partial`.
4. Writes the section file back.
5. Optionally records the rationale as a structured entry in
   ``decisions.yaml``.

This module deliberately avoids pulling in OpenMDAO or any factory
runtime imports. Short-name validation for design variables uses a
static map (:data:`_FACTORY_DV_SHORT_NAMES`) that mirrors the
``var_paths`` lists in the corresponding factory sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from hangar.omd.plan_schema import (
    RECOMMENDED_DECISION_STAGES,
    validate_partial,
)
from hangar.sdk.errors import UserInputError


# ---------------------------------------------------------------------------
# Static metadata
# ---------------------------------------------------------------------------

# Short DV / objective / constraint names registered by each factory.
# Mirrors:
#   - packages/omd/src/hangar/omd/factories/oas.py:524-540 (AerostructPoint)
#   - packages/omd/src/hangar/omd/factories/oas_aero.py:192-200 (AeroPoint)
# Keep this in sync with those files by hand. The constant is used for
# fast input validation without importing OpenMDAO factories.
_FACTORY_DV_SHORT_NAMES: dict[str, frozenset[str]] = {
    "oas/AerostructPoint": frozenset({
        "twist_cp",
        "thickness_cp",
        "chord_cp",
        "spar_thickness_cp",
        "skin_thickness_cp",
        "t_over_c_cp",
        "S_ref",
        "structural_mass",
        "CL",
        "CD",
        "CDi",
        "CDv",
        "CDw",
        "CM",
        "failure",
        "tsaiwu_sr",
        "L_equals_W",
        "fuelburn",
    }),
    "oas/AeroPoint": frozenset({
        "twist_cp",
        "chord_cp",
        "t_over_c_cp",
        "S_ref",
        "CL",
        "CD",
        "CDi",
        "CDv",
        "CDw",
        "CM",
    }),
}

# Each mutation primitive maps to a recommended decision stage. All
# values must appear in RECOMMENDED_DECISION_STAGES.
_STAGE_FOR_PRIMITIVE: dict[str, str] = {
    "add_component": "component_selection",
    "add_requirement": "problem_definition",
    "add_dv": "dv_setup",
    "add_shared_var": "dv_setup",
    "set_objective": "objective_selection",
    "set_operating_point": "operating_point_selection",
    "set_solver": "solver_selection",
    "set_analysis_strategy": "formulation",
}


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def _load_section(plan_dir: Path, stem: str, key: str) -> Any:
    """Load a modular section file, auto-unwrapping a top-level key.

    Mirrors the unwrap rule in ``assemble._merge_yaml_files`` so that
    files authored either as ``key: [...]`` or as a bare list/mapping
    round-trip correctly.
    """
    data = _load_yaml(plan_dir / f"{stem}.yaml")
    if data is None:
        return None
    if isinstance(data, dict) and len(data) == 1 and key in data:
        return data[key]
    return data


def _require_plan_dir(plan_dir: Path) -> None:
    if not plan_dir.is_dir():
        raise FileNotFoundError(f"plan_dir does not exist: {plan_dir}")
    if not (plan_dir / "metadata.yaml").exists():
        raise UserInputError(
            f"plan_dir not initialized: {plan_dir} (run "
            "`omd-cli plan init` first)"
        )


# ---------------------------------------------------------------------------
# Partial-plan load
# ---------------------------------------------------------------------------

# Modular-file stem -> top-level plan key. Mirrors
# hangar.omd.assemble._STEM_TO_KEY. Duplicated here so plan_mutate does
# not import from assemble (keeps the read path trivial).
_STEM_TO_KEY: dict[str, str] = {
    "metadata": "metadata",
    "requirements": "requirements",
    "operating_points": "operating_points",
    "connections": "connections",
    "shared_vars": "shared_vars",
    "solvers": "solvers",
    "decisions": "decisions",
    "rationale": "rationale",
    "analysis_plan": "analysis_plan",
}

_OPTIMIZATION_KEYS: frozenset[str] = frozenset(
    {"design_variables", "constraints", "objective", "optimizer"}
)


def load_partial(plan_dir: Path) -> dict:
    """Read a plan directory without enforcing full-schema validity.

    Returns whatever sections are present. Does not allocate a version
    or write history. Intended for in-progress authoring.
    """
    plan_dir = Path(plan_dir)
    plan: dict = {}

    for stem, key in _STEM_TO_KEY.items():
        val = _load_section(plan_dir, stem, key)
        if val is not None:
            plan[key] = val

    opt = _load_yaml(plan_dir / "optimization.yaml")
    if isinstance(opt, dict):
        for key in _OPTIMIZATION_KEYS:
            if key in opt:
                plan[key] = opt[key]

    comp_dir = plan_dir / "components"
    if comp_dir.is_dir():
        components: list = []
        for comp_path in sorted(comp_dir.glob("*.yaml")):
            comp_data = _load_yaml(comp_path)
            if comp_data is None:
                continue
            if isinstance(comp_data, list):
                components.extend(comp_data)
            else:
                components.append(comp_data)
        if components:
            plan["components"] = components

    return plan


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_partial(plan_dir: Path) -> None:
    """Validate the current on-disk partial plan; raise on errors."""
    plan = load_partial(plan_dir)
    errors = validate_partial(plan)
    if errors:
        summary = "; ".join(
            f"{e['path']}: {e['message']}" for e in errors[:5]
        )
        raise UserInputError(
            f"Partial plan failed schema validation: {summary}",
            details={"errors": errors},
        )


def _collect_var_paths(plan_dir: Path) -> set[str]:
    """Union of short DV names across components declared in the plan.

    Returns ``set()`` if no components are declared or none of the
    declared types appear in :data:`_FACTORY_DV_SHORT_NAMES`. Callers
    should treat an empty set as "no strict-name validation available"
    rather than "no names are valid".
    """
    plan = load_partial(plan_dir)
    names: set[str] = set()
    for comp in plan.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        comp_type = comp.get("type")
        short_names = _FACTORY_DV_SHORT_NAMES.get(comp_type)
        if short_names:
            names |= short_names
    return names


# ---------------------------------------------------------------------------
# Decision capture hook
# ---------------------------------------------------------------------------

def _next_auto_decision_id(decisions: list) -> str:
    existing = {
        d.get("id") for d in decisions
        if isinstance(d, dict) and isinstance(d.get("id"), str)
    }
    n = 1
    while f"dec-auto-{n}" in existing:
        n += 1
    return f"dec-auto-{n}"


def _capture_decision(
    plan_dir: Path,
    *,
    primitive: str,
    rationale: str | None,
    summary: str,
    element_path: str | None,
) -> None:
    """Append a structured decision entry if ``rationale`` is set."""
    if not rationale:
        return
    stage = _STAGE_FOR_PRIMITIVE.get(primitive, "formulation")
    decisions = _load_section(plan_dir, "decisions", "decisions") or []
    if not isinstance(decisions, list):
        raise UserInputError(
            "decisions.yaml exists but is not a list/sequence"
        )
    entry: dict[str, Any] = {
        "id": _next_auto_decision_id(decisions),
        "stage": stage,
        "decision": summary,
        "rationale": rationale,
    }
    if element_path:
        entry["element_path"] = element_path
    decisions.append(entry)
    _write_yaml(plan_dir / "decisions.yaml", decisions)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def init_plan(
    plan_dir: Path,
    *,
    plan_id: str,
    name: str,
    description: str | None = None,
) -> dict:
    """Scaffold a plan directory with ``metadata.yaml`` only.

    Creates the directory if it does not exist. Overwrites an existing
    ``metadata.yaml`` — callers who want non-destructive behavior should
    check before calling.
    """
    plan_dir = Path(plan_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)

    if not plan_id:
        raise UserInputError("plan_id must be a non-empty string")
    if not name:
        raise UserInputError("name must be a non-empty string")

    metadata: dict[str, Any] = {
        "id": plan_id,
        "name": name,
        "version": 1,
    }
    if description:
        metadata["description"] = description

    _write_yaml(plan_dir / "metadata.yaml", metadata)
    _validate_partial(plan_dir)
    return metadata


def add_component(
    plan_dir: Path,
    *,
    comp_id: str,
    comp_type: str,
    config: dict,
    rationale: str | None = None,
    replace: bool = False,
) -> dict:
    """Write ``components/{comp_id}.yaml`` as a bare mapping.

    Refuses to overwrite an existing component unless ``replace=True``.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not comp_id:
        raise UserInputError("comp_id must be a non-empty string")
    if not comp_type:
        raise UserInputError("comp_type must be a non-empty string")
    if not isinstance(config, dict):
        raise UserInputError("config must be a mapping")

    comp_dir = plan_dir / "components"
    comp_dir.mkdir(exist_ok=True)
    target = comp_dir / f"{comp_id}.yaml"
    if target.exists() and not replace:
        raise UserInputError(
            f"component '{comp_id}' already exists at {target} "
            "(pass replace=True to overwrite)"
        )

    component = {"id": comp_id, "type": comp_type, "config": config}
    _write_yaml(target, component)

    try:
        _validate_partial(plan_dir)
    except UserInputError:
        target.unlink(missing_ok=True)
        raise

    _capture_decision(
        plan_dir,
        primitive="add_component",
        rationale=rationale,
        summary=f"Added component {comp_id} ({comp_type})",
        element_path=f"components[{comp_id}]",
    )
    return component


def add_requirement(
    plan_dir: Path,
    *,
    req: dict,
    rationale: str | None = None,
    replace: bool = False,
) -> dict:
    """Append a requirement to ``requirements.yaml``.

    The requirement must have at least ``id`` and ``text`` per the
    schema. Duplicate ids raise unless ``replace=True``.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not isinstance(req, dict):
        raise UserInputError("req must be a mapping")
    req_id = req.get("id")
    if not isinstance(req_id, str) or not req_id:
        raise UserInputError("req.id must be a non-empty string")
    if "text" not in req or not req["text"]:
        raise UserInputError("req.text must be a non-empty string")

    existing = _load_section(plan_dir, "requirements", "requirements") or []
    if not isinstance(existing, list):
        raise UserInputError("requirements.yaml must hold a list")

    idx = next(
        (i for i, r in enumerate(existing)
         if isinstance(r, dict) and r.get("id") == req_id),
        None,
    )
    if idx is not None and not replace:
        raise UserInputError(
            f"requirement '{req_id}' already exists "
            "(pass replace=True to overwrite)"
        )
    if idx is not None:
        existing[idx] = req
    else:
        existing.append(req)

    _write_yaml(plan_dir / "requirements.yaml", existing)
    _validate_partial(plan_dir)

    _capture_decision(
        plan_dir,
        primitive="add_requirement",
        rationale=rationale,
        summary=f"Added requirement {req_id}",
        element_path=f"requirements[{req_id}]",
    )
    return req


def add_dv(
    plan_dir: Path,
    *,
    name: str,
    lower: float,
    upper: float,
    scaler: float | None = None,
    units: str | None = None,
    rationale: str | None = None,
    replace: bool = False,
) -> dict:
    """Add a design variable to ``optimization.yaml``.

    Validates ``name`` against the short-name set of declared
    components. A prefixed form (``wing.twist_cp``) is accepted as long
    as the suffix after the final ``.`` matches a registered short
    name.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not name:
        raise UserInputError("name must be a non-empty string")

    allowed = _collect_var_paths(plan_dir)
    suffix = name.rsplit(".", 1)[-1]
    if allowed and suffix not in allowed:
        raise UserInputError(
            f"unknown DV short name '{name}'. Allowed for declared "
            f"components: {sorted(allowed)}"
        )

    if lower is None or upper is None:
        raise UserInputError("lower and upper bounds are required")
    if lower >= upper:
        raise UserInputError(
            f"lower ({lower}) must be strictly less than upper ({upper})"
        )

    opt = _load_yaml(plan_dir / "optimization.yaml") or {}
    if not isinstance(opt, dict):
        raise UserInputError("optimization.yaml must hold a mapping")
    dvs = opt.get("design_variables") or []
    if not isinstance(dvs, list):
        raise UserInputError("optimization.design_variables must be a list")

    dv: dict[str, Any] = {"name": name, "lower": lower, "upper": upper}
    if scaler is not None:
        dv["scaler"] = scaler
    if units is not None:
        dv["units"] = units

    idx = next(
        (i for i, d in enumerate(dvs)
         if isinstance(d, dict) and d.get("name") == name),
        None,
    )
    if idx is not None and not replace:
        raise UserInputError(
            f"design variable '{name}' already declared "
            "(pass replace=True to overwrite)"
        )
    if idx is not None:
        dvs[idx] = dv
    else:
        dvs.append(dv)

    opt["design_variables"] = dvs
    _write_yaml(plan_dir / "optimization.yaml", opt)
    _validate_partial(plan_dir)

    _capture_decision(
        plan_dir,
        primitive="add_dv",
        rationale=rationale,
        summary=f"DV {name} bounds [{lower}, {upper}]",
        element_path=f"design_variables[{name}]",
    )
    return dv


def set_objective(
    plan_dir: Path,
    *,
    name: str,
    scaler: float | None = None,
    units: str | None = None,
    rationale: str | None = None,
) -> dict:
    """Set the optimization objective in ``optimization.yaml``.

    Replaces any existing objective. Validates ``name`` against the
    short-name set of declared components (prefixed or bare).
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not name:
        raise UserInputError("name must be a non-empty string")

    allowed = _collect_var_paths(plan_dir)
    suffix = name.rsplit(".", 1)[-1]
    if allowed and suffix not in allowed:
        raise UserInputError(
            f"unknown objective name '{name}'. Allowed for declared "
            f"components: {sorted(allowed)}"
        )

    opt = _load_yaml(plan_dir / "optimization.yaml") or {}
    if not isinstance(opt, dict):
        raise UserInputError("optimization.yaml must hold a mapping")

    objective: dict[str, Any] = {"name": name}
    if scaler is not None:
        objective["scaler"] = scaler
    if units is not None:
        objective["units"] = units

    opt["objective"] = objective
    _write_yaml(plan_dir / "optimization.yaml", opt)
    _validate_partial(plan_dir)

    _capture_decision(
        plan_dir,
        primitive="set_objective",
        rationale=rationale,
        summary=f"Objective: minimize {name}",
        element_path="objective",
    )
    return objective


def add_decision(plan_dir: Path, *, decision: dict) -> dict:
    """Append a hand-authored decision entry to ``decisions.yaml``.

    Unlike the rationale hook on other primitives, this call bypasses
    :func:`_capture_decision` — the call itself *is* the decision. The
    entry is validated structurally via the partial schema.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not isinstance(decision, dict):
        raise UserInputError("decision must be a mapping")

    decisions = _load_section(plan_dir, "decisions", "decisions") or []
    if not isinstance(decisions, list):
        raise UserInputError("decisions.yaml must hold a list")

    if "id" not in decision:
        decision = {**decision, "id": _next_auto_decision_id(decisions)}

    decisions.append(decision)
    _write_yaml(plan_dir / "decisions.yaml", decisions)
    _validate_partial(plan_dir)
    return decision


def set_operating_point(
    plan_dir: Path,
    *,
    fields: dict,
    rationale: str | None = None,
) -> dict:
    """Merge ``fields`` into ``operating_points.yaml``.

    ``fields`` values may be bare numbers/strings/arrays or
    ``{"value": ..., "units": ...}`` objects. Existing keys are
    overwritten. Operating points are stored as a flat mapping matching
    the single-point schema.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not isinstance(fields, dict) or not fields:
        raise UserInputError("fields must be a non-empty mapping")

    current = _load_section(plan_dir, "operating_points", "operating_points") or {}
    if not isinstance(current, dict):
        raise UserInputError(
            "operating_points.yaml holds a multipoint structure; "
            "set_operating_point only updates single-point dicts"
        )

    current = {**current, **fields}
    _write_yaml(plan_dir / "operating_points.yaml", current)
    _validate_partial(plan_dir)

    _capture_decision(
        plan_dir,
        primitive="set_operating_point",
        rationale=rationale,
        summary=f"Operating point fields: {sorted(fields)}",
        element_path="operating_points",
    )
    return current


def set_solver(
    plan_dir: Path,
    *,
    nonlinear: str | None = None,
    linear: str | None = None,
    nonlinear_options: dict | None = None,
    linear_options: dict | None = None,
    rationale: str | None = None,
) -> dict:
    """Write ``solvers.yaml`` with the given solver types.

    Unspecified legs are left unchanged; call twice to set both.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if nonlinear is None and linear is None:
        raise UserInputError(
            "at least one of nonlinear / linear must be provided"
        )

    current = _load_section(plan_dir, "solvers", "solvers") or {}
    if not isinstance(current, dict):
        raise UserInputError("solvers.yaml must hold a mapping")

    if nonlinear is not None:
        block: dict[str, Any] = {"type": nonlinear}
        if nonlinear_options:
            block["options"] = nonlinear_options
        current["nonlinear"] = block
    if linear is not None:
        block = {"type": linear}
        if linear_options:
            block["options"] = linear_options
        current["linear"] = block

    _write_yaml(plan_dir / "solvers.yaml", current)
    _validate_partial(plan_dir)

    summary_parts: list[str] = []
    if nonlinear is not None:
        summary_parts.append(f"nonlinear={nonlinear}")
    if linear is not None:
        summary_parts.append(f"linear={linear}")
    _capture_decision(
        plan_dir,
        primitive="set_solver",
        rationale=rationale,
        summary="Solvers: " + ", ".join(summary_parts),
        element_path="solvers",
    )
    return current


def set_analysis_strategy(
    plan_dir: Path,
    *,
    phases: int,
    phase_id_prefix: str = "p",
    rationale: str | None = None,
) -> dict:
    """Scaffold ``analysis_plan.yaml`` with ``phases`` empty phases.

    Each phase gets ``{id, name, mode, depends_on, success_criteria}``
    pre-populated so the partial validator passes immediately. Phase
    ids are ``{prefix}{n}`` for ``n`` in ``1..phases``; ``depends_on``
    chains each phase to its predecessor.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not isinstance(phases, int) or phases < 1:
        raise UserInputError("phases must be a positive integer")
    if not phase_id_prefix:
        raise UserInputError("phase_id_prefix must be non-empty")

    phase_entries: list[dict[str, Any]] = []
    for n in range(1, phases + 1):
        pid = f"{phase_id_prefix}{n}"
        entry: dict[str, Any] = {
            "id": pid,
            "name": "TODO",
            "mode": "analysis",
            "depends_on": [],
            "success_criteria": [],
        }
        if phase_entries:
            entry["depends_on"] = [phase_entries[-1]["id"]]
        phase_entries.append(entry)

    analysis_plan = {"phases": phase_entries}
    _write_yaml(plan_dir / "analysis_plan.yaml", analysis_plan)
    _validate_partial(plan_dir)

    _capture_decision(
        plan_dir,
        primitive="set_analysis_strategy",
        rationale=rationale,
        summary=f"Scaffolded {phases} phases",
        element_path="analysis_plan",
    )
    return analysis_plan


def add_shared_var(
    plan_dir: Path,
    *,
    name: str,
    consumers: list[str],
    value: float | list[float] | None = None,
    units: str | None = None,
    rationale: str | None = None,
    replace: bool = False,
) -> dict:
    """Append an entry to ``shared_vars.yaml``.

    Each consumer must match a declared component id. Duplicate names
    are rejected unless ``replace`` is set.
    """
    plan_dir = Path(plan_dir)
    _require_plan_dir(plan_dir)

    if not name:
        raise UserInputError("name must be a non-empty string")
    if not consumers:
        raise UserInputError("consumers must be a non-empty list")

    plan = load_partial(plan_dir)
    known_ids = {
        c.get("id") for c in plan.get("components", []) or []
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    for cid in consumers:
        if not isinstance(cid, str) or not cid:
            raise UserInputError(
                f"consumer id must be a non-empty string (got {cid!r})"
            )
        if known_ids and cid not in known_ids:
            raise UserInputError(
                f"consumer '{cid}' does not match any declared component "
                f"id. Known: {sorted(known_ids)}"
            )

    existing = _load_section(plan_dir, "shared_vars", "shared_vars")
    if existing is None:
        shared_list: list = []
    elif isinstance(existing, list):
        shared_list = existing
    else:
        raise UserInputError(
            "shared_vars.yaml must be a list or {shared_vars: [...]}"
        )

    entry: dict[str, Any] = {"name": name, "consumers": list(consumers)}
    if value is not None:
        entry["value"] = value
    if units is not None:
        entry["units"] = units

    idx = next(
        (i for i, d in enumerate(shared_list)
         if isinstance(d, dict) and d.get("name") == name),
        None,
    )
    if idx is not None and not replace:
        raise UserInputError(
            f"shared_vars entry '{name}' already exists "
            "(pass replace=True to overwrite)"
        )
    if idx is not None:
        shared_list[idx] = entry
    else:
        shared_list.append(entry)

    _write_yaml(plan_dir / "shared_vars.yaml", shared_list)
    _validate_partial(plan_dir)

    _capture_decision(
        plan_dir,
        primitive="add_shared_var",
        rationale=rationale,
        summary=f"shared_var {name} consumers={list(consumers)}",
        element_path=f"shared_vars[{name}]",
    )
    return entry


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "RECOMMENDED_DECISION_STAGES",
    "add_component",
    "add_decision",
    "add_dv",
    "add_requirement",
    "add_shared_var",
    "init_plan",
    "load_partial",
    "set_analysis_strategy",
    "set_objective",
    "set_operating_point",
    "set_solver",
]
