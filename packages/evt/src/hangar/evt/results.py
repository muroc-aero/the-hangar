"""Harvest results from a built evtolpy ``Aircraft``.

The three core upstream analysis lanes read aircraft properties:
  * mission-segment-energy -> ``<seg>_energy_kw_hr`` for 18 segments
  * mission-segment-power   -> ``<seg>_avg_electric_power_kw`` for 18 segments
  * mission-segment-weight  -> component masses + ``empty_mass_kg``, and the
                               ``_iterate_mtow()`` convergence history

These functions reproduce exactly what the upstream ``log_*.py`` scripts emit,
so the MCP/CLI layer is parity-checkable against the direct API.
"""

from __future__ import annotations

import math
from typing import Any

# 18 mission segments in upstream order (the CSV column order of the log
# scripts). ``key`` is the attribute stem; ``label`` is the human label.
SEGMENTS: list[tuple[str, str]] = [
    ("depart_taxi", "Depart Taxi"),
    ("hover_climb", "Hover Climb"),
    ("trans_climb", "Transition Climb"),
    ("depart_proc", "Depart Procedures"),
    ("accel_climb", "Accelerate Climb"),
    ("cruise", "Cruise"),
    ("decel_descend", "Decelerate Descend"),
    ("arrive_proc", "Arrive Procedures"),
    ("trans_descend", "Transition Descend"),
    ("hover_descend", "Hover Descend"),
    ("arrive_taxi", "Arrive Taxi"),
    ("reserve_hover_climb", "Reserve Hover Climb"),
    ("reserve_trans_climb", "Reserve Transition Climb"),
    ("reserve_accel_climb", "Reserve Accelerate Climb"),
    ("reserve_cruise", "Reserve Cruise"),
    ("reserve_decel_descend", "Reserve Decelerate Descend"),
    ("reserve_trans_descend", "Reserve Transition Descend"),
    ("reserve_hover_descend", "Reserve Hover Descend"),
]

SEGMENT_KEYS = [k for k, _ in SEGMENTS]
SEGMENT_LABELS = [lbl for _, lbl in SEGMENTS]

# Component mass attributes in upstream mass-breakdown order.
MASS_COMPONENTS: list[tuple[str, str]] = [
    ("wing_mass_kg", "Wing"),
    ("horiz_tail_mass_kg", "Horizontal Tail"),
    ("vert_tail_mass_kg", "Vertical Tail"),
    ("fuselage_mass_kg", "Fuselage"),
    ("boom_mass_kg", "Boom"),
    ("landing_gear_mass_kg", "Landing Gear"),
    ("epu_mass_kg", "EPU"),
    ("lift_rotor_hub_mass_kg", "Lift Rotor + Hub"),
    ("tilt_rotor_mass_kg", "Tilt Rotor"),
    ("actuator_mass_kg", "Actuators"),
    ("furnishings_mass_kg", "Furnishings"),
    ("environmental_control_system_mass_kg", "ECS"),
    ("avionics_mass_kg", "Avionics"),
    ("hivolt_power_dist_mass_kg", "High-Volt Power Dist."),
    ("lovolt_power_coms_mass_kg", "Low-Volt Power & Comms"),
]


def _f(val) -> float:
    return float(val)


def extract_energy_table(aircraft) -> dict[str, float]:
    """Per-segment energy (kW*hr), keyed by segment stem."""
    return {k: _f(getattr(aircraft, f"{k}_energy_kw_hr")) for k in SEGMENT_KEYS}


def extract_power_table(aircraft) -> dict[str, float]:
    """Per-segment average electric power (kW), keyed by segment stem."""
    return {
        k: _f(getattr(aircraft, f"{k}_avg_electric_power_kw")) for k in SEGMENT_KEYS
    }


def extract_mass_breakdown(aircraft) -> dict[str, float]:
    """Component empty-mass breakdown (kg), keyed by attribute name."""
    return {attr: _f(getattr(aircraft, attr)) for attr, _ in MASS_COMPONENTS}


def extract_geometry(aircraft) -> dict[str, float]:
    """Derived geometry summary."""
    return {
        "wing_area_m2": _f(aircraft.wing_area_m2),
        "wing_aspect_ratio": _f(aircraft.wing_aspect_ratio),
        "wing_mac_m": _f(aircraft.wing_mac_m),
        "wing_root_chord_m": _f(aircraft.wing_root_chord_m),
        "horiz_tail_area_m2": _f(aircraft.horiz_tail_area_m2),
        "vert_tail_area_m2": _f(aircraft.vert_tail_area_m2),
        "fuselage_wetted_area_m2": _f(aircraft.fuselage_wetted_area_m2),
        "fuselage_fineness_ratio": _f(aircraft.fuselage_fineness_ratio),
    }


