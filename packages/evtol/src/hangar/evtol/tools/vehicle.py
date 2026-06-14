"""Vehicle / config definition tools.

evtolpy is configured by a single five-section JSON config (aircraft, mission,
power, propulsion, environ). These tools accumulate that config in the session:
``load_vehicle_template`` seeds a complete baseline, and the section setters
merge overrides onto it. Each setter validates parameter names against the
known schema -- evtolpy silently ignores unrecognized keys, so a typo would
otherwise vanish.
"""

from __future__ import annotations

from typing import Annotated, Any

from hangar.evtol.state import sessions as _sessions
from hangar.evtol.config.defaults import VEHICLE_TEMPLATES, get_template
from hangar.evtol.validators import validate_section_params, validate_template


async def list_vehicle_templates() -> dict:
    """List the built-in vehicle templates and their descriptions."""
    return {
        "templates": {
            name: meta["description"] for name, meta in VEHICLE_TEMPLATES.items()
        },
        "count": len(VEHICLE_TEMPLATES),
    }


async def load_vehicle_template(
    template: Annotated[
        str,
        "Template name. Valid: " + ", ".join(sorted(VEHICLE_TEMPLATES)),
    ] = "test_all",
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Seed the session config from a complete, upstream-validated template.

    Call this first. The template fills all five config sections; refine it with
    define_vehicle / configure_mission / set_power / set_propulsion /
    set_environment, then run_mission_analysis or run_sizing.
    """
    validate_template(template)
    session = _sessions.get(session_id)
    session.config = get_template(template)
    return {
        "template": template,
        "description": VEHICLE_TEMPLATES[template]["description"],
        "sections": sorted(session.config),
        "status": f"Loaded template '{template}'. Override any section, then analyse.",
    }


async def _apply_section(section: str, params: dict[str, Any], session_id: str) -> dict:
    """Validate and merge ``params`` into a config section (shared by setters)."""
    validate_section_params(section, params)
    session = _sessions.get(session_id)
    session.config.setdefault(section, {})
    session.config[section].update(params)
    return {
        "section": section,
        "updated": sorted(params),
        "status": f"Applied {len(params)} override(s) to '{section}'.",
    }


async def define_vehicle(
    params: Annotated[
        dict[str, Any],
        "Aircraft-section overrides as {key: value}, e.g. "
        "{'wingspan_m': 14.0, 'payload_kg': 400}. Keys are validated against the "
        "aircraft schema (geometry, masses, aero coefficients, tail volumes).",
    ],
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Override aircraft-section parameters (geometry, fixed masses, aero coeffs)."""
    return await _apply_section("aircraft", params, session_id)


async def set_propulsion(
    params: Annotated[
        dict[str, Any],
        "Propulsion-section overrides, e.g. "
        "{'rotor_count': 8, 'rotor_diameter_m': 2.5, 'tip_mach': 0.45}.",
    ],
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Override propulsion parameters (rotor counts/diameters, tip Mach, efficiency)."""
    return await _apply_section("propulsion", params, session_id)


async def set_power(
    params: Annotated[
        dict[str, Any],
        "Power-section overrides, e.g. "
        "{'batt_spec_energy_w_h_p_kg': 280.0, 'epu_effic': 0.92}.",
    ],
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Override power parameters (battery specific energy, pack factors, efficiencies)."""
    return await _apply_section("power", params, session_id)


async def set_environment(
    params: Annotated[
        dict[str, Any],
        "Environment-section overrides, e.g. "
        "{'air_density_sea_lvl_kg_p_m3': 1.18}.",
    ],
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Override environment parameters (densities, gravity, viscosities, sound speed)."""
    return await _apply_section("environ", params, session_id)
