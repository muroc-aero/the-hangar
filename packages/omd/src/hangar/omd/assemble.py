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
    "solvers": "solvers",
    "decisions": "decisions",
    "rationale": "rationale",
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

    return {
        "plan": plan,
        "version": new_version,
        "content_hash": content_hash,
        "output_path": str(output),
        "store_path": str(store_path) if store_path else None,
        "errors": [],
    }


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
