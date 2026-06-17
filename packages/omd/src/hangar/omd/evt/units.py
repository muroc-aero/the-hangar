"""Single source of OpenMDAO units for every native-evt variable.

evtolpy bakes units into key names; here we attach the real OpenMDAO unit
strings so the model auto-converts on connection and can couple to other
hangar tools. Every component pulls its input/output units from ``UNITS`` via
``u()`` so units are declared once, consistently. A key absent from ``UNITS``
defaults to dimensionless (``None``) and should be added here, not inlined.

Convention: keys are the evtolpy attribute/property/config names. ``None`` means
dimensionless (coefficients, fractions, ratios, Reynolds, Mach, counts).
"""

from __future__ import annotations

UNITS: dict[str, str | None] = {
    # --- environ ---
    "g_m_p_s2": "m/s**2",
    "sound_speed_m_p_s": "m/s",
    "air_density_sea_lvl_kg_p_m3": "kg/m**3",
    "air_density_max_alt_kg_p_m3": "kg/m**3",
    "kinematic_viscosity_sea_lvl_m2_p_s": "m**2/s",
    "kinematic_viscosity_max_alt_m2_p_s": "m**2/s",
    # --- masses ---
    "max_takeoff_mass_kg": "kg",
    "payload_kg": "kg",
    "empty_mass_kg": "kg",
    "battery_mass_kg": "kg",
    "wing_mass_kg": "kg",
    "horiz_tail_mass_kg": "kg",
    "vert_tail_mass_kg": "kg",
    "fuselage_mass_kg": "kg",
    "boom_mass_kg": "kg",
    "landing_gear_mass_kg": "kg",
    "epu_mass_kg": "kg",
    "single_epu_mass_kg": "kg",
    "lift_rotor_hub_mass_kg": "kg",
    "tilt_rotor_mass_kg": "kg",
    "pusher_motor_mass_kg": "kg",
    "actuator_mass_kg": "kg",
    "furnishings_mass_kg": "kg",
    "environmental_control_system_mass_kg": "kg",
    "avionics_mass_kg": "kg",
    "hivolt_power_dist_mass_kg": "kg",
    "lovolt_power_coms_mass_kg": "kg",
    # --- geometry: lengths ---
    "wingspan_m": "m",
    "d_value_m": "m",
    "fuselage_l_m": "m",
    "fuselage_w_m": "m",
    "fuselage_h_m": "m",
    "wing_root_chord_m": "m",
    "wing_mac_m": "m",
    "rotor_diameter_m": "m",
    "pusher_rotor_diameter_m": "m",
    # --- geometry: areas ---
    "wing_area_m2": "m**2",
    "horiz_tail_area_m2": "m**2",
    "vert_tail_area_m2": "m**2",
    "fuselage_wetted_area_m2": "m**2",
    "disk_area_m2": "m**2",
    "landing_gear_drag_area_m2": "m**2",
    # --- speeds ---
    "stall_speed_m_p_s": "m/s",
    "cruise_h_m_p_s": "m/s",
    # --- power / energy ---
    "total_mission_energy_kw_hr": "kW*h",
    "total_reserve_mission_energy_kw_hr": "kW*h",
    "peak_power_kw": "kW",
    "disk_loading_kg_p_m2": "kg/m**2",
    "batt_spec_energy_w_h_p_kg": "W*h/kg",
    "cruise_avg_shaft_power_kw": "kW",
    "pusher_rotor_rpm": "rpm",
}


def u(name: str) -> str | None:
    """OpenMDAO units for a native-evt variable name (None = dimensionless)."""
    return UNITS.get(name)