def extract_aero(aircraft) -> dict[str, float]:
    """Cruise aerodynamic summary."""
    return {
        "cruise_cl": _f(aircraft.cruise_cl),
        "cruise_cd": _f(aircraft.cruise_cd),
        "cruise_l_p_d": _f(aircraft.cruise_l_p_d),
        "total_drag_coef": _f(aircraft.total_drag_coef),
        "induced_drag_cdi": _f(aircraft.induced_drag_cdi),
    }


def extract_propulsion(aircraft) -> dict[str, float]:
    """Propulsion/rotor summary."""
    return {
        "disk_loading_kg_p_m2": _f(aircraft.disk_loading_kg_p_m2),
        "rotor_solidity": _f(aircraft.rotor_solidity),
        "over_torque_factor": _f(aircraft.over_torque_factor),
    }


def extract_mission_results(aircraft) -> dict[str, Any]:
    """Full mission analysis payload at the as-configured MTOW.

    Reproduces the three core upstream lanes (energy, power, mass breakdown)
    plus geometry/aero/propulsion summaries and total-energy roll-ups. No MTOW
    iteration is run here -- this matches upstream's ``log_mission_segment_*``
    and ``log_mass_breakdown`` scripts, which read an unsized aircraft.
    """
    energy = extract_energy_table(aircraft)
    power = extract_power_table(aircraft)
    masses = extract_mass_breakdown(aircraft)

    return {
        "max_takeoff_mass_kg": _f(aircraft.max_takeoff_mass_kg),
        "segment_labels": dict(zip(SEGMENT_KEYS, SEGMENT_LABELS)),
        "energy_kw_hr": energy,
        "avg_electric_power_kw": power,
        "mass_breakdown_kg": masses,
        "totals": {
            "total_mission_energy_kw_hr": _f(aircraft.total_mission_energy_kw_hr),
            "total_reserve_mission_energy_kw_hr": _f(
                aircraft.total_reserve_mission_energy_kw_hr
            ),
            "empty_mass_kg": _f(aircraft.empty_mass_kg),
            "battery_mass_kg": _f(aircraft.battery_mass_kg),
            "payload_kg": _f(aircraft.payload_kg),
            "payload_mass_frac": _f(aircraft.payload_mass_frac),
        },
        "geometry": extract_geometry(aircraft),
        "aero": extract_aero(aircraft),
        "propulsion": extract_propulsion(aircraft),
    }


def run_mtow_iteration(aircraft) -> dict[str, Any]:
    """Run evtolpy's MTOW convergence loop and harvest the result.

    Reproduces upstream ``log_mtow_iteration``: calls ``_iterate_mtow()`` (which
    mutates the aircraft's MTOW in place) and returns the converged MTOW plus the
    full per-iteration history. ``_iterate_mtow`` raises ``ValueError`` on
    divergence (the upstream safeguard); callers surface that as a tool error.
    """
    initial_mtow = _f(aircraft.max_takeoff_mass_kg)
    final_mtow, history = aircraft._iterate_mtow()

    # Convergence is "by construction" when the loop returns under tolerance;
    # detect the non-converged exit (loop ran to max_iter without |delta|<tol).
    last = history[-1] if history else {}
    converged = bool(history) and abs(last.get("delta_kg", math.inf)) < 1e-3

    return {
        "initial_mtow_kg": initial_mtow,
        "sized_mtow_kg": _f(final_mtow),
        "converged": converged,
        "iterations": len(history),
        "history": [
            {
                "iteration": int(row["iteration"]),
                "mtow_guess_kg": _f(row["mtow_guess_kg"]),
                "new_mtow_kg": _f(row["new_mtow_kg"]),
                "delta_kg": _f(row["delta_kg"]),
                "empty_mass_kg": _f(row["empty_mass_kg"]),
                "battery_mass_kg": _f(row["battery_mass_kg"]),
                "payload_mass_kg": _f(row["payload_mass_kg"]),
                "total_energy_converged_kw_hr": _f(
                    row["total_energy_converged_kw_hr"]
                ),
            }
            for row in history
        ],
        # Mass breakdown at the converged MTOW.
        "mass_breakdown_kg": extract_mass_breakdown(aircraft),
        "totals": {
            "empty_mass_kg": _f(aircraft.empty_mass_kg),
            "battery_mass_kg": _f(aircraft.battery_mass_kg),
            "payload_kg": _f(aircraft.payload_kg),
            "total_mission_energy_kw_hr": _f(aircraft.total_mission_energy_kw_hr),
        },
    }
