"""Aircraft definition tools: load templates and define custom configurations."""

from __future__ import annotations

import copy
from typing import Annotated

from hangar.ocp.config.aircraft_templates import AIRCRAFT_TEMPLATES
from hangar.ocp.state import sessions as _sessions


async def list_aircraft_templates() -> dict:
    """List all built-in aircraft templates with summary specifications.

    Returns a dict of template names with descriptions, categories,
    default propulsion architectures, and key specs (MTOW, propulsion, wing area, pax).
    """
    templates = {}
    for name, info in AIRCRAFT_TEMPLATES.items():
        templates[name] = {
            "description": info["description"],
            "category": info["category"],
            "default_architecture": info["default_architecture"],
            "summary": info["summary"],
        }
    return {"templates": templates, "count": len(templates)}


async def load_aircraft_template(
    template: Annotated[
        str,
        "Built-in template name: 'caravan', 'b738', 'kingair', 'tbm850'",
    ],
    overrides: Annotated[
        dict | None,
        "Optional parameter overrides as nested dict matching the aircraft data structure. "
        "Example: {'ac': {'weights': {'MTOW': {'value': 4500, 'units': 'kg'}}}}",
    ] = None,
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Load a built-in aircraft data template into the session.

    Optionally override specific parameters with the ``overrides`` dict.
    This sets the aircraft configuration but does NOT set the propulsion
    architecture -- call ``set_propulsion_architecture()`` next.

    Returns the aircraft data summary and default architecture suggestion.
    """
    if template not in AIRCRAFT_TEMPLATES:
        valid = ", ".join(sorted(AIRCRAFT_TEMPLATES))
        raise ValueError(
            f"Unknown template {template!r}. Available: {valid}"
        )

    info = AIRCRAFT_TEMPLATES[template]
    data = copy.deepcopy(info["data"])

    # Apply overrides
    if overrides:
        _deep_merge(data, overrides)

    session = _sessions.get(session_id)
    session.aircraft_data = data
    session.aircraft_template = template
    session.invalidate_cache()

    return {
        "template": template,
        "description": info["description"],
        "default_architecture": info["default_architecture"],
        "aircraft_data_summary": _summarize_aircraft_data(data),
        "next_step": (
            f"Call set_propulsion_architecture('{info['default_architecture']}') "
            "or choose a different architecture."
        ),
    }


async def define_aircraft(
    # Aerodynamics
    CLmax_TO: Annotated[float, "Max CL at takeoff"] = 2.25,
    e: Annotated[float, "Oswald efficiency factor"] = 0.8,
    CD0_cruise: Annotated[float, "Zero-lift drag coeff (cruise)"] = 0.027,
    CD0_TO: Annotated[float, "Zero-lift drag coeff (takeoff)"] = 0.033,
    # Wing geometry
    S_ref: Annotated[float, "Wing reference area in m^2"] = 26.0,
    AR: Annotated[float, "Wing aspect ratio"] = 9.69,
    c4sweep: Annotated[float, "Quarter-chord sweep in deg"] = 1.0,
    taper: Annotated[float, "Taper ratio"] = 0.625,
    toverc: Annotated[float, "Thickness-to-chord ratio"] = 0.19,
    # Fuselage
    fuselage_S_wet: Annotated[float | None, "Fuselage wetted area in m^2"] = None,
    fuselage_width: Annotated[float | None, "Fuselage width in m"] = None,
    fuselage_length: Annotated[float | None, "Fuselage length in m"] = None,
    fuselage_height: Annotated[float | None, "Fuselage height in m"] = None,
    # Empennage
    hstab_S_ref: Annotated[float, "Horizontal stab reference area in m^2"] = 6.93,
    hstab_c4_to_wing_c4: Annotated[float, "Hstab-to-wing quarter-chord distance in m"] = 7.28,
    vstab_S_ref: Annotated[float, "Vertical stab reference area in m^2"] = 3.34,
    # Landing gear
    nosegear_length: Annotated[float, "Nose gear length in m"] = 0.9,
    maingear_length: Annotated[float, "Main gear length in m"] = 0.92,
    # Weights
    MTOW: Annotated[float, "Max takeoff weight in kg"] = 3970.0,
    W_fuel_max: Annotated[float, "Max fuel weight in kg"] = 1018.0,
    MLW: Annotated[float, "Max landing weight in kg"] = 3358.0,
    OEW: Annotated[float | None, "Operating empty weight in kg (turbofan only)"] = None,
    W_battery: Annotated[float | None, "Battery weight in kg (hybrid/electric)"] = None,
    # Propulsion
    engine_rating: Annotated[float, "Engine rated power in hp (or thrust in lbf for turbofan)"] = 675.0,
    engine_rating_units: Annotated[str, "Units for engine rating: 'hp' or 'lbf'"] = "hp",
    propeller_diameter: Annotated[float | None, "Propeller diameter in m"] = None,
    motor_rating: Annotated[float | None, "Motor rated power in hp (hybrid/electric)"] = None,
    generator_rating: Annotated[float | None, "Generator rated power in hp (hybrid)"] = None,
    # Other
    num_passengers_max: Annotated[int, "Max passenger count"] = 2,
    q_cruise: Annotated[float, "Cruise dynamic pressure in lb/ft^2"] = 56.96,
    num_engines: Annotated[int | None, "Number of engines (multi-engine only)"] = None,
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Define a custom aircraft configuration from individual parameters.

    Builds the OpenConcept aircraft data dict and stores it in the session.
    Call ``set_propulsion_architecture()`` next to select the propulsion system.
    """
    data: dict = {"ac": {}}
    ac = data["ac"]

    # Aerodynamics
    ac["aero"] = {
        "CLmax_TO": {"value": CLmax_TO},
        "polar": {
            "e": {"value": e},
            "CD0_TO": {"value": CD0_TO},
            "CD0_cruise": {"value": CD0_cruise},
        },
    }

    # Geometry
    geom: dict = {
        "wing": {
            "S_ref": {"value": S_ref, "units": "m**2"},
            "AR": {"value": AR},
            "c4sweep": {"value": c4sweep, "units": "deg"},
            "taper": {"value": taper},
            "toverc": {"value": toverc},
        },
        "hstab": {
            "S_ref": {"value": hstab_S_ref, "units": "m**2"},
            "c4_to_wing_c4": {"value": hstab_c4_to_wing_c4, "units": "m"},
        },
        "vstab": {"S_ref": {"value": vstab_S_ref, "units": "m**2"}},
        "nosegear": {"length": {"value": nosegear_length, "units": "m"}},
        "maingear": {"length": {"value": maingear_length, "units": "m"}},
    }

    if fuselage_S_wet is not None:
        geom["fuselage"] = {
            "S_wet": {"value": fuselage_S_wet, "units": "m**2"},
            "width": {"value": fuselage_width or 1.7, "units": "m"},
            "length": {"value": fuselage_length or 12.0, "units": "m"},
            "height": {"value": fuselage_height or 1.7, "units": "m"},
        }

    ac["geom"] = geom

    # Weights
    weights: dict = {
        "MTOW": {"value": MTOW, "units": "kg"},
        "W_fuel_max": {"value": W_fuel_max, "units": "kg"},
        "MLW": {"value": MLW, "units": "kg"},
    }
    if OEW is not None:
        weights["OEW"] = {"value": OEW, "units": "kg"}
    if W_battery is not None:
        weights["W_battery"] = {"value": W_battery, "units": "kg"}
    ac["weights"] = weights

    # Propulsion
    propulsion: dict = {
        "engine": {"rating": {"value": engine_rating, "units": engine_rating_units}},
    }
    if propeller_diameter is not None:
        propulsion["propeller"] = {"diameter": {"value": propeller_diameter, "units": "m"}}
    if motor_rating is not None:
        propulsion["motor"] = {"rating": {"value": motor_rating, "units": "hp"}}
    if generator_rating is not None:
        propulsion["generator"] = {"rating": {"value": generator_rating, "units": "hp"}}
    ac["propulsion"] = propulsion

    # Other
    ac["num_passengers_max"] = {"value": num_passengers_max}
    ac["q_cruise"] = {"value": q_cruise, "units": "lb*ft**-2"}
    if num_engines is not None:
        ac["num_engines"] = {"value": num_engines}

    session = _sessions.get(session_id)
    session.aircraft_data = data
    session.aircraft_template = None
    session.invalidate_cache()

    return {
        "status": "Aircraft defined",
        "aircraft_data_summary": _summarize_aircraft_data(data),
        "next_step": "Call set_propulsion_architecture() to select the propulsion system.",
    }


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base dict (mutates base)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _summarize_aircraft_data(data: dict) -> dict:
    """Extract a human-readable summary from an aircraft data dict."""
    ac = data.get("ac", {})
    summary: dict = {}

    mtow = ac.get("weights", {}).get("MTOW", {})
    if mtow:
        summary["MTOW"] = f"{mtow.get('value')} {mtow.get('units', 'kg')}"

    sref = ac.get("geom", {}).get("wing", {}).get("S_ref", {})
    if sref:
        summary["wing_S_ref"] = f"{sref.get('value')} {sref.get('units', 'm**2')}"

    ar = ac.get("geom", {}).get("wing", {}).get("AR", {})
    if ar:
        summary["wing_AR"] = ar.get("value")

    eng = ac.get("propulsion", {}).get("engine", {}).get("rating", {})
    if eng:
        summary["engine_rating"] = f"{eng.get('value')} {eng.get('units', 'hp')}"

    pax = ac.get("num_passengers_max", {})
    if pax:
        summary["max_passengers"] = pax.get("value")

    return summary
