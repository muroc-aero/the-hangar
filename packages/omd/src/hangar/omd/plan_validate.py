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

    # Shared-var names are always resolvable (they wire to the root
    # shared_ivc subsystem in composite plans).
    for sv in plan.get("shared_vars") or []:
        if isinstance(sv, dict):
            name = sv.get("name")
            if isinstance(name, str) and name:
                known.add(name)

    # Auto-derived shared_vars (Fix 3): when composition_policy=auto,
    # any name declared as produced by >=2 components resolves to the
    # root shared_ivc.
    if plan.get("composition_policy") == "auto":
        from hangar.omd.registry import get_factory_contract

        no_auto = set(plan.get("no_auto_share") or [])
        producer_counts: dict[str, int] = {}
        for comp in components:
            if not isinstance(comp, dict):
                continue
            ctype = comp.get("type")
            if not isinstance(ctype, str):
                continue
            try:
                contract = get_factory_contract(ctype)
            except KeyError:
                continue
            if contract is None:
                continue
            for name in contract.produces:
                producer_counts[name] = producer_counts.get(name, 0) + 1
        for name, count in producer_counts.items():
            if count >= 2 and name not in no_auto:
                known.add(name)

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


def validate_shared_vars(plan: dict) -> list[ValidationFinding]:
    """Check shared_vars consumers reference real components.

    Emits findings for:
      - consumer id that does not match any declared component
      - duplicate shared_var names
      - consumer whose factory type has no skip_fields support
        (pyc/* and paraboloid/* currently)
    """
    shared_vars = plan.get("shared_vars") or []
    if not shared_vars:
        return []

    findings: list[ValidationFinding] = []
    components = plan.get("components") or []
    comp_types: dict[str, str] = {}
    for comp in components:
        if isinstance(comp, dict) and isinstance(comp.get("id"), str):
            comp_types[comp["id"]] = comp.get("type", "")

    seen_names: set[str] = set()
    # pyc/* cycles are built as the model root with their own namespaces;
    # they won't have an `ac|*`-style promoted input to drive, so the
    # shared-IVC fanout will not wire. Other factories are allowed to try.
    unsupported_prefixes = ("pyc/",)

    for i, entry in enumerate(shared_vars):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            if name in seen_names:
                findings.append(ValidationFinding(
                    path=f"shared_vars[{i}].name",
                    message=f"Duplicate shared_vars entry '{name}'.",
                ))
            seen_names.add(name)

        consumers = entry.get("consumers") or []
        for j, cid in enumerate(consumers):
            if not isinstance(cid, str):
                continue
            if cid not in comp_types:
                suggestions = difflib.get_close_matches(
                    cid, sorted(comp_types), n=3, cutoff=0.5,
                )
                findings.append(ValidationFinding(
                    path=f"shared_vars[{i}].consumers[{j}]",
                    message=(
                        f"Consumer '{cid}' does not match any declared "
                        f"component id."
                    ),
                    suggestions=suggestions,
                ))
                continue
            ctype = comp_types[cid]
            if ctype.startswith(unsupported_prefixes):
                findings.append(ValidationFinding(
                    path=f"shared_vars[{i}].consumers[{j}]",
                    message=(
                        f"Component '{cid}' (type '{ctype}') does not "
                        f"support skip_fields; use explicit "
                        f"'connections:' for this consumer instead."
                    ),
                ))
    return findings


def validate_factory_contracts(plan: dict) -> list[ValidationFinding]:
    """Advisory validation for Fix 3 auto-derived shared_vars.

    Emits informational findings when ``composition_policy=auto`` and
    reports:
      - Names that would be auto-hoisted (informational).
      - ``no_auto_share`` entries that do not match any producer
        (warns with close-match suggestions).
      - Multiple contracts declaring different ``default`` values for
        the same name (informational; first producer wins).

    Safe to call on plans without ``composition_policy`` set; returns
    an empty list when the policy is ``explicit`` (the default).
    """
    policy = plan.get("composition_policy", "explicit")
    if policy != "auto":
        return []

    from hangar.omd.registry import get_factory_contract

    findings: list[ValidationFinding] = []
    components = plan.get("components") or []
    user_shared_names = {
        sv["name"] for sv in (plan.get("shared_vars") or [])
        if isinstance(sv, dict) and "name" in sv
    }

    producers: dict[str, list[tuple[str, object]]] = {}
    for comp in components:
        if not isinstance(comp, dict):
            continue
        ctype = comp.get("type")
        cid = comp.get("id")
        if not isinstance(ctype, str) or not isinstance(cid, str):
            continue
        try:
            contract = get_factory_contract(ctype)
        except KeyError:
            continue
        if contract is None:
            continue
        for name, spec in contract.produces.items():
            producers.setdefault(name, []).append((cid, spec))

    all_produced = set(producers.keys())
    no_auto = plan.get("no_auto_share") or []
    for i, name in enumerate(no_auto):
        if not isinstance(name, str):
            continue
        if name not in all_produced:
            suggestions = difflib.get_close_matches(
                name, sorted(all_produced), n=3, cutoff=0.5,
            )
            findings.append(ValidationFinding(
                path=f"no_auto_share[{i}]",
                message=(
                    f"'{name}' is listed in no_auto_share but no "
                    f"component contract declares it as produced."
                ),
                suggestions=suggestions,
            ))

    for name, prods in sorted(producers.items()):
        if len(prods) < 2:
            continue
        if name in user_shared_names or name in no_auto:
            continue
        consumer_ids = sorted(pid for pid, _ in prods)
        findings.append(ValidationFinding(
            path="composition_policy",
            message=(
                f"Auto-shared '{name}' across {consumer_ids} "
                f"(default from '{prods[0][0]}')."
            ),
        ))
        defaults = {getattr(spec, "default", None) for _, spec in prods}
        if len(defaults) > 1:
            findings.append(ValidationFinding(
                path=f"shared_vars(auto)[{name}]",
                message=(
                    f"Producers for '{name}' declare different defaults "
                    f"({sorted(str(d) for d in defaults)}); "
                    f"first producer '{prods[0][0]}' wins."
                ),
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
    findings += validate_shared_vars(plan)
    findings += validate_factory_contracts(plan)
    return findings


def format_findings(findings: list[ValidationFinding]) -> str:
    """Render findings as a human-readable multi-line string."""
    lines = []
    for f in findings:
        hint = f" (did you mean: {', '.join(f.suggestions)}?)" if f.suggestions else ""
        lines.append(f"  {f.path}: {f.message}{hint}")
    return "\n".join(lines)


__all__ = [
    "validate_factory_contracts",
    "validate_plan_semantic",
    "validate_shared_vars",
    "validate_var_paths",
    "format_findings",
]
