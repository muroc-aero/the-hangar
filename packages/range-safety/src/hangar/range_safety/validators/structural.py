"""Plan structure validation: required fields, schema conformance.

Checks that the plan references valid component types, has consistent
internal references (DV/constraint/objective names, connection endpoints),
and uses known solver/optimizer types.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Known solver and optimizer types (must match materializer.py)
_NONLINEAR_SOLVERS = {"NewtonSolver", "NonlinearBlockGS"}
_LINEAR_SOLVERS = {"DirectSolver", "LinearBlockGS"}
_OPTIMIZERS = {"SLSQP", "COBYLA", "L-BFGS-B", "Nelder-Mead"}


def _default_catalog_dir() -> Path:
    """Resolve the default catalog directory from the repo root."""
    # Walk up from this file to find the catalog/ directory
    here = Path(__file__).resolve()
    # packages/range-safety/src/hangar/range_safety/validators/structural.py
    # -> repo root is 6 levels up
    for parent in here.parents:
        candidate = parent / "catalog"
        if candidate.is_dir():
            return candidate
    return here.parents[6] / "catalog"


def _load_catalog(catalog_dir: Path) -> dict[str, dict]:
    """Load all catalog YAML files into a type-string -> dict mapping.

    Args:
        catalog_dir: Root catalog directory (contains subdirs like oas/).

    Returns:
        Dict mapping type strings (e.g., "oas/AerostructPoint") to
        parsed YAML catalog entries.
    """
    catalog: dict[str, dict] = {}
    if not catalog_dir.is_dir():
        logger.warning("Catalog directory not found: %s", catalog_dir)
        return catalog

    for yaml_path in catalog_dir.rglob("*.yaml"):
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and "type" in data:
                catalog[data["type"]] = data
        except Exception as exc:
            logger.warning("Failed to load catalog entry %s: %s", yaml_path, exc)

    return catalog


def _finding(
    check: str,
    severity: str,
    message: str,
) -> dict:
    """Build a finding dict."""
    return {"check": check, "severity": severity, "message": message}


def validate_structural(
    plan: dict,
    catalog_dir: Path | None = None,
) -> list[dict]:
    """Check that the plan is structurally sound.

    Goes beyond JSON schema validation to verify that internal references
    are consistent and component types exist in the catalog.

    Args:
        plan: Parsed plan dictionary (already schema-validated).
        catalog_dir: Path to the catalog directory. Uses default if None.

    Returns:
        List of finding dicts with keys: check, severity, message.
    """
    findings: list[dict] = []

    if catalog_dir is None:
        catalog_dir = _default_catalog_dir()
    catalog = _load_catalog(catalog_dir)

    components = plan.get("components", [])
    component_ids = set()

    # -- Component checks --
    for comp in components:
        comp_id = comp.get("id", "<unknown>")
        comp_type = comp.get("type", "")

        # Duplicate component IDs
        if comp_id in component_ids:
            findings.append(_finding(
                "duplicate_component_id",
                "error",
                f"Duplicate component ID: '{comp_id}'",
            ))
        component_ids.add(comp_id)

        # Component type exists in catalog
        if catalog and comp_type not in catalog:
            available = sorted(catalog.keys())
            findings.append(_finding(
                "component_type_exists",
                "error",
                f"Component '{comp_id}' has type '{comp_type}' "
                f"not found in catalog. Available: {available}",
            ))

        # OAS-specific checks on surface config
        config = comp.get("config", {})
        surfaces = config.get("surfaces", [])
        for surface in surfaces:
            num_y = surface.get("num_y")
            if num_y is not None and num_y % 2 == 0:
                findings.append(_finding(
                    "num_y_odd",
                    "error",
                    f"Component '{comp_id}', surface '{surface.get('name', '?')}': "
                    f"num_y={num_y} must be odd",
                ))

            # Aerostruct requires fem_model_type + material properties
            fem_model = surface.get("fem_model_type")
            if comp_type == "oas/AerostructPoint" and not fem_model:
                findings.append(_finding(
                    "fem_model_required",
                    "error",
                    f"Component '{comp_id}', surface '{surface.get('name', '?')}': "
                    f"fem_model_type required for AerostructPoint",
                ))

            if fem_model:
                required_props = ["E", "G", "yield_stress", "mrho"]
                missing = [p for p in required_props if p not in surface]
                if missing:
                    findings.append(_finding(
                        "material_properties",
                        "error",
                        f"Component '{comp_id}', surface '{surface.get('name', '?')}': "
                        f"fem_model_type='{fem_model}' requires material properties: "
                        f"{missing}",
                    ))

        # Slot provider checks
        slots = config.get("slots", {})
        for slot_name, slot_cfg in slots.items():
            provider_name = slot_cfg.get("provider", "")

            # Check provider is registered
            try:
                from hangar.omd.slots import list_slot_providers
                known_providers = list_slot_providers()
                if provider_name not in known_providers:
                    findings.append(_finding(
                        "slot_provider_exists",
                        "error",
                        f"Component '{comp_id}', slot '{slot_name}': "
                        f"provider '{provider_name}' not registered. "
                        f"Known: {known_providers}",
                    ))
            except ImportError:
                pass  # omd not installed, skip

            # OAS slot config checks
            slot_config = slot_cfg.get("config", {})
            if provider_name.startswith("oas/"):
                slot_num_y = slot_config.get("num_y")
                if slot_num_y is not None and slot_num_y % 2 == 0:
                    findings.append(_finding(
                        "slot_num_y_odd",
                        "error",
                        f"Component '{comp_id}', slot '{slot_name}': "
                        f"num_y={slot_num_y} must be odd (OAS constraint)",
                    ))

                slot_num_x = slot_config.get("num_x")
                if slot_num_x is not None and slot_num_x < 2:
                    findings.append(_finding(
                        "slot_mesh_params",
                        "warning",
                        f"Component '{comp_id}', slot '{slot_name}': "
                        f"num_x={slot_num_x} < 2 may produce poor results",
                    ))

    # -- Solver checks --
    solvers = plan.get("solvers", {})
    nl_solver = solvers.get("nonlinear", {})
    lin_solver = solvers.get("linear", {})

    if nl_solver:
        nl_type = nl_solver.get("type", "")
        if nl_type and nl_type not in _NONLINEAR_SOLVERS:
            findings.append(_finding(
                "solver_type_valid",
                "error",
                f"Unknown nonlinear solver type: '{nl_type}'. "
                f"Known: {sorted(_NONLINEAR_SOLVERS)}",
            ))

        # Iterative NL solver should have a linear solver
        if nl_type in _NONLINEAR_SOLVERS and not lin_solver:
            findings.append(_finding(
                "linear_solver_specified",
                "warning",
                f"Nonlinear solver '{nl_type}' specified without a "
                f"linear solver. A linear solver is recommended.",
            ))

    if lin_solver:
        lin_type = lin_solver.get("type", "")
        if lin_type and lin_type not in _LINEAR_SOLVERS:
            findings.append(_finding(
                "solver_type_valid",
                "error",
                f"Unknown linear solver type: '{lin_type}'. "
                f"Known: {sorted(_LINEAR_SOLVERS)}",
            ))

    # -- Optimizer checks --
    optimizer = plan.get("optimizer", {})
    if optimizer:
        opt_type = optimizer.get("type", "")
        if opt_type and opt_type not in _OPTIMIZERS:
            findings.append(_finding(
                "optimizer_type_valid",
                "error",
                f"Unknown optimizer type: '{opt_type}'. "
                f"Known: {sorted(_OPTIMIZERS)}",
            ))

    # -- DV / constraint / objective name checks --
    for dv in plan.get("design_variables", []):
        name = dv.get("name", "")
        if not name:
            findings.append(_finding(
                "dv_name_nonempty",
                "error",
                "Design variable has empty name",
            ))

    for con in plan.get("constraints", []):
        name = con.get("name", "")
        if not name:
            findings.append(_finding(
                "constraint_name_nonempty",
                "error",
                "Constraint has empty name",
            ))

    obj = plan.get("objective", {})
    if obj:
        name = obj.get("name", "")
        if not name:
            findings.append(_finding(
                "objective_name_nonempty",
                "error",
                "Objective has empty name",
            ))

    # -- Connection endpoint checks --
    for conn in plan.get("connections", []):
        src = conn.get("src", "")
        tgt = conn.get("tgt", "")
        # Connection paths typically start with a component ID
        src_root = src.split(".")[0] if "." in src else src
        tgt_root = tgt.split(".")[0] if "." in tgt else tgt

        if src_root and src_root not in component_ids:
            findings.append(_finding(
                "connection_endpoint_exists",
                "warning",
                f"Connection source '{src}' root '{src_root}' "
                f"does not match any component ID",
            ))
        if tgt_root and tgt_root not in component_ids:
            findings.append(_finding(
                "connection_endpoint_exists",
                "warning",
                f"Connection target '{tgt}' root '{tgt_root}' "
                f"does not match any component ID",
            ))

    return findings
