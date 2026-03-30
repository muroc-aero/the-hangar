"""Input validation for OpenConcept MCP tools.

These validators run *before* analysis to catch invalid parameters early.
"""

from __future__ import annotations

from hangar.sdk.errors import UserInputError
from hangar.ocp.config.defaults import PROPULSION_ARCHITECTURES
from hangar.ocp.config.limits import (
    AIRSPEED_MAX_KN,
    AIRSPEED_MIN_KN,
    BATTERY_SPEC_ENERGY_MAX,
    BATTERY_SPEC_ENERGY_MIN,
    CLIMB_VS_MAX,
    CLIMB_VS_MIN,
    CRUISE_ALTITUDE_MAX_FT,
    CRUISE_ALTITUDE_MIN_FT,
    MISSION_RANGE_MAX_NM,
    MISSION_RANGE_MIN_NM,
    NUM_NODES_MAX,
    NUM_NODES_MIN,
)


def validate_architecture(architecture: str) -> None:
    """Raise UserInputError if architecture is not recognized."""
    if architecture not in PROPULSION_ARCHITECTURES:
        valid = ", ".join(sorted(PROPULSION_ARCHITECTURES))
        raise UserInputError(
            f"Unknown propulsion architecture {architecture!r}. "
            f"Valid architectures: {valid}"
        )


def validate_mission_type(mission_type: str) -> None:
    """Raise UserInputError if mission_type is not recognized."""
    valid = {"full", "basic", "with_reserve"}
    if mission_type not in valid:
        raise UserInputError(
            f"Unknown mission_type {mission_type!r}. "
            f"Valid types: {', '.join(sorted(valid))}"
        )


def validate_num_nodes(num_nodes: int) -> None:
    """Validate num_nodes is odd (2N+1) and within bounds.

    OpenConcept uses Simpson's rule integration which requires an odd number
    of nodes.
    """
    if not isinstance(num_nodes, int) or num_nodes < NUM_NODES_MIN:
        raise UserInputError(
            f"num_nodes must be an integer >= {NUM_NODES_MIN}, got {num_nodes}"
        )
    if num_nodes > NUM_NODES_MAX:
        raise UserInputError(
            f"num_nodes must be <= {NUM_NODES_MAX}, got {num_nodes}"
        )
    if num_nodes % 2 == 0:
        raise UserInputError(
            f"num_nodes must be ODD (2N+1) for Simpson's rule integration, "
            f"got {num_nodes}. Try {num_nodes + 1}."
        )


def validate_mission_params(params: dict) -> None:
    """Validate mission parameter ranges."""
    cruise_alt = params.get("cruise_altitude_ft")
    if cruise_alt is not None:
        if not (CRUISE_ALTITUDE_MIN_FT <= cruise_alt <= CRUISE_ALTITUDE_MAX_FT):
            raise UserInputError(
                f"cruise_altitude must be between {CRUISE_ALTITUDE_MIN_FT} and "
                f"{CRUISE_ALTITUDE_MAX_FT} ft, got {cruise_alt}"
            )

    mission_range = params.get("mission_range_NM")
    if mission_range is not None:
        if not (MISSION_RANGE_MIN_NM <= mission_range <= MISSION_RANGE_MAX_NM):
            raise UserInputError(
                f"mission_range must be between {MISSION_RANGE_MIN_NM} and "
                f"{MISSION_RANGE_MAX_NM} NM, got {mission_range}"
            )

    climb_vs = params.get("climb_vs_ftmin")
    if climb_vs is not None:
        if not (CLIMB_VS_MIN <= climb_vs <= CLIMB_VS_MAX):
            raise UserInputError(
                f"climb_vs must be between {CLIMB_VS_MIN} and "
                f"{CLIMB_VS_MAX} ft/min, got {climb_vs}"
            )

    for speed_key in ["climb_Ueas_kn", "cruise_Ueas_kn", "descent_Ueas_kn"]:
        speed = params.get(speed_key)
        if speed is not None:
            if not (AIRSPEED_MIN_KN <= speed <= AIRSPEED_MAX_KN):
                raise UserInputError(
                    f"{speed_key} must be between {AIRSPEED_MIN_KN} and "
                    f"{AIRSPEED_MAX_KN} kn, got {speed}"
                )


def validate_aircraft_data_for_architecture(
    aircraft_data: dict,
    architecture: str,
) -> None:
    """Validate that the aircraft data dict has required fields for the architecture."""
    arch_info = PROPULSION_ARCHITECTURES[architecture]
    required = arch_info["required_ac_fields"]

    ac = aircraft_data.get("ac", {})
    missing = []
    for field_path in required:
        # Convert pipe-separated path to nested dict lookup
        parts = field_path.replace("ac|", "").split("|")
        current = ac
        found = True
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                found = False
                break
            current = current[part]
        if not found:
            missing.append(field_path)

    if missing:
        raise UserInputError(
            f"Aircraft data missing required fields for {architecture!r} "
            f"architecture: {', '.join(missing)}"
        )


def validate_session_ready_for_analysis(session) -> None:
    """Validate that the session has all required configuration for analysis."""
    if session.aircraft_data is None:
        raise UserInputError(
            "No aircraft configured. Call load_aircraft_template() or "
            "define_aircraft() first."
        )
    if session.propulsion_architecture is None:
        raise UserInputError(
            "No propulsion architecture set. Call set_propulsion_architecture() first."
        )


def validate_battery_specific_energy(value: float) -> None:
    """Validate battery specific energy is within realistic bounds."""
    if not (BATTERY_SPEC_ENERGY_MIN <= value <= BATTERY_SPEC_ENERGY_MAX):
        raise UserInputError(
            f"battery_specific_energy must be between {BATTERY_SPEC_ENERGY_MIN} and "
            f"{BATTERY_SPEC_ENERGY_MAX} Wh/kg, got {value}"
        )
