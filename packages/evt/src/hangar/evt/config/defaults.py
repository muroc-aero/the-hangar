"""Vehicle templates and the config schema for the evt server.

evtolpy's ``Aircraft`` constructor reads a JSON config with five required
sections -- ``aircraft``, ``mission``, ``power``, ``propulsion``, ``environ``
-- and indexes keys directly (a missing key raises ``KeyError``). So a config
must be *complete* before it can be built. Templates here provide complete,
upstream-validated baselines; section setters merge user overrides onto a
template.

The ``*_SCHEMA`` frozensets are the known key sets per section. evtolpy
silently ignores unrecognized JSON keys, so the validators reject unknown
keys up front rather than letting a typo pass through unnoticed.
"""

from __future__ import annotations

import copy

# ---------------------------------------------------------------------------
# Vehicle templates
# ---------------------------------------------------------------------------

# Lift+cruise eVTOL baseline -- vendored from upstream sample-inputs/test-all.json
# at the pinned evtolpy ref. This is the parity baseline.
_TEST_ALL = {
    "aircraft": {
        "max_takeoff_mass_kg": 3175.0,
        "payload_kg": 454.0,
        "vehicle_cl_max": 2.08,
        "wing_taper_ratio": 0.278,
        "wingspan_m": 15.0,
        "d_value_m": 15.75,
        "stall_speed_m_p_s": 40.6,
        "fuselage_l_m": 8.26,
        "fuselage_w_m": 1.30,
        "fuselage_h_m": 1.35,
        "wing_airfoil_cd_at_cruise_cl": 0.007,
        "cruise_wing_lift_fraction": 0.8,
        "empennage_airfoil_cd0": 0.006,
        "span_effic_factor": 0.8,
        "trim_drag_factor": 1.02,
        "landing_gear_drag_area_m2": 0.3933,
        "excres_protub_factor": 1.02,
        "horiz_tail_vol_coeff": 0.7820,
        "vert_tail_vol_coeff": 0.03913,
        "ratio_disk_to_stopped_rotor_area": 20.95,
        "wing_t_p_c": 0.1208,
        "actuator_mass_kg": 81.6,
        "furnishings_mass_kg": 52.0,
        "environmental_control_system_mass_kg": 40.0,
        "avionics_mass_kg": 60.0,
        "hivolt_power_dist_mass_kg": 80.0,
        "lovolt_power_coms_mass_kg": 41.0,
        "mass_margin_factor": 0.05,
    },
    "environ": {
        "g_m_p_s2": 9.81,
        "sound_speed_m_p_s": 334.5,
        "air_density_sea_lvl_kg_p_m3": 1.226,
        "air_density_max_alt_kg_p_m3": 1.056,
        "kinematic_viscosity_sea_lvl_m2_p_s": 1.412e-5,
        "kinematic_viscosity_max_alt_m2_p_s": 1.281e-5,
    },
    "mission": {
        "depart_taxi_avg_h_m_p_s": 1.34,
        "depart_taxi_s": 30.0,
        "hover_climb_avg_v_m_p_s": 2.54,
        "hover_climb_s": 12.0,
        "trans_climb_avg_h_m_p_s": 24.4,
        "trans_climb_v_m_p_s": 5.1,
        "trans_climb_s": 30.0,
        "depart_proc_h_m_p_s": 48.8,
        "depart_proc_s": 18.0,
        "accel_climb_avg_h_m_p_s": 58.0,
        "accel_climb_v_m_p_s": 5.1,
        "accel_climb_s": 143.0,
        "cruise_h_m_p_s": 67.1,
        "cruise_s": 664.0,
        "decel_descend_avg_h_m_p_s": 58.0,
        "decel_descend_v_m_p_s": 5.1,
        "decel_descend_s": 143.0,
        "arrive_proc_h_m_p_s": 48.8,
        "arrive_proc_s": 18.0,
        "trans_descend_avg_h_m_p_s": 24.4,
        "trans_descend_v_m_p_s": 5.1,
        "trans_descend_s": 30.0,
        "hover_descend_avg_v_m_p_s": 2.54,
        "hover_descend_s": 12.0,
        "arrive_taxi_avg_h_m_p_s": 1.34,
        "arrive_taxi_s": 30.0,
        "reserve_hover_climb_avg_v_m_p_s": 2.54,
        "reserve_hover_climb_s": 12.0,
        "reserve_trans_climb_avg_h_m_p_s": 24.4,
        "reserve_trans_climb_v_m_p_s": 5.1,
        "reserve_trans_climb_s": 30.0,
        "reserve_accel_climb_avg_h_m_p_s": 58.0,
        "reserve_accel_climb_v_m_p_s": 5.1,
        "reserve_accel_climb_s": 24.0,
        "reserve_cruise_h_m_p_s": 67.1,
        "reserve_cruise_s": 54.0,
        "reserve_decel_descend_avg_h_m_p_s": 58.0,
        "reserve_decel_descend_v_m_p_s": 5.1,
        "reserve_decel_descend_s": 24.0,
        "reserve_trans_descend_avg_h_m_p_s": 24.4,
        "reserve_trans_descend_v_m_p_s": 5.1,
        "reserve_trans_descend_s": 30.0,
        "reserve_hover_descend_avg_v_m_p_s": 2.54,
        "reserve_hover_descend_s": 12.0,
    },
    "power": {
        "batt_spec_energy_w_h_p_kg": 232.5,
        "batt_inaccessible_energy_frac": 0.05,
        "batt_eol_capacity": 0.80,
        "batt_int_factor": 0.65,
        "epu_effic": 0.90,
        "hover_power_effic": 0.70,
    },
    "propulsion": {
        "rotor_effic": 0.80,
        "rotor_count": 12,
        "lift_rotor_count": 6,
        "tilt_rotor_count": 6,
        "pusher_rotor_count": 1,
        "rotor_diameter_m": 2.0,
        "pusher_rotor_diameter_m": 1.5,
        "tip_mach": 0.4,
        "pusher_rotor_tip_mach": 0.55,
        "rotor_avg_cl": 0.625,
    },
}


