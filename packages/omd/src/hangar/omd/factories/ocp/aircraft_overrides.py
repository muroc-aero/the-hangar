"""Aircraft-data overrides for the OCP mission factories.

A plan can start from a built-in ``aircraft_template`` and change
individual aircraft-data fields in three places, all of which resolve
here to the same result:

- ``config.aircraft_data`` next to ``aircraft_template`` -- merged over
  the template (nested template shape or flat ``ac|...`` keys);
- plan ``operating_points`` keys that are aircraft-data paths
  (``ac|propulsion|engine|rating: {value: 1117.2, units: hp}``);
- ``config.structural_fudge`` (alias ``ac|weights|structural_fudge`` in
  either of the above) -- the empty-weight model's structural weight
  multiplier, which is not an aircraft-data field but a per-phase
  constant inside OpenConcept's weight model (stock 1.6).

Every override is checked against the fields the chosen architecture
actually reads: a path the template does not have, or one the
architecture never registers (e.g. ``ac|weights|OEW`` on a propeller
architecture, whose OEW is computed), is an error rather than a
silently ignored value.

Kept free of OpenConcept imports so ``plan_validate`` can run the same
checks statically.
"""

from __future__ import annotations

import copy
import difflib
from dataclasses import dataclass, field
from typing import Any

from hangar.omd.factories.ocp.architectures import PROPULSION_ARCHITECTURES
from hangar.omd.factories.ocp.defaults import (
    _COMMON_FIELDS,
    _FUSELAGE_FIELDS,
    _HYBRID_FIELDS,
    _MULTI_ENGINE_FIELDS,
    _OEW_FIELDS,
    _PROPELLER_FIELDS,
)
from hangar.omd.factories.ocp.templates import AIRCRAFT_TEMPLATES

STRUCTURAL_FUDGE_KEYS = ("structural_fudge", "ac|weights|structural_fudge")
BATTERY_SPEC_ENERGY = "ac|propulsion|battery|specific_energy"
_BATTERY_SPEC_ENERGY_UNITS = "W*h/kg"

_ALL_FIELDS = set(
    _COMMON_FIELDS + _FUSELAGE_FIELDS + _PROPELLER_FIELDS + _HYBRID_FIELDS
    + _MULTI_ENGINE_FIELDS + _OEW_FIELDS
) | {BATTERY_SPEC_ENERGY}


@dataclass
class Problem:
    """One override that cannot be applied."""

    path: str
    message: str
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ResolvedAircraft:
    """Aircraft data with every override applied."""

    data: dict
    structural_fudge: float | None = None
    battery_specific_energy: float | None = None
    # pipe path (or "structural_fudge") -> {"value", "units", "source"}
    applied: dict[str, dict] = field(default_factory=dict)


def is_override_key(key: str) -> bool:
    """Operating-point keys the OCP factory consumes as aircraft overrides."""
    return isinstance(key, str) and (key in STRUCTURAL_FUDGE_KEYS or key.startswith("ac|"))


def flatten_aircraft_data(data: Any, prefix: str = "") -> dict[str, dict]:
    """Nested template-shaped data (or flat ``ac|...`` keys) -> leaf specs.

    A leaf is a mapping with a ``value`` key, or a bare number/list.
    Returns ``{pipe_path: {"value": ..., "units": ...}}``.
    """
    out: dict[str, dict] = {}
    if not isinstance(data, dict):
        return out
    for key, val in data.items():
        path = key if "|" in str(key) or not prefix else f"{prefix}|{key}"
        if isinstance(val, dict) and "value" in val:
            out[path] = {"value": val["value"], "units": val.get("units")}
        elif isinstance(val, dict):
            out.update(flatten_aircraft_data(val, path))
        else:
            out[path] = {"value": val, "units": None}
    return out


def structural_fudge_applies(architecture: str, slots: dict | None) -> bool:
    """True when the architecture's own empty-weight model is in use.

    That model carries the ``OEW.const.structural_fudge`` constant; a
    weight slot or a propulsion slot (OEW passthrough) replaces it.
    """
    arch = PROPULSION_ARCHITECTURES.get(architecture, {})
    slots = slots or {}
    return bool(arch.get("weight_class")) and "weight" not in slots and "propulsion" not in slots


