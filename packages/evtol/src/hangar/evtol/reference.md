# evtol Parameter Reference

The evtol server wraps [evtolpy](https://github.com/starbelt/evtolpy). A vehicle
is described by a five-section config (aircraft, mission, power, propulsion,
environ). Load a complete baseline with `load_vehicle_template`, then override
individual keys with the section setters. Unknown keys are rejected (evtolpy
silently ignores them otherwise).

## Units convention

Units are encoded in key/attribute names: `_kg` (mass), `_m` (length),
`_m2` (area), `_s` (seconds), `_m_p_s` (m/s), `_kw` (kilowatts),
`_kw_hr` (kilowatt-hours). No implicit conversions.

## aircraft section (define_vehicle)

Geometry/mass/aero of the airframe. Keys:
`max_takeoff_mass_kg`, `payload_kg`, `vehicle_cl_max`, `wing_taper_ratio`,
`wingspan_m`, `d_value_m`, `stall_speed_m_p_s`, `fuselage_l_m`, `fuselage_w_m`,
`fuselage_h_m`, `wing_airfoil_cd_at_cruise_cl`, `cruise_wing_lift_fraction`,
`empennage_airfoil_cd0`, `span_effic_factor`, `trim_drag_factor`,
`landing_gear_drag_area_m2`, `excres_protub_factor`, `horiz_tail_vol_coeff`,
`vert_tail_vol_coeff`, `ratio_disk_to_stopped_rotor_area`, `wing_t_p_c`,
`actuator_mass_kg`, `furnishings_mass_kg`,
`environmental_control_system_mass_kg`, `avionics_mass_kg`,
`hivolt_power_dist_mass_kg`, `lovolt_power_coms_mass_kg`, `mass_margin_factor`.

`max_takeoff_mass_kg` is the *initial* MTOW guess; `run_sizing` converges it.

## propulsion section (set_propulsion)

`rotor_effic`, `rotor_count`, `lift_rotor_count`, `tilt_rotor_count`,
`pusher_rotor_count` (integers), `rotor_diameter_m`, `pusher_rotor_diameter_m`,
`tip_mach`, `pusher_rotor_tip_mach`, `rotor_avg_cl`.

## power section (set_power)

`batt_spec_energy_w_h_p_kg` (Wh/kg, 50-1000), `batt_inaccessible_energy_frac`,
`batt_eol_capacity`, `batt_int_factor`, `epu_effic`, `hover_power_effic`.
Fraction/efficiency keys must lie in (0, 1].

## environ section (set_environment)

`g_m_p_s2`, `sound_speed_m_p_s`, `air_density_sea_lvl_kg_p_m3`,
`air_density_max_alt_kg_p_m3`, `kinematic_viscosity_sea_lvl_m2_p_s`,
`kinematic_viscosity_max_alt_m2_p_s`.

## mission section (configure_mission)

Per-segment speeds and durations for 18 segments (11 main + 7 reserve). Each
segment has a horizontal speed (`*_h_m_p_s` / `*_avg_h_m_p_s`), some a vertical
speed (`*_v_m_p_s` / `*_avg_v_m_p_s`), and a duration (`*_s`). Segment stems, in
order: `depart_taxi`, `hover_climb`, `trans_climb`, `depart_proc`,
`accel_climb`, `cruise`, `decel_descend`, `arrive_proc`, `trans_descend`,
`hover_descend`, `arrive_taxi`, then `reserve_*` variants of the climb/cruise/
descend segments.

## Outputs

`run_mission_analysis` returns:
- `energy_kw_hr` -- per-segment energy, keyed by segment stem
- `avg_electric_power_kw` -- per-segment average electric power
- `mass_breakdown_kg` -- 15-component empty-mass breakdown
- `totals` -- total mission/reserve energy, empty/battery/payload mass
- `geometry`, `aero`, `propulsion` -- derived summaries

`run_sizing` returns `sized_mtow_kg`, `converged`, `iterations`, `history`
(per-iteration MTOW guess/delta/masses), and the mass breakdown at sized MTOW.
