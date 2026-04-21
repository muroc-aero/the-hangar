"""Semantic validation for assembled plans.

Runs *after* JSON Schema validation. Catches the class of mistake where a
plan parses as valid YAML but references a DV/constraint/objective short
name that no factory exposes (the silent pass-through bug at
``materializer._resolve_var_path`` line 699).

Output format mirrors ``plan_schema.load_and_validate``: a list of dicts
with ``path`` + ``message``.  Suggestions are included when available.
"""

from __future__ import annotations

import difflib
from typing import Any

from hangar.omd.errors import ValidationFinding


# ---------------------------------------------------------------------------
# Known short names, by component type.
#
# Keep in sync with:
#   - materializer._resolve_var_path (hardcoded tables)
#   - each factory's var_paths dict
#
# These are used only for suggestion lookup. Actual resolution still goes
# through _resolve_var_path, which may accept names not listed here
# (e.g. pipe-separated OpenConcept paths pass through unchanged).
# ---------------------------------------------------------------------------

_GENERIC_PROMOTED = {
    "alpha", "v", "rho", "Mach_number", "re", "load_factor", "beta",
    "CT", "R", "W0", "speed_of_sound",
    "alpha_maneuver", "fuel_mass",
    "W0_without_point_masses", "point_masses", "point_mass_locations",
    "fuel_vol_delta", "fuel_diff",
    "fuelburn", "L_equals_W", "structural_mass",
}

_OAS_COMMON = {
    "twist_cp", "thickness_cp", "chord_cp",
    "spar_thickness_cp", "skin_thickness_cp", "t_over_c_cp",
    "CL", "CD", "CDi", "CDv", "CDw", "CM",
    "failure", "tsaiwu_sr", "S_ref",
}

_OCP_COMMON = {
    "fuel_burn", "OEW", "MTOW", "TOFL",
    # Top-level maneuver-slot outputs (see slots.py
    # `_oas_maneuver_provider.result_paths` and
    # `factories/ocp/builder.py` var_paths wiring)
    "failure_maneuver", "W_wing_maneuver", "alpha_maneuver",
}

_KNOWN_BY_PREFIX: dict[str, set[str]] = {
    "oas/": _GENERIC_PROMOTED | _OAS_COMMON,
    "ocp/": _GENERIC_PROMOTED | _OCP_COMMON,
    "pyc/": _GENERIC_PROMOTED,
    "paraboloid/": _GENERIC_PROMOTED | {"x", "y", "f_xy"},
}


def _known_names_for(components: list[dict]) -> set[str]:
    """Collect plausible short names across all components in a plan."""
    names: set[str] = set(_GENERIC_PROMOTED)
    for comp in components:
        ctype = comp.get("type", "")
        for prefix, candidates in _KNOWN_BY_PREFIX.items():
            if ctype.startswith(prefix):
                names |= candidates
    return names


def _is_resolvable(name: str) -> bool:
    """Names containing '.' or '|' are treated as explicit full paths."""
    return "." in name or "|" in name


def _suggest(name: str, known: set[str]) -> list[str]:
    """Return up to three close matches for ``name`` from the known set."""
    return difflib.get_close_matches(name, sorted(known), n=3, cutoff=0.6)


def _check_name_list(
    items: list[dict],
    section: str,
    known: set[str],
    name_key: str = "name",
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for i, item in enumerate(items or []):
        name = item.get(name_key) if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            continue
        if _is_resolvable(name):
            continue
        if name in known:
            continue
        suggestions = _suggest(name, known)
        findings.append(ValidationFinding(
            path=f"{section}[{i}].{name_key}",
            message=f"Unknown variable '{name}'.",
            suggestions=suggestions,
        ))
    return findings


def validate_var_paths(plan: dict) -> list[ValidationFinding]:
    """Check every DV/constraint/objective short name resolves.

    Empty plans or plans missing the optional DV/constraint/objective
    sections pass through without findings.
    """
    components = plan.get("components") or []
    known = _known_names_for(components)

    findings: list[ValidationFinding] = []
    findings += _check_name_list(plan.get("design_variables") or [],
                                 "design_variables", known)
    findings += _check_name_list(plan.get("constraints") or [],
                                 "constraints", known)

    obj = plan.get("objective")
    if isinstance(obj, dict):
        name = obj.get("name")
        if isinstance(name, str) and not _is_resolvable(name) and name not in known:
            findings.append(ValidationFinding(
                path="objective.name",
                message=f"Unknown variable '{name}'.",
                suggestions=_suggest(name, known),
            ))
    return findings


def validate_plan_semantic(plan: dict, registry_types: set[str] | None = None) -> list[ValidationFinding]:
    """Run all semantic checks (component types known + var paths resolve)."""
    findings: list[ValidationFinding] = []

    if registry_types is not None:
        for i, comp in enumerate(plan.get("components") or []):
            ctype = comp.get("type") if isinstance(comp, dict) else None
            if not isinstance(ctype, str):
                continue
            if ctype not in registry_types:
                suggestions = difflib.get_close_matches(
                    ctype, sorted(registry_types), n=3, cutoff=0.5,
                )
                findings.append(ValidationFinding(
                    path=f"components[{i}].type",
                    message=f"Unknown component type '{ctype}'.",
                    suggestions=suggestions,
                ))

    findings += validate_var_paths(plan)
    return findings


def format_findings(findings: list[ValidationFinding]) -> str:
    """Render findings as a human-readable multi-line string."""
    lines = []
    for f in findings:
        hint = f" (did you mean: {', '.join(f.suggestions)}?)" if f.suggestions else ""
        lines.append(f"  {f.path}: {f.message}{hint}")
    return "\n".join(lines)


__all__ = [
    "validate_var_paths",
    "validate_plan_semantic",
    "format_findings",
]