def _slot_field_changes(slots: dict | None) -> tuple[set[str], set[str]]:
    removes: set[str] = set()
    adds: set[str] = set()
    if not slots:
        return removes, adds
    try:
        from hangar.omd.slots import get_slot_provider
    except Exception:  # noqa: BLE001 -- slot stack not importable here
        return removes, adds
    for cfg in slots.values():
        if not isinstance(cfg, dict) or "provider" not in cfg:
            continue
        try:
            prov = get_slot_provider(cfg["provider"])
        except Exception:  # noqa: BLE001 -- unknown provider fails elsewhere
            continue
        removes |= set(getattr(prov, "removes_fields", ()) or ())
        adds |= set(getattr(prov, "adds_fields", {}) or {})
    return removes, adds


def active_fields(architecture: str, slots: dict | None = None) -> set[str]:
    """Aircraft-data paths the mission model registers for this setup.

    Mirrors the field registration in ``builder._build_mission_problem``.
    """
    arch = PROPULSION_ARCHITECTURES[architecture]
    is_cfm56 = arch["prop_class"] == "CFM56"
    is_hybrid = arch["has_battery"] and arch["has_fuel"]
    fields = set(_COMMON_FIELDS) | set(_FUSELAGE_FIELDS)
    if not is_cfm56:
        fields |= set(_PROPELLER_FIELDS)
    if is_hybrid:
        fields |= set(_HYBRID_FIELDS) | {BATTERY_SPEC_ENERGY}
    if arch["num_engines"] > 1:
        fields |= set(_MULTI_ENGINE_FIELDS)
    if is_cfm56 or (slots and "propulsion" in slots):
        fields |= set(_OEW_FIELDS)
    removes, adds = _slot_field_changes(slots)
    return fields - removes - adds


def _suggest(path: str, known: set[str]) -> list[str]:
    leaf = path.rsplit("|", 1)[-1]
    same_leaf = sorted(k for k in known if k.rsplit("|", 1)[-1] == leaf)
    close = difflib.get_close_matches(path, sorted(known), n=3, cutoff=0.6)
    return list(dict.fromkeys(same_leaf + close))[:5]