# Archer Midnight-class vehicle -- vendored from the AIAA SciTech 2026 case
# study config (examples/abu_scitech_2026/cfg/archer-midnight-1500-30.json) so a
# faithful named baseline ships with the package and is reachable on a deployed
# server (no filesystem config needed). Vectored-thrust layout: 6 tilt + 6 lift
# rotors, NO pusher (rotor_count=12). Mission timeline is a ~30 mi / 1500 ft
# profile; override mission/* (e.g. cruise_s) to retarget range. Native
# evt/Sizing closes this to ~2020 kg sized MTOW.
_ARCHER_MIDNIGHT = {
    'aircraft': {
        'max_takeoff_mass_kg': 3175.0,
        'payload_kg': 454.0,
        'vehicle_cl_max': 1.5,
        'wing_taper_ratio': 0.6,
        'wingspan_m': 15.24,
        'd_value_m': 15.24,
        'stall_speed_m_p_s': 40.6,
        'fuselage_l_m': 8.0,
        'fuselage_w_m': 1.3,
        'fuselage_h_m': 1.5,
        'wing_airfoil_cd_at_cruise_cl': 0.0065,
        'empennage_airfoil_cd0': 0.005,
        'span_effic_factor': 0.8,
        'trim_drag_factor': 1.1,
        'landing_gear_drag_area_m2': 0.07,
        'excres_protub_factor': 1.1,
        'horiz_tail_vol_coeff': 0.7,
        'vert_tail_vol_coeff': 0.06,
        'ratio_disk_to_stopped_rotor_area': 100.0,
        'wing_t_p_c': 0.18,
        'actuator_mass_kg': 69.6,
        'furnishings_mass_kg': 67.0,
        'environmental_control_system_mass_kg': 40.0,
        'avionics_mass_kg': 60.0,
        'hivolt_power_dist_mass_kg': 80.0,
        'lovolt_power_coms_mass_kg': 60.0,
        'mass_margin_factor': 0.05,
    },
    'mission': {
        'depart_taxi_avg_h_m_p_s': 1.34,
        'depart_taxi_s': 30.0,
        'hover_climb_avg_v_m_p_s': 2.54,
        'hover_climb_s': 6.0,
        'trans_climb_avg_h_m_p_s': 24.4,
        'trans_climb_v_m_p_s': 5.1,
        'trans_climb_s': 15.0,
        'depart_proc_h_m_p_s': 48.7,
        'depart_proc_s': 18.0,
        'accel_climb_avg_h_m_p_s': 57.9,
        'accel_climb_v_m_p_s': 5.1,
        'accel_climb_s': 72.0,
        'cruise_h_m_p_s': 67.1,
        'cruise_s': 558.0,
        'decel_descend_avg_h_m_p_s': 57.9,
        'decel_descend_v_m_p_s': 5.1,
        'decel_descend_s': 72.0,
        'arrive_proc_h_m_p_s': 48.7,
        'arrive_proc_s': 18.0,
        'trans_descend_avg_h_m_p_s': 24.4,
        'trans_descend_v_m_p_s': 5.1,
        'trans_descend_s': 15.0,
        'hover_descend_avg_v_m_p_s': 2.54,
        'hover_descend_s': 6.0,
        'arrive_taxi_avg_h_m_p_s': 1.34,
        'arrive_taxi_s': 30.0,
        'reserve_hover_climb_avg_v_m_p_s': 2.54,
        'reserve_hover_climb_s': 6.0,
        'reserve_trans_climb_avg_h_m_p_s': 24.4,
        'reserve_trans_climb_v_m_p_s': 5.1,
        'reserve_trans_climb_s': 15.0,
        'reserve_accel_climb_avg_h_m_p_s': 57.9,
        'reserve_accel_climb_v_m_p_s': 5.1,
        'reserve_accel_climb_s': 12.0,
        'reserve_cruise_h_m_p_s': 67.1,
        'reserve_cruise_s': 112.0,
        'reserve_decel_descend_avg_h_m_p_s': 57.9,
        'reserve_decel_descend_v_m_p_s': 5.1,
        'reserve_decel_descend_s': 12.0,
        'reserve_trans_descend_avg_h_m_p_s': 24.4,
        'reserve_trans_descend_v_m_p_s': 5.1,
        'reserve_trans_descend_s': 15.0,
        'reserve_hover_descend_avg_v_m_p_s': 2.54,
        'reserve_hover_descend_s': 6.0,
    },
    'power': {
        'batt_spec_energy_w_h_p_kg': 243.0,
        'batt_inaccessible_energy_frac': 0.1,
        'batt_eol_capacity': 0.9,
        'batt_int_factor': 0.75,
        'epu_effic': 0.9,
        'hover_power_effic': 0.72,
    },
    'propulsion': {
        'rotor_effic': 0.85,
        'rotor_count': 12,
        'lift_rotor_count': 6,
        'tilt_rotor_count': 6,
        'rotor_diameter_m': 2.0,
        'tip_mach': 0.4,
        'rotor_avg_cl': 0.75,
    },
    'environ': {
        'g_m_p_s2': 9.81,
        'sound_speed_m_p_s': 340.3,
        'air_density_sea_lvl_kg_p_m3': 1.225,
        'air_density_max_alt_kg_p_m3': 1.175,
        'kinematic_viscosity_sea_lvl_m2_p_s': 1.46e-05,
        'kinematic_viscosity_max_alt_m2_p_s': 1.5e-05,
    },
}


