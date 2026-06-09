"""Normalization of unit-tagged operating-point values.

The plan schema allows an operating-point value either bare (number,
string, or array) or unit-tagged: ``{"value": ..., "units": "..."}``.
Factories expect plain values in canonical units, so the materializer
normalizes the whole operating_points mapping here, in one place,
before any factory sees it. Unit-tagged values are converted to the
canonical units with OpenMDAO's unit machinery; a tag on a key whose
canonical units are unknown is an error rather than a silent pass-through.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from openmdao.utils.units import convert_units

# Canonical units each factory expects, by operating-point key.
# None means dimensionless (a units tag on these keys is an error).
# Keep in sync with the IndepVarComp units in factories/oas.py,
# factories/oas_aero.py, and the set_val units in factories/pyc.py.
_CANONICAL_UNITS: dict[str, str | None] = {
    # OAS (oas/AeroPoint, oas/AerostructPoint)
    "velocity": "m/s",
    "alpha": "deg",
    "alpha_maneuver": "deg",
    "beta": "deg",
    "Mach_number": None,
    "re": "1/m",
    "reynolds_number": "1/m",
    "rho": "kg/m**3",
    "density": "kg/m**3",
    "CT": "1/s",
    "R": "m",
    "W0": "kg",
    "W0_without_point_masses": "kg",
    "speed_of_sound": "m/s",
    "load_factor": None,
    "empty_cg": "m",
    "cg": "m",
    "height_agl": "m",
    "omega": "deg/s",
    "point_masses": "kg",
    "point_mass_locations": "m",
    "fuel_mass": "kg",
    # pyCycle (pyc/*)
    "alt": "ft",
    "MN": None,
    "Fn_target": "lbf",
    "T4_target": "degR",
    "T_ab_target": "degR",
    "pwr_target": "hp",
    "nozz_PR_target": None,
    "BPR_target": None,
    "ab_FAR": None,
    # paraboloid
    "x": None,
    "y": None,
}


def _resolve_value(key: str, raw: Any) -> Any:
    """Return the plain value for one operating-point entry.

    Bare values pass through. ``{"value": ...}`` is unwrapped;
    ``{"value": ..., "units": ...}`` is converted to the key's
    canonical units.
    """
    if not (isinstance(raw, dict) and "value" in raw):
        return raw

    value = raw["value"]
    units = raw.get("units")
    if units is None:
        return value

    if key not in _CANONICAL_UNITS:
        raise ValueError(
            f"Operating point '{key}' has a units tag ({units!r}) but its "
            f"canonical units are unknown; pass a bare value in the units "
            f"the factory expects, or add the key to op_points._CANONICAL_UNITS."
        )
    target = _CANONICAL_UNITS[key]
    if target is None:
        raise ValueError(
            f"Operating point '{key}' is dimensionless; remove the "
            f"units tag ({units!r})."
        )

    try:
        if isinstance(value, (list, tuple)):
            arr = np.asarray(value, dtype=float)
            return convert_units(arr, units, target).tolist()
        return convert_units(float(value), units, target)
    except Exception as exc:
        raise ValueError(
            f"Cannot convert operating point '{key}' from {units!r} "
            f"to {target!r}: {exc}"
        ) from exc


def _normalize_flat(op: dict) -> dict:
    return {key: _resolve_value(key, raw) for key, raw in op.items()}


def normalize_operating_points(op: Any) -> Any:
    """Normalize a full operating_points mapping (single- or multipoint)."""
    if not isinstance(op, dict):
        return op
    if "flight_points" in op:
        out = dict(op)
        out["flight_points"] = [
            _normalize_flat(fp) if isinstance(fp, dict) else fp
            for fp in op["flight_points"]
        ]
        if isinstance(op.get("shared"), dict):
            out["shared"] = _normalize_flat(op["shared"])
        return out
    return _normalize_flat(op)


__all__ = ["normalize_operating_points"]
