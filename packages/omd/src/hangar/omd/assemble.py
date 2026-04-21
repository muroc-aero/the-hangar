"""Assemble modular YAML plan directories into canonical plan files.

A plan directory contains modular YAML files that are merged into a
single canonical plan.yaml. The assembled plan is validated against
the plan schema, content-hashed, auto-versioned, and archived to
a history/ subdirectory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

from hangar.omd.plan_schema import validate_plan


# ---------------------------------------------------------------------------
# Merge strategy: file stem -> plan key mapping
# ---------------------------------------------------------------------------

# Direct mapping: file stem -> top-level plan key
_STEM_TO_KEY = {
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

# The optimization file contains nested keys that get promoted
_OPTIMIZATION_KEYS = {"design_variables", "constraints", "objective", "optimizer"}


def _merge_yaml_files(plan_dir: Path) -> dict:
    """Read and merge all modular YAML files from a plan directory.

    Merge rules:
    - metadata.yaml -> metadata
    - requirements.yaml -> requirements
    - operating_points.yaml -> operating_points
    - connections.yaml -> connections
    - solvers.yaml -> solvers
    - decisions.yaml -> decisions
    - rationale.yaml -> rationale
    - optimization.yaml -> design_variables, constraints, objective, optimizer
    - components/*.yaml -> collected into components array

    Args:
        plan_dir: Path to the plan directory.

    Returns:
        Merged plan dictionary.
    """
    plan: dict = {}

    # Direct-mapped files
    for stem, key in _STEM_TO_KEY.items():
        path = plan_dir / f"{stem}.yaml"
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            if data is not None:
                # If the file contains a dict with the key as top-level,
                # unwrap it. Otherwise use the data directly.
                if isinstance(data, dict) and key in data and len(data) == 1:
                    plan[key] = data[key]
                else:
                    plan[key] = data

    # Optimization file: promotes nested keys to top level
    opt_path = plan_dir / "optimization.yaml"
    if opt_path.exists():
        with open(opt_path) as f:
            opt_data = yaml.safe_load(f)
        if isinstance(opt_data, dict):
            for key in _OPTIMIZATION_KEYS:
                if key in opt_data:
                    plan[key] = opt_data[key]

    # Components: collected from components/ subdirectory
    comp_dir = plan_dir / "components"
    if comp_dir.is_dir():
        components = []
        for comp_path in sorted(comp_dir.glob("*.yaml")):
            with open(comp_path) as f:
                comp_data = yaml.safe_load(f)
            if comp_data is not None:
                if isinstance(comp_data, list):
                    components.extend(comp_data)
                else:
                    components.append(comp_data)
        if components:
            plan["components"] = components

    return plan


def _compute_content_hash(plan: dict) -> str:
    """Compute SHA256 hash of the plan's canonical JSON representation.

    Args:
        plan: Plan dictionary (without content_hash field).

    Returns:
        Hex-encoded SHA256 hash string.
    """
    # Remove transient fields before hashing
    hashable = {k: v for k, v in plan.items() if k != "metadata"}
    canonical = json.dumps(hashable, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _auto_version(plan_dir: Path, plan: dict) -> int:
    """Determine next version number and archive to history/.

    Reads existing history/ directory to find the highest version,
    increments by one, and copies the assembled plan there.

    Args:
        plan_dir: Plan directory path.
        plan: Assembled plan dict (metadata.version will be updated).

    Returns:
        The new version number.
    """
    history_dir = plan_dir / "history"
    history_dir.mkdir(exist_ok=True)

    # Find highest existing version
    max_version = 0
    for hist_file in history_dir.glob("v*.yaml"):
        try:
            v = int(hist_file.stem[1:])
            max_version = max(max_version, v)
        except ValueError:
            continue

    new_version = max_version + 1
    return new_version


def assemble_plan(
    plan_dir: Path,
    output: Path | None = None,
) -> dict:
    """Merge modular YAML files into a canonical plan.

    Args:
        plan_dir: Directory containing modular YAML files.
        output: Path to write assembled plan.yaml. Defaults to
            plan_dir / "plan.yaml".

    Returns:
        Dict with keys:
        - plan: the assembled plan dict
        - version: int
        - content_hash: str
        - output_path: str
        - errors: list of validation errors (empty if valid)
    """
    plan_dir = Path(plan_dir)
    if output is None:
        output = plan_dir / "plan.yaml"
    else:
        output = Path(output)

    # Merge modular files
    plan = _merge_yaml_files(plan_dir)

    # Inject placeholder version/content_hash so schema validation passes.
    # These are overwritten with real values after validation succeeds.
    if "metadata" in plan:
        if "version" not in plan["metadata"]:
            plan["metadata"]["version"] = 1  # placeholder
        if "content_hash" not in plan["metadata"]:
            plan["metadata"]["content_hash"] = ""

    # Validate against schema
    errors = validate_plan(plan)
    if errors:
        return {
            "plan": plan,
            "version": None,
            "content_hash": None,
            "output_path": str(output),
            "errors": errors,
        }

    # Compute content hash
    content_hash = _compute_content_hash(plan)

    # Auto-version
    new_version = _auto_version(plan_dir, plan)
    if "metadata" in plan:
        plan["metadata"]["version"] = new_version
        plan["metadata"]["content_hash"] = content_hash

        # Track parent version for replan provenance
        if new_version > 1:
            plan["metadata"]["parent_version"] = new_version - 1

    # Write assembled plan
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        yaml.dump(plan, f, default_flow_style=False, sort_keys=False)

    # Archive to history (in the plan directory)
    history_dir = plan_dir / "history"
    history_dir.mkdir(exist_ok=True)
    shutil.copy2(output, history_dir / f"v{new_version}.yaml")

    # Copy to central plan store
    plan_id = plan.get("metadata", {}).get("id", "unknown")
    store_path = _copy_to_plan_store(plan_id, new_version, output)

    # Record decision entities in provenance DB
    plan_entity_id = f"{plan_id}/v{new_version}"
    _record_decisions(plan_id, new_version, plan_entity_id, plan)
    _record_requirements(plan_id, new_version, plan_entity_id, plan)
    _record_analysis_plan(plan_id, new_version, plan_entity_id, plan)

    return {
        "plan": plan,
        "version": new_version,
        "content_hash": content_hash,
        "output_path": str(output),
        "store_path": str(store_path) if store_path else None,
        "errors": [],
    }


def _record_decisions(
    plan_id: str,
    version: int,
    plan_entity_id: str,
    plan: dict,
) -> None:
    """Record decision entries from the plan as provenance entities.

    Each entry in plan["decisions"] becomes a decision entity linked
    to the plan entity via a wasAttributedTo edge. If the decision
    carries an ``element_path``, a plan_element entity is recorded
    (if it does not already exist) and a ``justifies`` edge is emitted
    from the decision to that element.
    """
    decisions = plan.get("decisions")
    if not decisions or not isinstance(decisions, list):
        return

    try:
        from hangar.omd.db import (
            init_analysis_db,
            record_entity,
            add_prov_edge,
            record_activity,
        )
        from hangar.omd.plan_paths import (
            resolve_element_path,
            element_entity_id,
        )

        init_analysis_db()

        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            dec_id = decision.get("id", f"dec-{decisions.index(decision)}")
            entity_id = f"{plan_entity_id}/dec/{dec_id}"
            record_entity(
                entity_id=entity_id,
                entity_type="decision",
                created_by=decision.get("agent", "have-agent"),
                plan_id=plan_id,
                version=version,
                metadata=json.dumps(decision),
                parent_id=plan_entity_id,
            )
            # Record the decide activity
            decide_act_id = f"act-decide-{entity_id}"
            record_activity(
                activity_id=decide_act_id,
                activity_type="decide",
                agent="have-agent",
                status="completed",
            )
            add_prov_edge("wasGeneratedBy", entity_id, decide_act_id)

            # Link decision to the element it justifies, if any.
            element_path = decision.get("element_path")
            resolved = resolve_element_path(plan, element_path)
            if resolved is not None:
                elem_id = element_entity_id(plan_entity_id, resolved)
                record_entity(
                    entity_id=elem_id,
                    entity_type="plan_element",
                    created_by="omd",
                    plan_id=plan_id,
                    version=version,
                    metadata=json.dumps({
                        "element_path": element_path,
                        "entity_kind": resolved.entity_kind,
                    }),
                    parent_id=plan_entity_id,
                )
                add_prov_edge("justifies", entity_id, elem_id)
    except Exception:
        # Don't fail assembly if provenance recording fails
        pass


def _record_requirements(
    plan_id: str,
    version: int,
    plan_entity_id: str,
    plan: dict,
) -> None:
    """Record requirements and their acceptance_criteria as entities.

    Each requirement becomes a first-class provenance entity (so later
    assessments can emit satisfies/violates edges against it). Each
    acceptance_criterion becomes a sub-entity linked via a
    has_criterion edge.
    """
    requirements = plan.get("requirements")
    if not requirements or not isinstance(requirements, list):
        return

    try:
        from hangar.omd.db import (
            init_analysis_db,
            record_entity,
            add_prov_edge,
        )

        init_analysis_db()

        for req in requirements:
            if not isinstance(req, dict):
                continue
            req_id = req.get("id")
            if not req_id:
                continue
            req_entity = f"{plan_entity_id}/req/{req_id}"
            record_entity(
                entity_id=req_entity,
                entity_type="requirement",
                created_by="omd",
                plan_id=plan_id,
                version=version,
                metadata=json.dumps(req),
                parent_id=plan_entity_id,
            )
            add_prov_edge("wasAttributedTo", req_entity, plan_entity_id)

            criteria = req.get("acceptance_criteria")
            if not isinstance(criteria, list):
                continue
            for idx, crit in enumerate(criteria):
                if not isinstance(crit, dict):
                    continue
                metric = crit.get("metric", f"c{idx}")
                crit_id = f"{req_entity}/crit/{metric}"
                record_entity(
                    entity_id=crit_id,
                    entity_type="acceptance_criterion",
                    created_by="omd",
                    plan_id=plan_id,
                    version=version,
                    metadata=json.dumps(crit),
                    parent_id=req_entity,
                )
                add_prov_edge("has_criterion", req_entity, crit_id)
    except Exception:
        pass


def _record_analysis_plan(
    plan_id: str,
    version: int,
    plan_entity_id: str,
    plan: dict,
) -> None:
    """Record analysis_plan phases as provenance entities.

    Each phase becomes a phase entity linked to the plan via
    wasAttributedTo. Each depends_on reference becomes a precedes edge
    from the predecessor phase to this one.
    """
    analysis_plan = plan.get("analysis_plan")
    if not isinstance(analysis_plan, dict):
        return
    phases = analysis_plan.get("phases")
    if not isinstance(phases, list):
        return

    try:
        from hangar.omd.db import (
            init_analysis_db,
            record_entity,
            add_prov_edge,
        )

        init_analysis_db()

        phase_ids = {
            p.get("id") for p in phases
            if isinstance(p, dict) and p.get("id")
        }

        for phase in phases:
            if not isinstance(phase, dict):
                continue
            pid = phase.get("id")
            if not pid:
                continue
            phase_entity = f"{plan_entity_id}/phase/{pid}"
            record_entity(
                entity_id=phase_entity,
                entity_type="phase",
                created_by="omd",
                plan_id=plan_id,
                version=version,
                metadata=json.dumps(phase),
                parent_id=plan_entity_id,
            )
            add_prov_edge("wasAttributedTo", phase_entity, plan_entity_id)

            depends_on = phase.get("depends_on") or []
            for dep in depends_on:
                if dep not in phase_ids:
                    continue
                dep_entity = f"{plan_entity_id}/phase/{dep}"
                add_prov_edge("precedes", dep_entity, phase_entity)
    except Exception:
        pass


def _copy_to_plan_store(plan_id: str, version: int, source: Path) -> Path | None:
    """Copy assembled plan to the central plan store.

    Returns the store path, or None if the copy failed.
    """
    from hangar.omd.db import plan_store_dir

    try:
        store_dir = plan_store_dir() / plan_id
        store_dir.mkdir(parents=True, exist_ok=True)
        dest = store_dir / f"v{version}.yaml"
        shutil.copy2(source, dest)
        return dest
    except Exception:
        return None