def collect_overrides(
    config: dict,
    operating_points: Any,
    architecture: str,
) -> tuple[dict, list[tuple[str, str, dict]], float | None, list[Problem]]:
    """Gather and check every aircraft override a component asks for.

    Returns ``(base_data, overrides, structural_fudge, problems)`` where
    ``overrides`` is a list of ``(source, pipe_path, spec)``.
    """
    problems: list[Problem] = []
    template_name = config.get("aircraft_template")
    inline = config.get("aircraft_data")
    if template_name:
        if template_name not in AIRCRAFT_TEMPLATES:
            raise ValueError(
                f"Unknown aircraft template '{template_name}'. "
                f"Available: {', '.join(sorted(AIRCRAFT_TEMPLATES))}"
            )
        base = copy.deepcopy(AIRCRAFT_TEMPLATES[template_name]["data"])
    elif inline:
        base = copy.deepcopy(inline)
    else:
        raise ValueError(
            "OCP factory requires either 'aircraft_template' or "
            "'aircraft_data' in config"
        )

    overrides: list[tuple[str, str, dict]] = []
    if template_name and inline:
        for path, spec in flatten_aircraft_data(inline).items():
            overrides.append((f"config.aircraft_data.{path}", path, spec))
    if isinstance(operating_points, dict) and "flight_points" not in operating_points:
        for key, raw in operating_points.items():
            if not is_override_key(key):
                continue
            if isinstance(raw, dict) and "value" in raw:
                spec = {"value": raw["value"], "units": raw.get("units")}
            else:
                spec = {"value": raw, "units": None}
            overrides.append((f"operating_points.{key}", key, spec))

    fudge_sources: list[tuple[str, Any]] = []
    if config.get("structural_fudge") is not None:
        fudge_sources.append(("config.structural_fudge", config["structural_fudge"]))
    remaining: list[tuple[str, str, dict]] = []
    for source, path, spec in overrides:
        if path in STRUCTURAL_FUDGE_KEYS:
            if spec.get("units"):
                problems.append(Problem(source, "structural_fudge is dimensionless; remove the units tag."))
                continue
            fudge_sources.append((source, spec["value"]))
        else:
            remaining.append((source, path, spec))

    fudge: float | None = None
    if fudge_sources:
        values = {float(v) for _, v in fudge_sources}
        if len(values) > 1:
            problems.append(Problem(
                fudge_sources[0][0],
                "structural_fudge is given more than once with different values: "
                + ", ".join(f"{s}={v}" for s, v in fudge_sources),
            ))
        fudge = float(fudge_sources[-1][1])
        if not structural_fudge_applies(architecture, config.get("slots")):
            problems.append(Problem(
                fudge_sources[0][0],
                f"structural_fudge has no effect for architecture '{architecture}' "
                "with the given slots: it scales the architecture's own "
                "empty-weight model, which a weight or propulsion slot replaces.",
            ))

    known = set(flatten_aircraft_data(base)) | _ALL_FIELDS
    active = active_fields(architecture, config.get("slots"))
    skipped = set(config.get("skip_fields") or [])
    for source, path, spec in remaining:
        if path not in known:
            problems.append(Problem(
                source,
                f"'{path}' is not an aircraft-data field. Structural weight "
                "factor: use structural_fudge.",
                _suggest(path, known | {"structural_fudge"}),
            ))
        elif path in skipped:
            problems.append(Problem(
                source,
                f"'{path}' is driven by shared_vars in this plan; set its "
                "value on the shared variable instead.",
            ))
        elif path not in active:
            problems.append(Problem(
                source,
                f"'{path}' is not read by architecture '{architecture}' "
                "(the model computes it or does not use it), so the value "
                "would have no effect.",
                _suggest(path, active),
            ))
    return base, remaining, fudge, problems


def _convert(value: Any, from_units: str | None, to_units: str | None) -> Any:
    if not from_units or not to_units or from_units == to_units:
        return value
    from openmdao.utils.units import convert_units

    if isinstance(value, (list, tuple)):
        return [convert_units(float(v), from_units, to_units) for v in value]
    return convert_units(float(value), from_units, to_units)


def _set_leaf(data: dict, path: str, spec: dict) -> None:
    node = data
    parts = path.split("|")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    old = node.get(parts[-1])
    old_units = old.get("units") if isinstance(old, dict) else None
    units = spec.get("units")
    if old_units and units:
        leaf = {"value": _convert(spec["value"], units, old_units), "units": old_units}
    elif units or old_units:
        leaf = {"value": spec["value"], "units": units or old_units}
    else:
        leaf = {"value": spec["value"]}
    node[parts[-1]] = leaf


def resolve_aircraft(
    config: dict,
    operating_points: Any,
    architecture: str,
) -> ResolvedAircraft:
    """Base aircraft data with every override applied, or UserInputError."""
    base, overrides, fudge, problems = collect_overrides(
        config, operating_points, architecture,
    )
    if problems:
        from hangar.sdk.errors import UserInputError

        lines = [f"{p.path}: {p.message}" + (f" Did you mean: {', '.join(p.suggestions)}?"
                                               if p.suggestions else "")
                 for p in problems]
        raise UserInputError(
            "Aircraft overrides cannot be applied:\n  " + "\n  ".join(lines),
            details={"problems": [p.__dict__ for p in problems]},
        )

    resolved = ResolvedAircraft(data=base, structural_fudge=fudge)
    for source, path, spec in overrides:
        if path == BATTERY_SPEC_ENERGY:
            resolved.battery_specific_energy = float(
                _convert(spec["value"], spec.get("units"), _BATTERY_SPEC_ENERGY_UNITS))
        else:
            _set_leaf(base, path, spec)
        resolved.applied[path] = {**spec, "source": source}
    if fudge is not None:
        resolved.applied["structural_fudge"] = {"value": fudge, "units": None,
                                                "source": "structural_fudge"}
    return resolved
