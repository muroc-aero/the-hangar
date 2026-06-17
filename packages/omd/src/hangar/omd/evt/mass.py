"""Mass-buildup component (faithful transcription of aircraft_mass.py +
aircraft_battery.py).

The empty-mass buildup is the NDARC/empirical heart of the evtolpy black box:
~15 component-mass regressions (wing/tail/fuselage/boom NDARC, lift-rotor and
tilt-rotor AFDD00 hub models, the FHE/Magicall EPU model, the Duffy pusher-motor
model, simple landing-gear and fixed-config masses), the empty-mass roll-up with
its margin factor, and the battery mass from total mission energy.

All the NDARC coefficients carry hidden imperial-unit conversions (KG_2_LB,
M_2_FT, M_P_S_2_KTS, N_P_M2_2_LB_P_FT2): the formulas convert SI inputs to
lb/ft/kts, evaluate the empirical fit in imperial, and convert the result back
to kg. Those constants are reproduced verbatim.

Two upstream quantities are computed internally rather than taken as inputs,
because they feed mass formulas that read them off the aircraft:

- ``hover_shaft_power_kw`` (momentum-theory hover power) -- needed by the single
  EPU mass model. Taken from ``disk_area_m2`` + ``hover_power_effic``.
- ``pusher_motor_torque_nm`` -- single pusher-motor torque from cruise shaft
  power and pusher RPM, needed by the Duffy pusher-motor model.

Rotor counts are integers that are never design variables, so they are component
**options**, matching ``PropulsionComp``. The pusher branch (count == 0 -> 0.0)
is selected by the option, never by a float branch inside ``compute``.

numpy math only and complex-step partials, matching the style template.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from hangar.omd.evt.units import u

# Imperial-conversion constants (verbatim from aircraft_mass.py).
KG_2_LB = 2.20462
M_2_FT = 3.28084
M_P_S_2_KTS = 1.9438
N_P_M2_2_LB_P_FT2 = 0.0209

# Inputs: every upstream quantity the mass formulas read. Geometry, environ,
# propulsion-derived scalars, MTOW, mission energy + cruise power, and the fixed
# config masses + battery/power config keys.
_INPUTS = (
    # geometry
    "wing_area_m2",
    "wing_aspect_ratio",
    "wing_taper_ratio",
    "wing_t_p_c",
    "wing_mac_m",
    "horiz_tail_area_m2",
    "vert_tail_area_m2",
    "fuselage_wetted_area_m2",
    "fuselage_l_m",
    "fuselage_fineness_ratio",
    # environ
    "g_m_p_s2",
    "sound_speed_m_p_s",
    "air_density_sea_lvl_kg_p_m3",
    "air_density_max_alt_kg_p_m3",
    # aero / mission speed (dive speed derives from cruise speed)
    "cruise_h_m_p_s",
    # propulsion-derived scalars
    "over_torque_factor",
    "rotor_solidity",
    "rotor_diameter_m",
    "tip_mach",
    "disk_area_m2",
    # power efficiencies feeding hover power
    "hover_power_effic",
    # mission outputs feeding pusher motor torque
    "cruise_avg_shaft_power_kw",
    "pusher_rotor_rpm",
    # sizing state
    "max_takeoff_mass_kg",
    "total_mission_energy_kw_hr",
    # battery config
    "batt_spec_energy_w_h_p_kg",
    "batt_int_factor",
    "batt_inaccessible_energy_frac",
    # empty-mass roll-up factor
    "mass_margin_factor",
)

# Fixed config masses: taken as inputs and echoed as identically-named outputs.
# OpenMDAO forbids an input and output sharing a name, so the input carries an
# ``_in`` suffix; the output keeps the exact evtolpy name.
_FIXED_MASSES = (
    "actuator_mass_kg",
    "furnishings_mass_kg",
    "environmental_control_system_mass_kg",
    "avionics_mass_kg",
    "hivolt_power_dist_mass_kg",
    "lovolt_power_coms_mass_kg",
)

# Public alias: config keys whose value is passed straight through to the output
# mass of the same name (exposed as ``<name>_in`` inputs). The builder uses this
# to route config values to the right input names.
FIXED_MASS_KEYS = frozenset(_FIXED_MASSES)

# Outputs: the 15 component masses (in upstream order), plus single_epu_mass_kg,
# pusher_motor_mass_kg, empty_mass_kg, battery_mass_kg.
_COMPONENT_MASSES = (
    "wing_mass_kg",
    "horiz_tail_mass_kg",
    "vert_tail_mass_kg",
    "fuselage_mass_kg",
    "boom_mass_kg",
    "landing_gear_mass_kg",
    "epu_mass_kg",
    "lift_rotor_hub_mass_kg",
    "tilt_rotor_mass_kg",
    "actuator_mass_kg",
    "furnishings_mass_kg",
    "environmental_control_system_mass_kg",
    "avionics_mass_kg",
    "hivolt_power_dist_mass_kg",
    "lovolt_power_coms_mass_kg",
)

_OUTPUTS = _COMPONENT_MASSES + (
    "single_epu_mass_kg",
    "pusher_motor_mass_kg",
    "empty_mass_kg",
    "battery_mass_kg",
)


class MassBuildupComp(om.ExplicitComponent):
    """NDARC/empirical component masses, empty mass, and battery mass."""

    def initialize(self) -> None:
        self.options.declare("rotor_count", types=int)
        self.options.declare("lift_rotor_count", types=int)
        self.options.declare("tilt_rotor_count", types=int)
        self.options.declare("pusher_rotor_count", types=int, default=0)

    def setup(self) -> None:
        for name in _INPUTS:
            self.add_input(name, val=1.0, units=u(name))
        for name in _FIXED_MASSES:
            self.add_input(name + "_in", val=1.0, units=u(name))
        for name in _OUTPUTS:
            self.add_output(name, val=1.0, units=u(name))
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs) -> None:
        rotor_count = self.options["rotor_count"]
        lift_rotor_count = self.options["lift_rotor_count"]
        tilt_rotor_count = self.options["tilt_rotor_count"]
        pusher_rotor_count = self.options["pusher_rotor_count"]

        mtow = inputs["max_takeoff_mass_kg"]
        g = inputs["g_m_p_s2"]
        a = inputs["sound_speed_m_p_s"]
        rho_sl = inputs["air_density_sea_lvl_kg_p_m3"]
        rho_alt = inputs["air_density_max_alt_kg_p_m3"]
        tip_mach = inputs["tip_mach"]
        rotor_diameter_m = inputs["rotor_diameter_m"]
        over_torque_factor = inputs["over_torque_factor"]
        solidity = inputs["rotor_solidity"]
        disk_area_m2 = inputs["disk_area_m2"]
        cruise_speed_m_p_s = inputs["cruise_h_m_p_s"]

        # --- hover shaft power [kW] (momentum theory; aircraft_performance) ---
        # Needed by the single-EPU mass model below.
        hover_shaft_power_kw = (
            ((g * mtow) ** 1.5 / (2.0 * rho_sl * disk_area_m2) ** 0.5)
            / inputs["hover_power_effic"]
        ) / 1000.0

        # --- single EPU mass [kg] (FHE / Magicall regression) ---
        # Hover torque, scaled to max thrust via the over-torque factor.
        rpm_hover_rpm = (
            (a * tip_mach / (rotor_diameter_m / 2.0)) * 60.0 / (2.0 * np.pi)
        )
        omega_hover_rad_s = 2.0 * np.pi * rpm_hover_rpm / 60.0
        torque_hover_nm = (
            hover_shaft_power_kw * 1000.0 / rotor_count
        ) / omega_hover_rad_s
        torque_max_nm = over_torque_factor * torque_hover_nm

        # Max RPM at minimum air density.
        rpm_max_rpm = (
            rpm_hover_rpm
            * np.sqrt(rho_sl / rho_alt)
            * np.sqrt(over_torque_factor)
        )
        omega_max_rad_s = 2.0 * np.pi * rpm_max_rpm / 60.0
        power_max_kw = (torque_max_nm * omega_max_rad_s) / 1000.0

        single_epu_mass_kg = 1.15 * (
            (power_max_kw / 12.67) + (torque_max_nm / 52.2) + 2.55
        )
        outputs["single_epu_mass_kg"] = single_epu_mass_kg

        # --- wing mass [kg] (NDARC AFDD93, Raymer-based, 0.9 tech factor) ---
        max_takeoff_mass_lb = mtow * KG_2_LB
        wing_area_ft2 = inputs["wing_area_m2"] * (M_2_FT**2)
        wing_aspect_ratio = inputs["wing_aspect_ratio"]
        wing_taper_ratio = inputs["wing_taper_ratio"]
        wing_t_p_c = inputs["wing_t_p_c"]
        wing_mass_lb = (
            5.66411
            * (max_takeoff_mass_lb / 1000.0) ** 0.847
            * (3.8 * 1.5) ** 0.39579
            * (wing_area_ft2) ** 0.21754
            * (wing_aspect_ratio) ** 0.50016
            * ((1.0 + wing_taper_ratio) / wing_t_p_c) ** 0.09359
            * 0.9
        )
        outputs["wing_mass_kg"] = wing_mass_lb / KG_2_LB

        # --- horizontal/vertical tail mass [kg] (NDARC, dive-speed driven) ---
        dive_speed_kts = 1.4 * cruise_speed_m_p_s * M_P_S_2_KTS

        horiz_tail_area_ft2 = inputs["horiz_tail_area_m2"] * (M_2_FT**2)
        horiz_tail_mass_lb = (
            horiz_tail_area_ft2
            * (0.00395 * (horiz_tail_area_ft2**0.2) * dive_speed_kts - 0.4885)
            * 0.9
        )
        outputs["horiz_tail_mass_kg"] = horiz_tail_mass_lb / KG_2_LB

        vert_tail_area_ft2 = inputs["vert_tail_area_m2"] * (M_2_FT**2)
        vert_tail_mass_lb = (
            vert_tail_area_ft2
            * (0.00395 * (vert_tail_area_ft2**0.2) * dive_speed_kts - 0.4885)
            * 0.9
        )
        outputs["vert_tail_mass_kg"] = vert_tail_mass_lb / KG_2_LB

        # --- fuselage mass [kg] (NDARC; wetted area, fineness, dyn pressure) ---
        fuselage_wetted_area_ft2 = inputs["fuselage_wetted_area_m2"] * (M_2_FT**2)
        fuselage_length_ft = inputs["fuselage_l_m"] * 0.5 * M_2_FT
        dyn_pressure_lb_ft2 = (
            0.5 * rho_sl * (cruise_speed_m_p_s**2.0) * N_P_M2_2_LB_P_FT2
        )
        fuselage_mass_lb = (
            0.052
            * (fuselage_wetted_area_ft2**1.086)
            * ((3.8 * 1.5 * max_takeoff_mass_lb) ** 0.177)
            * (fuselage_length_ft**-0.051)
            * (inputs["fuselage_fineness_ratio"] ** -0.072)
            * (dyn_pressure_lb_ft2**0.241)
            * 0.9
        )
        outputs["fuselage_mass_kg"] = fuselage_mass_lb / KG_2_LB

        # --- boom mass [kg] (NDARC engine-support + cowling). The upstream
        # EPU-mass sanity-check raise is intentionally omitted; the solver owns
        # feasibility. ---
        single_epu_mass_lb = single_epu_mass_kg * KG_2_LB
        wing_mac_m = inputs["wing_mac_m"]
        boom_mass_kg = (
            0.0412
            * (single_epu_mass_lb**1.1433)
            * (rotor_count**1.3762)
            / KG_2_LB
            + 6 * 0.2315 * ((1.2 * rotor_diameter_m + wing_mac_m) ** 1.3476)
        ) * 2
        outputs["boom_mass_kg"] = boom_mass_kg

        # --- landing gear mass [kg] (3.25% MTOW x crash x retract factors) ---
        outputs["landing_gear_mass_kg"] = 0.0325 * mtow * 1.14 * 1.08

        # --- total EPU mass [kg] (single EPU x rotor count) ---
        outputs["epu_mass_kg"] = single_epu_mass_kg * rotor_count

        # --- lift-rotor + hub mass [kg] (NDARC 19.2 AFDD00, 2-bladed) ---
        rotor_radius_ft = (rotor_diameter_m / 2.0) * M_2_FT
        tip_speed_ft_s = (
            a
            * tip_mach
            * np.sqrt(rho_sl / rho_alt)
            * np.sqrt(over_torque_factor)
            * M_2_FT
        )

        term_common_lift = (
            (np.pi / 2.0 / 2.0) * rotor_diameter_m * solidity * M_2_FT
        )
        lift_rotor_hub_mass_lb = (
            0.0024419
            * (lift_rotor_count)
            * (2.0**0.53479)
            * (rotor_radius_ft**1.74231)
            * (term_common_lift**0.77291)
            * (tip_speed_ft_s**0.87562)
            * (1.1**2.51048)
        ) + (
            0.00037547
            * (lift_rotor_count)
            * (2.0**0.71443)
            * (rotor_radius_ft**1.99321)
            * (term_common_lift**0.79577)
            * (tip_speed_ft_s**0.96323)
            * (1.1**0.46203)
            * (1.1**2.58473)
        )
        outputs["lift_rotor_hub_mass_kg"] = lift_rotor_hub_mass_lb / KG_2_LB

        # --- tilt-rotor mass [kg] (NDARC 19.2 AFDD00, 3-bladed) ---
        term_common_tilt = (
            (np.pi / 2.0 / 3.0) * rotor_diameter_m * solidity * M_2_FT
        )
        tilt_rotor_mass_lb = (
            0.0024419
            * 1.1794
            * (tilt_rotor_count)
            * (3.0**0.53479)
            * (rotor_radius_ft**1.74231)
            * (term_common_tilt**0.77291)
            * (tip_speed_ft_s**0.87562)
            * (1.1**2.51048)
        ) + (
            0.00037547
            * (1.1794**1.02958)
            * (tilt_rotor_count)
            * (3.0**0.71443)
            * (rotor_radius_ft**1.99321)
            * (term_common_tilt**0.79577)
            * (tip_speed_ft_s**0.96323)
            * (1.1**0.46203)
            * (1.1**2.58473)
        )
        outputs["tilt_rotor_mass_kg"] = tilt_rotor_mass_lb / KG_2_LB

        # --- pusher motor mass [kg] (Duffy 2018; 0 if no pusher rotors) ---
        if pusher_rotor_count == 0:
            outputs["pusher_motor_mass_kg"] = 0.0
        else:
            # Single pusher-motor torque from cruise shaft power and RPM.
            omega_rad_p_s = inputs["pusher_rotor_rpm"] * np.pi / 30.0
            pusher_motor_torque_nm = (
                inputs["cruise_avg_shaft_power_kw"] * 1000.0 / pusher_rotor_count
            ) / omega_rad_p_s
            single_motor_mass_lb = (58.0 / 990.0) * (
                (1.3558 * pusher_motor_torque_nm) - 10.0
            ) + 2.0
            outputs["pusher_motor_mass_kg"] = (
                single_motor_mass_lb * pusher_rotor_count
            ) / KG_2_LB

        # --- fixed config masses echoed straight through ---
        for name in _FIXED_MASSES:
            outputs[name] = inputs[name + "_in"]

        # --- empty mass [kg] (structural + subsystem, with margin factor) ---
        structural_mass = (
            outputs["wing_mass_kg"]
            + outputs["horiz_tail_mass_kg"]
            + outputs["vert_tail_mass_kg"]
            + outputs["fuselage_mass_kg"]
            + outputs["boom_mass_kg"]
            + outputs["landing_gear_mass_kg"]
            + outputs["lift_rotor_hub_mass_kg"]
            + outputs["tilt_rotor_mass_kg"]
            + outputs["pusher_motor_mass_kg"]
        )
        subsys_mass = (
            outputs["epu_mass_kg"]
            + outputs["actuator_mass_kg"]
            + outputs["furnishings_mass_kg"]
            + outputs["environmental_control_system_mass_kg"]
            + outputs["avionics_mass_kg"]
            + outputs["hivolt_power_dist_mass_kg"]
            + outputs["lovolt_power_coms_mass_kg"]
        )
        subtotal = structural_mass + subsys_mass
        outputs["empty_mass_kg"] = subtotal * (1.0 + inputs["mass_margin_factor"])

        # --- battery mass [kg] (total mission energy / usable specific energy) ---
        batt_accessible_energy_frac = 1.0 - inputs["batt_inaccessible_energy_frac"]
        outputs["battery_mass_kg"] = (
            inputs["total_mission_energy_kw_hr"] * 1000.0
        ) / (
            inputs["batt_spec_energy_w_h_p_kg"]
            * batt_accessible_energy_frac
            * inputs["batt_int_factor"]
        )
