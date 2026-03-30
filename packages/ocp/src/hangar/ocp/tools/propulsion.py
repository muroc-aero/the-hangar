"""Propulsion architecture selection tool."""

from __future__ import annotations

from typing import Annotated

from hangar.ocp.config.defaults import PROPULSION_ARCHITECTURES
from hangar.ocp.state import sessions as _sessions
from hangar.ocp.validators import (
    validate_architecture,
    validate_aircraft_data_for_architecture,
    validate_battery_specific_energy,
)


async def set_propulsion_architecture(
    architecture: Annotated[
        str,
        "Propulsion system architecture: 'turboprop', 'twin_turboprop', "
        "'series_hybrid', 'twin_series_hybrid', 'twin_turbofan'",
    ],
    motor_rating: Annotated[
        float | None,
        "Motor rated power in hp (required for hybrid/electric architectures)",
    ] = None,
    generator_rating: Annotated[
        float | None,
        "Generator rated power in hp (required for hybrid architectures)",
    ] = None,
    battery_weight: Annotated[
        float | None,
        "Battery weight in kg (required for hybrid/electric architectures)",
    ] = None,
    battery_specific_energy: Annotated[
        float | None,
        "Battery specific energy in Wh/kg (hybrid/electric, default 300)",
    ] = None,
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Select and configure the propulsion system architecture.

    Must be called after ``load_aircraft_template()`` or ``define_aircraft()``.
    Updates the aircraft data dict with any provided propulsion overrides
    (motor_rating, generator_rating, battery_weight) and stores the
    architecture selection in the session.

    Returns architecture details and what the next step should be.
    """
    validate_architecture(architecture)

    session = _sessions.get(session_id)
    if session.aircraft_data is None:
        raise ValueError(
            "No aircraft configured. Call load_aircraft_template() or "
            "define_aircraft() first."
        )

    arch_info = PROPULSION_ARCHITECTURES[architecture]

    # Apply propulsion parameter overrides to aircraft data
    ac = session.aircraft_data.get("ac", {})
    overrides: dict = {}

    if motor_rating is not None:
        ac.setdefault("propulsion", {}).setdefault("motor", {})["rating"] = {
            "value": motor_rating,
            "units": "hp",
        }
        overrides["motor_rating_hp"] = motor_rating

    if generator_rating is not None:
        ac.setdefault("propulsion", {}).setdefault("generator", {})["rating"] = {
            "value": generator_rating,
            "units": "hp",
        }
        overrides["generator_rating_hp"] = generator_rating

    if battery_weight is not None:
        ac.setdefault("weights", {})["W_battery"] = {
            "value": battery_weight,
            "units": "kg",
        }
        overrides["battery_weight_kg"] = battery_weight

    if battery_specific_energy is not None:
        validate_battery_specific_energy(battery_specific_energy)
        overrides["battery_specific_energy"] = battery_specific_energy

    # Validate that required fields are present
    validate_aircraft_data_for_architecture(session.aircraft_data, architecture)

    # Store in session
    session.propulsion_architecture = architecture
    session.propulsion_overrides = overrides
    session.invalidate_cache()

    return {
        "architecture": architecture,
        "description": f"{arch_info['prop_class']} propulsion system",
        "has_fuel": arch_info["has_fuel"],
        "has_battery": arch_info["has_battery"],
        "num_engines": arch_info["num_engines"],
        "overrides_applied": overrides,
        "next_step": "Call configure_mission() to set the mission profile, then run_mission_analysis().",
    }
