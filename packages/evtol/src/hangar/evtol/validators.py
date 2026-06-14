"""Input validation for evtol MCP tools.

Raises ValueError with clear messages for invalid inputs. The most important
check is :func:`validate_section_params`: evtolpy silently ignores unrecognized
JSON keys, so a mistyped parameter name would otherwise be applied to nothing
and pass unnoticed -- we reject unknown keys up front.
"""

from __future__ import annotations

from typing import Any

from hangar.evtol.config.defaults import (
    INT_KEYS,
    SECTION_SCHEMA,
    VEHICLE_TEMPLATES,
)
from hangar.evtol.config.limits import (
    BATT_SPEC_ENERGY_MAX,
    BATT_SPEC_ENERGY_MIN,
    FRACTION_KEYS,
)


def _suggest(name: str, valid: set[str]) -> str:
    """Return a short ' (did you mean X?)' hint for a near-miss key."""
    import difflib

    match = difflib.get_close_matches(name, valid, n=1, cutoff=0.6)
    return f" (did you mean {match[0]!r}?)" if match else ""


def validate_template(name: str) -> None:
    """Raise ValueError if the template name is unknown."""
    if name not in VEHICLE_TEMPLATES:
        valid = ", ".join(sorted(VEHICLE_TEMPLATES))
        raise ValueError(f"Unknown vehicle template {name!r}. Valid: {valid}")


def validate_section_params(section: str, params: dict[str, Any]) -> None:
    """Validate that ``params`` are well-formed for a config ``section``.

    Rejects unknown keys (with a typo suggestion), non-numeric values, and
    obviously non-physical values (negative magnitudes, out-of-range fractions,
    battery specific energy outside a sane window).
    """
    schema = SECTION_SCHEMA.get(section)
    if schema is None:
        raise ValueError(
            f"Unknown config section {section!r}. Valid: {sorted(SECTION_SCHEMA)}"
        )
    if not params:
        raise ValueError(f"No parameters provided for section {section!r}.")

    for key, val in params.items():
        if key not in schema:
            raise ValueError(
                f"Unknown {section} parameter {key!r}{_suggest(key, set(schema))}. "
                f"evtolpy silently ignores unrecognized keys, so this is rejected. "
                f"Valid {section} keys: {sorted(schema)}"
            )
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(
                f"{section}.{key} must be a number (got {val!r})."
            )
        if key in INT_KEYS and (val != int(val) or val < 0):
            raise ValueError(
                f"{section}.{key} must be a non-negative integer (got {val!r})."
            )
        if key in FRACTION_KEYS and not (0.0 < val <= 1.0):
            raise ValueError(
                f"{section}.{key} is a fraction/efficiency and must be in (0, 1] "
                f"(got {val})."
            )
        if key == "batt_spec_energy_w_h_p_kg" and not (
            BATT_SPEC_ENERGY_MIN <= val <= BATT_SPEC_ENERGY_MAX
        ):
            raise ValueError(
                f"power.batt_spec_energy_w_h_p_kg={val} Wh/kg is outside the "
                f"plausible range [{BATT_SPEC_ENERGY_MIN}, {BATT_SPEC_ENERGY_MAX}]."
            )
        if key.endswith(("_kg", "_m", "_m2", "_s", "_m_p_s")) and val < 0:
            raise ValueError(f"{section}.{key} must be non-negative (got {val}).")


def validate_config_present(session) -> dict:
    """Return the session config, or raise if no vehicle has been defined."""
    config = session.config
    if not config:
        raise ValueError(
            "No vehicle defined in this session. Call load_vehicle_template "
            "(or define all five config sections) first."
        )
    return config


def validate_sweep_param(param: str) -> tuple[str, str]:
    """Validate a dotted sweep parameter ``section.key``; return (section, key)."""
    if "." not in param:
        raise ValueError(
            f"Sweep parameter must be 'section.key' (e.g. "
            f"'power.batt_spec_energy_w_h_p_kg'); got {param!r}."
        )
    section, key = param.split(".", 1)
    schema = SECTION_SCHEMA.get(section)
    if schema is None:
        raise ValueError(
            f"Unknown sweep section {section!r}. Valid: {sorted(SECTION_SCHEMA)}"
        )
    if key not in schema:
        raise ValueError(
            f"Unknown sweep key {key!r} for section {section!r}"
            f"{_suggest(key, set(schema))}. Valid: {sorted(schema)}"
        )
    return section, key
