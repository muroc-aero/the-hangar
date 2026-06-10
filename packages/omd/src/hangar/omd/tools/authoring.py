"""Plan authoring tools -- modular plan construction over MCP.

These wrap the same ``hangar.omd.plan_mutate`` primitives as the
``omd-cli plan`` subcommands, so MCP-only agents (claude.ai) can author
plans server-side without filesystem access. Relative ``plan_dir`` names
resolve into the omd workspace (``hangar_data/omd/workspace``).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from hangar.sdk.errors import UserInputError

from hangar.omd.tools._helpers import (
    resolve_plan_dir,
    resolve_plan_path,
    workspace_write_target,
)


async def write_plan(
    path: Annotated[str, "Target YAML path; relative paths land in the omd workspace"],
    content: Annotated[str, "Full YAML document to write"],
) -> dict:
    """Write a complete plan (or plan fragment) YAML file server-side.

    Direct-authoring alternative to the plan_* tools: compose the YAML
    yourself, write it, then validate_plan / run_plan it. Returns the
    resolved path to pass to those tools.
    """
    import yaml

    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise UserInputError(f"content is not valid YAML: {exc}") from exc

    target = workspace_write_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(target.write_text, content)
    return {"written": True, "path": str(target)}


async def read_plan(
    plan_path: Annotated[str, "Plan YAML path (workspace-relative or absolute)"],
) -> dict:
    """Read a plan YAML file back (workspace files or any server-side path)."""
    path = resolve_plan_path(plan_path)
    if path.is_dir():
        files = sorted(
            str(p.relative_to(path)) for p in path.rglob("*.yaml")
        )
        return {"path": str(path), "is_dir": True, "files": files}
    content = await asyncio.to_thread(path.read_text)
    return {"path": str(path), "is_dir": False, "content": content}


async def plan_init(
    plan_dir: Annotated[str, "Plan directory name (created in the workspace) or absolute path"],
    plan_id: Annotated[str, "Plan id (metadata.id), e.g. 'wing-opt-v1'"],
    name: Annotated[str, "Human-readable plan name"],
    description: Annotated[str | None, "Optional plan description"] = None,
) -> dict:
    """Scaffold a modular plan directory with metadata.yaml."""
    from hangar.omd.plan_mutate import init_plan

    target = resolve_plan_dir(plan_dir, create=True)
    metadata = await asyncio.to_thread(
        init_plan, target, plan_id=plan_id, name=name, description=description
    )
    return {"plan_dir": str(target), "metadata": metadata}


async def plan_add_component(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    comp_id: Annotated[str, "Component id, e.g. 'wing'"],
    comp_type: Annotated[str, "Factory type, e.g. 'oas/AerostructPoint' (see omd://reference)"],
    config: Annotated[dict, "Component config mapping forwarded to the factory"],
    rationale: Annotated[str | None, "Why this component/config (recorded as a plan decision)"] = None,
    replace: Annotated[bool, "Overwrite an existing component with the same id"] = False,
) -> dict:
    """Add a component to the plan (components/{comp_id}.yaml)."""
    from hangar.omd.plan_mutate import add_component

    target = resolve_plan_dir(plan_dir)
    component = await asyncio.to_thread(
        add_component, target, comp_id=comp_id, comp_type=comp_type,
        config=config, rationale=rationale, replace=replace,
    )
    return {"plan_dir": str(target), "component": component}


async def plan_add_requirement(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    requirement: Annotated[dict, "Requirement mapping; needs at least 'id' and 'text', plus optional type/priority/acceptance_criteria"],
    rationale: Annotated[str | None, "Why this requirement (recorded as a plan decision)"] = None,
    replace: Annotated[bool, "Overwrite an existing requirement with the same id"] = False,
) -> dict:
    """Add a requirement (with optional acceptance criteria) to the plan."""
    from hangar.omd.plan_mutate import add_requirement

    target = resolve_plan_dir(plan_dir)
    req = await asyncio.to_thread(
        add_requirement, target, req=requirement, rationale=rationale, replace=replace
    )
    return {"plan_dir": str(target), "requirement": req}


async def plan_add_dv(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    name: Annotated[str, "DV short or prefixed name, e.g. 'twist_cp' or 'wing.twist_cp'"],
    lower: Annotated[float, "Lower bound"],
    upper: Annotated[float, "Upper bound (must exceed lower)"],
    scaler: Annotated[float | None, "Optional driver scaler"] = None,
    units: Annotated[str | None, "Optional units"] = None,
    rationale: Annotated[str | None, "Why this DV and these bounds"] = None,
    replace: Annotated[bool, "Overwrite an existing DV with the same name"] = False,
) -> dict:
    """Add a design variable; the name is validated against declared components."""
    from hangar.omd.plan_mutate import add_dv

    target = resolve_plan_dir(plan_dir)
    dv = await asyncio.to_thread(
        add_dv, target, name=name, lower=lower, upper=upper,
        scaler=scaler, units=units, rationale=rationale, replace=replace,
    )
    return {"plan_dir": str(target), "design_variable": dv}


async def plan_set_objective(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    name: Annotated[str, "Objective name, e.g. 'CD' or 'fuelburn'"],
    scaler: Annotated[float | None, "Optional driver scaler"] = None,
    units: Annotated[str | None, "Optional units"] = None,
    rationale: Annotated[str | None, "Why this objective"] = None,
) -> dict:
    """Set the optimization objective (replaces any existing one)."""
    from hangar.omd.plan_mutate import set_objective

    target = resolve_plan_dir(plan_dir)
    objective = await asyncio.to_thread(
        set_objective, target, name=name, scaler=scaler,
        units=units, rationale=rationale,
    )
    return {"plan_dir": str(target), "objective": objective}


async def plan_set_operating_point(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    fields: Annotated[dict, "Operating-point fields to merge, e.g. {'Mach_number': 0.78, 'alpha': 2.0}"],
    rationale: Annotated[str | None, "Why these conditions"] = None,
) -> dict:
    """Merge fields into the plan's operating point (existing keys are kept)."""
    from hangar.omd.plan_mutate import set_operating_point

    target = resolve_plan_dir(plan_dir)
    op = await asyncio.to_thread(
        set_operating_point, target, fields=fields, rationale=rationale
    )
    return {"plan_dir": str(target), "operating_points": op}


