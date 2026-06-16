"""Geometry component (faithful transcription of aircraft_geometry.py).

Closed-form wing/tail/fuselage geometry. Feed-forward within the domain:
``wing_area -> wing_root_chord -> wing_mac`` and ``wing_area + wingspan -> AR``,
then the tail areas. ``fuselage_wetted_area`` follows Hoerner Eq 6.30; upstream
guards it on ``fuselage_cf`` being populated but does not use the value, so it is
computed here without any aero dependency.

This module is the style template for the other domain components: numpy math
only, units pulled from ``units.UNITS``, and complex-step partials.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from hangar.omd.evt.units import u

# Inputs this component reads (config keys + environ), with their evtolpy names.
_INPUTS = (
    "max_takeoff_mass_kg",
    "stall_speed_m_p_s",
    "vehicle_cl_max",
    "wingspan_m",
    "wing_taper_ratio",
    "fuselage_l_m",
    "fuselage_w_m",
    "fuselage_h_m",
    "horiz_tail_vol_coeff",
    "vert_tail_vol_coeff",
    "g_m_p_s2",
    "air_density_sea_lvl_kg_p_m3",
)

_OUTPUTS = (
    "wing_area_m2",
    "wing_root_chord_m",
    "wing_mac_m",
    "wing_aspect_ratio",
    "horiz_tail_area_m2",
    "vert_tail_area_m2",
    "fuselage_fineness_ratio",
    "fuselage_wetted_area_m2",
)


class GeometryComp(om.ExplicitComponent):
    """Wing/tail/fuselage geometry from MTOW, stall speed, and fuselage dims."""

    def setup(self) -> None:
        for name in _INPUTS:
            self.add_input(name, val=1.0, units=u(name))
        for name in _OUTPUTS:
            self.add_output(name, val=1.0, units=u(name))
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs) -> None:
        mtow = inputs["max_takeoff_mass_kg"]
        g = inputs["g_m_p_s2"]
        rho_sl = inputs["air_density_sea_lvl_kg_p_m3"]
        vstall = inputs["stall_speed_m_p_s"]
        cl_max = inputs["vehicle_cl_max"]
        span = inputs["wingspan_m"]
        taper = inputs["wing_taper_ratio"]
        fl = inputs["fuselage_l_m"]
        fw = inputs["fuselage_w_m"]
        fh = inputs["fuselage_h_m"]

        # Stall-speed equation solved for wing area.
        wing_area = (2.0 * mtow * g) / (rho_sl * (vstall**2.0) * cl_max)
        outputs["wing_area_m2"] = wing_area

        # Root chord, then mean aerodynamic chord.
        root_chord = 2.0 * wing_area / (span * (1.0 + taper))
        outputs["wing_root_chord_m"] = root_chord
        outputs["wing_mac_m"] = (
            (2.0 / 3.0) * root_chord * (1.0 + taper**2.0 / (1.0 + taper))
        )

        outputs["wing_aspect_ratio"] = span**2.0 / wing_area

        mac = outputs["wing_mac_m"]
        outputs["horiz_tail_area_m2"] = (
            inputs["horiz_tail_vol_coeff"] * wing_area * mac
        ) / (0.5 * fl)
        outputs["vert_tail_area_m2"] = (
            inputs["vert_tail_vol_coeff"] * span * wing_area
        ) / (0.5 * fl)

        # Hoerner: fineness ratio and wetted area.
        fineness = 2.0 * fl / (fw + fh)
        outputs["fuselage_fineness_ratio"] = fineness
        ref_area = np.pi * ((fw + fh) / 4.0) ** 2.0
        outputs["fuselage_wetted_area_m2"] = 3.0 * fineness * ref_area