VEHICLE_TEMPLATES: dict[str, dict] = {
    "test_all": {
        "description": "Lift+cruise eVTOL reference (upstream test-all.json baseline; "
        "6 lift + 6 tilt rotors + 1 pusher, 3175 kg initial MTOW). The parity baseline.",
        "config": _TEST_ALL,
    },
    "archer_midnight": {
        "description": "Archer Midnight-class eVTOL (AIAA SciTech 2026 case-study "
        "baseline; vectored thrust, 6 tilt + 6 lift rotors, no pusher; ~30 mi / "
        "1500 ft mission). Native evt/Sizing closes to ~2020 kg sized MTOW. "
        "Override mission/aircraft/power/propulsion keys to customize.",
        "config": _ARCHER_MIDNIGHT,
    },
}


def get_template(name: str) -> dict:
    """Return a deep copy of a named template's config dict."""
    if name not in VEHICLE_TEMPLATES:
        valid = ", ".join(sorted(VEHICLE_TEMPLATES))
        raise ValueError(f"Unknown vehicle template {name!r}. Valid: {valid}")
    return copy.deepcopy(VEHICLE_TEMPLATES[name]["config"])


# ---------------------------------------------------------------------------
# Config schema -- known keys per section (derived from the baseline template)
# ---------------------------------------------------------------------------

SECTIONS = ("aircraft", "mission", "power", "propulsion", "environ")

AIRCRAFT_SCHEMA = frozenset(_TEST_ALL["aircraft"])
MISSION_SCHEMA = frozenset(_TEST_ALL["mission"])
POWER_SCHEMA = frozenset(_TEST_ALL["power"])
PROPULSION_SCHEMA = frozenset(_TEST_ALL["propulsion"])
ENVIRON_SCHEMA = frozenset(_TEST_ALL["environ"])

SECTION_SCHEMA: dict[str, frozenset[str]] = {
    "aircraft": AIRCRAFT_SCHEMA,
    "mission": MISSION_SCHEMA,
    "power": POWER_SCHEMA,
    "propulsion": PROPULSION_SCHEMA,
    "environ": ENVIRON_SCHEMA,
}

# Integer-valued propulsion keys (kept int so JSON/divisor math stays exact).
INT_KEYS = frozenset({
    "rotor_count", "lift_rotor_count", "tilt_rotor_count", "pusher_rotor_count",
})

# Keys the upstream constructor treats as optional (have an internal default).
OPTIONAL_KEYS = frozenset({"cruise_wing_lift_fraction"})
