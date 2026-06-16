"""Segment and mass-component ordering for the native evt model.

Vendored copies of the upstream ordering (kept identical to
``hangar.evt.results``) so the native package has no runtime dependency on the
evt server. These orders define the layout of the ``segment_energy_kw_hr`` /
``segment_power_kw`` (18,) and ``mass_breakdown_kg`` (15,) vectors and must not
be reordered: the omd summary extractor, plots, and parity suite all index by
them.
"""

from __future__ import annotations

# 18 mission segments in upstream order.
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

# Indices of the seven reserve segments (for the reserve-energy roll-up).
RESERVE_INDICES = [i for i, (k, _) in enumerate(SEGMENTS) if k.startswith("reserve_")]

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

MASS_KEYS = [k for k, _ in MASS_COMPONENTS]
