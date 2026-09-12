"""Name registry for external subsystems, mirroring MISSION_TEMPLATES."""

from __future__ import annotations

import difflib
from typing import Any

from hangar.avy.subsystems import oas_wing_mass

EXTERNAL_SUBSYSTEMS: dict[str, dict[str, Any]] = {
    "oas_wing_mass": {
        "description": (
            "OpenAeroStruct wingbox wing mass (upstream Aviary's own OAS "
            "integration): a pre-mission nested aerostructural "
            "sub-optimization (cruise + 2.5g maneuver, strength and "
            "fuel-volume constraints) whose optimized wing mass overrides "
            "the empirical FLOPS value on Aircraft.Wing.MASS. Adds one "
            "nested sub-opt per outer optimizer evaluation -- expect a "
            "coupled sizing to run minutes, not seconds."
        ),
        "supported_decks": oas_wing_mass.SUPPORTED_DECKS,
        "config_keys": sorted(oas_wing_mass.VALID_CONFIG_KEYS),
        "validate": oas_wing_mass.resolve_config,
        "build": oas_wing_mass.build_oas_wing_mass,
    },
}


def _suggest(key: str, valid) -> str:
    close = difflib.get_close_matches(key, list(valid), n=1)
    return f" Did you mean {close[0]!r}?" if close else ""


def validate_subsystem_spec(name: str, config: dict | None = None) -> dict:
    """Validate a (name, config) pair; return the resolved config.

    Pure validation -- safe in any venv, used by the tools before a run is
    attempted and by the omd worker when materializing specs.
    """
    if name not in EXTERNAL_SUBSYSTEMS:
        raise ValueError(
            f"Unknown external subsystem {name!r}. Available: "
            f"{sorted(EXTERNAL_SUBSYSTEMS)}.{_suggest(name, EXTERNAL_SUBSYSTEMS)}"
        )
    return EXTERNAL_SUBSYSTEMS[name]["validate"](config)


def build_external_subsystems(specs: list[dict] | None) -> list:
    """Materialize [{'name': ..., 'config': {...}}, ...] into builders.

    Requires the Aviary venv (builders import aviary/openaerostruct).
    """
    builders = []
    for spec in specs or []:
        name = spec["name"]
        validate_subsystem_spec(name, spec.get("config"))
        builders.append(EXTERNAL_SUBSYSTEMS[name]["build"](spec.get("config"), name=name))
    return builders


def list_external_subsystems_info() -> dict[str, dict[str, Any]]:
    """Registry metadata for the list tool (no callables)."""
    return {
        name: {
            "description": entry["description"],
            "supported_decks": list(entry["supported_decks"]),
            "config_keys": list(entry["config_keys"]),
        }
        for name, entry in EXTERNAL_SUBSYSTEMS.items()
    }