async def plan_set_solver(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    nonlinear: Annotated[str | None, "Nonlinear solver type, e.g. 'NewtonSolver'"] = None,
    linear: Annotated[str | None, "Linear solver type, e.g. 'DirectSolver'"] = None,
    nonlinear_options: Annotated[dict | None, "Nonlinear solver options, e.g. {'maxiter': 30, 'atol': 1e-8}"] = None,
    linear_options: Annotated[dict | None, "Linear solver options"] = None,
    rationale: Annotated[str | None, "Why this solver setup"] = None,
) -> dict:
    """Configure the plan's solvers (solvers.yaml)."""
    from hangar.omd.plan_mutate import set_solver

    target = resolve_plan_dir(plan_dir)
    solvers = await asyncio.to_thread(
        set_solver, target, nonlinear=nonlinear, linear=linear,
        nonlinear_options=nonlinear_options, linear_options=linear_options,
        rationale=rationale,
    )
    return {"plan_dir": str(target), "solvers": solvers}


async def plan_set_analysis_strategy(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    phases: Annotated[int, "Number of analysis phases to scaffold"],
    phase_id_prefix: Annotated[str, "Phase id prefix ('p' gives p1, p2, ...)"] = "p",
    rationale: Annotated[str | None, "Why this phasing"] = None,
) -> dict:
    """Scaffold the plan's phased analysis strategy (analysis_plan.yaml)."""
    from hangar.omd.plan_mutate import set_analysis_strategy

    target = resolve_plan_dir(plan_dir)
    strategy = await asyncio.to_thread(
        set_analysis_strategy, target, phases=phases,
        phase_id_prefix=phase_id_prefix, rationale=rationale,
    )
    return {"plan_dir": str(target), "analysis_plan": strategy}


async def plan_add_shared_var(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    name: Annotated[str, "Shared-var name, e.g. 'ac|geom|wing|AR'"],
    consumers: Annotated[list[str], "Component ids that consume this variable"],
    value: Annotated[float | list[float] | None, "Optional initial value"] = None,
    units: Annotated[str | None, "Optional units"] = None,
    rationale: Annotated[str | None, "Why this variable is shared"] = None,
    replace: Annotated[bool, "Overwrite an existing shared var with the same name"] = False,
) -> dict:
    """Declare a shared variable between components (multi-component plans)."""
    from hangar.omd.plan_mutate import add_shared_var

    target = resolve_plan_dir(plan_dir)
    shared = await asyncio.to_thread(
        add_shared_var, target, name=name, consumers=consumers,
        value=value, units=units, rationale=rationale, replace=replace,
    )
    return {"plan_dir": str(target), "shared_var": shared}


async def plan_set_composition_policy(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    policy: Annotated[str, "Composition policy: 'explicit' or 'auto'"],
    no_auto_share: Annotated[list[str] | None, "Variable names excluded from auto-sharing ([] clears the list)"] = None,
    rationale: Annotated[str | None, "Why this policy"] = None,
) -> dict:
    """Set how variables compose across components (composition_policy.yaml)."""
    from hangar.omd.plan_mutate import set_composition_policy

    target = resolve_plan_dir(plan_dir)
    result = await asyncio.to_thread(
        set_composition_policy, target, policy=policy,
        no_auto_share=no_auto_share, rationale=rationale,
    )
    return {"plan_dir": str(target), "composition_policy": result}


async def plan_add_decision(
    plan_dir: Annotated[str, "Plan directory (workspace-relative or absolute)"],
    decision: Annotated[dict, "Decision mapping: stage, decision, rationale, optional id/element_path"],
) -> dict:
    """Record a hand-authored decision in the plan (decisions.yaml)."""
    from hangar.omd.plan_mutate import add_decision

    target = resolve_plan_dir(plan_dir)
    dec = await asyncio.to_thread(add_decision, target, decision=decision)
    return {"plan_dir": str(target), "decision": dec}


async def review_plan(
    plan_path: Annotated[str, "Assembled plan YAML or modular plan directory"],
) -> dict:
    """Review a plan for completeness gaps (requirements, decisions, checks).

    Returns advisory findings -- unlike validate_plan these do not block a
    run, they flag what a thorough study should still pin down.
    """
    from dataclasses import asdict

    from hangar.omd.plan_review import review_plan_file

    path = resolve_plan_path(plan_path)
    plan, findings = await asyncio.to_thread(review_plan_file, path)
    return {
        "plan_path": str(path),
        "plan_id": ((plan or {}).get("metadata") or {}).get("id"),
        "findings": [asdict(f) for f in findings],
    }
