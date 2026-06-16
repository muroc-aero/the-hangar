"""Propulsion component (faithful transcription of propulsion.py +
aircraft_propulsion.py).

Disk area/loading, over-torque factor, rotor solidity from hover thrust
coefficient, and pusher-rotor RPM. Rotor counts are integers that are never
design variables, so they are component **options** (build-time constants),
keeping the differentiated inputs clean for complex step.

``pusher_motor_torque_nm`` depends on ``cruise_avg_shaft_power_kw`` (a mission
output), so it is computed downstream in the mass domain, not here.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from hangar.omd.evt.units import u

_INPUTS = (
    "max_takeoff_mass_kg",
    "rotor_diameter_m",
    "tip_mach",
    "rotor_avg_cl",
    "pusher_rotor_diameter_m",
    "pusher_rotor_tip_mach",
    "g_m_p_s2",
    "sound_speed_m_p_s",
    "air_density_sea_lvl_kg_p_m3",
)

_OUTPUTS = (
    "disk_area_m2",
    "disk_loading_kg_p_m2",
    "over_torque_factor",
    "rotor_solidity",
    "pusher_rotor_rpm",
)


class PropulsionComp(om.ExplicitComponent):
    """Rotor disk geometry, loading, solidity, over-torque, pusher RPM."""

    def initialize(self) -> None:
        self.options.declare("rotor_count", types=int)
        self.options.declare("pusher_rotor_count", types=int, default=0)

    def setup(self) -> None:
        for name in _INPUTS:
            self.add_input(name, val=1.0, units=u(name))
        for name in _OUTPUTS:
            units = "rpm" if name == "pusher_rotor_rpm" else u(name)
            self.add_output(name, val=1.0, units=units)
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs) -> None:
        rotor_count = self.options["rotor_count"]
        pusher_count = self.options["pusher_rotor_count"]

        mtow = inputs["max_takeoff_mass_kg"]
        g = inputs["g_m_p_s2"]
        rho_sl = inputs["air_density_sea_lvl_kg_p_m3"]
        a = inputs["sound_speed_m_p_s"]
        diam = inputs["rotor_diameter_m"]
        tip_mach = inputs["tip_mach"]
        avg_cl = inputs["rotor_avg_cl"]

        radius = diam / 2.0
        disk_area = rotor_count * np.pi * radius**2.0
        outputs["disk_area_m2"] = disk_area
        outputs["disk_loading_kg_p_m2"] = mtow / disk_area

        # Over-torque: hover thrust redistributed over rotor_count-2, +30% margin.
        outputs["over_torque_factor"] = (
            rotor_count / (rotor_count - 2)
        ) * 1.3

        # Rotor solidity from hover thrust coefficient.
        rpm_hover = (a * tip_mach / radius) * 60.0 / (2.0 * np.pi)
        omega_hover = rpm_hover * np.pi / 30.0
        ct_hover = (mtow * g / rotor_count) / (
            rho_sl * np.pi * radius**4.0 * omega_hover**2.0
        )
        outputs["rotor_solidity"] = ct_hover * 6.0 / avg_cl

        # Pusher RPM (0 if no pusher rotors).
        if pusher_count == 0:
            outputs["pusher_rotor_rpm"] = 0.0
        else:
            pusher_radius = inputs["pusher_rotor_diameter_m"] / 2.0
            outputs["pusher_rotor_rpm"] = (
                a * inputs["pusher_rotor_tip_mach"] / pusher_radius
            ) * 60.0 / (2.0 * np.pi)
