"""Aero component (faithful transcription of aircraft_aero.py).

Cruise drag buildup at the as-configured MTOW: fuselage skin friction
(Prandtl-Schlichting) plus a Hoerner form factor, the lifting-line induced
drag, empennage/landing-gear/stopped-rotor parasite terms, and the resulting
L/D. When the wing carries only part of the cruise lift
(``cruise_wing_lift_fraction < 1``) the rotors make up the balance and their
induced power is converted to an equivalent drag via momentum theory.

Geometry (``wing_area_m2``, ``wing_aspect_ratio``, ``wing_mac_m`` is not read
here), propulsion (``disk_area_m2``), and environ/mission quantities are taken
as inputs -- this module does not recompute them. numpy math only and
complex-step partials, matching the style of geometry.py / propulsion.py.

The upstream ``_calc_cruise_l_p_d`` branches on ``cruise_wing_lift_fraction``
to short-circuit the rotor term when the wing carries all the lift. Branching
on a differentiated input breaks complex step, so the rotor-momentum term is
always evaluated here; it vanishes identically as ``f_wing -> 1`` (the rotor
lift fraction goes to zero), so the closed form agrees with both upstream
branches.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from hangar.omd.evt.units import u

# Inputs this component reads: aero config keys, plus upstream-domain quantities
# (geometry/propulsion outputs and environ/mission values), with evtolpy names.
_INPUTS = (
    # aircraft config keys
    "cruise_wing_lift_fraction",
    "stall_speed_m_p_s",
    "vehicle_cl_max",
    "span_effic_factor",
    "wing_airfoil_cd_at_cruise_cl",
    "empennage_airfoil_cd0",
    "landing_gear_drag_area_m2",
    "ratio_disk_to_stopped_rotor_area",
    "trim_drag_factor",
    "excres_protub_factor",
    "fuselage_l_m",
    "fuselage_w_m",
    "fuselage_h_m",
    # environ
    "kinematic_viscosity_max_alt_m2_p_s",
    "air_density_max_alt_kg_p_m3",
    # mission
    "cruise_h_m_p_s",
    # geometry-domain inputs (computed upstream by GeometryComp)
    "wing_area_m2",
    "wing_aspect_ratio",
    "fuselage_fineness_ratio",
    "horiz_tail_area_m2",
    "vert_tail_area_m2",
    # propulsion-domain input (computed upstream by PropulsionComp)
    "disk_area_m2",
)

_OUTPUTS = (
    "fuselage_cruise_reynolds",
    "fuselage_cd0_p_cf",
    "fuselage_cf",
    "fuselage_cd0",
    "cruise_cl",
    "induced_drag_cdi",
    "horiz_tail_cd0",
    "vert_tail_cd0",
    "landing_gear_cd0",
    "stopped_rotor_cd0",
    "cruise_cd",
    "cruise_l_p_d",
    "total_drag_coef",
)


class AeroComp(om.ExplicitComponent):
    """Cruise drag buildup and L/D for the lift+cruise eVTOL."""

    def setup(self) -> None:
        for name in _INPUTS:
            self.add_input(name, val=1.0, units=u(name))
        for name in _OUTPUTS:
            self.add_output(name, val=1.0, units=u(name))
        self.declare_partials("*", "*", method="cs")

    def compute(self, inputs, outputs) -> None:
        f_wing = inputs["cruise_wing_lift_fraction"]
        vstall = inputs["stall_speed_m_p_s"]
        cl_max = inputs["vehicle_cl_max"]
        span_eff = inputs["span_effic_factor"]
        wing_airfoil_cd = inputs["wing_airfoil_cd_at_cruise_cl"]
        emp_cd0 = inputs["empennage_airfoil_cd0"]
        lg_drag_area = inputs["landing_gear_drag_area_m2"]
        ratio_disk_stopped = inputs["ratio_disk_to_stopped_rotor_area"]
        trim_drag = inputs["trim_drag_factor"]
        excres_protub = inputs["excres_protub_factor"]
        fl = inputs["fuselage_l_m"]
        fw = inputs["fuselage_w_m"]
        fh = inputs["fuselage_h_m"]
        nu = inputs["kinematic_viscosity_max_alt_m2_p_s"]
        rho = inputs["air_density_max_alt_kg_p_m3"]
        V = inputs["cruise_h_m_p_s"]
        wing_area = inputs["wing_area_m2"]
        aspect_ratio = inputs["wing_aspect_ratio"]
        fineness = inputs["fuselage_fineness_ratio"]
        horiz_tail_area = inputs["horiz_tail_area_m2"]
        vert_tail_area = inputs["vert_tail_area_m2"]
        disk_area = inputs["disk_area_m2"]

        # Cruise CL: stall-speed equation with cruise speed, scaled by the wing
        # lift fraction (rotors carry the rest).
        cruise_cl = f_wing * (vstall**2.0) * cl_max / (V**2.0)
        outputs["cruise_cl"] = cruise_cl

        # Hoerner Eq 6.31 fuselage form factor.
        fuselage_cd0_p_cf = (
            3.0 * fineness
            + 4.5 / fineness**0.5
            + 21.0 / fineness**2.0
        )
        outputs["fuselage_cd0_p_cf"] = fuselage_cd0_p_cf

        # Fuselage Reynolds, then Prandtl-Schlichting skin friction.
        reynolds = V * fl / nu
        outputs["fuselage_cruise_reynolds"] = reynolds
        fuselage_cf = 0.455 / np.log10(reynolds) ** 2.58
        outputs["fuselage_cf"] = fuselage_cf

        # Fuselage CD0: form factor * cf * reference area / wing area.
        fuselage_reference_area = np.pi * ((fw + fh) / 4.0) ** 2.0
        fuselage_cd0 = (
            fuselage_cd0_p_cf * fuselage_cf * fuselage_reference_area / wing_area
        )
        outputs["fuselage_cd0"] = fuselage_cd0

        # Induced drag.
        induced_drag_cdi = cruise_cl**2.0 / (np.pi * aspect_ratio * span_eff)
        outputs["induced_drag_cdi"] = induced_drag_cdi

        # Empennage, landing-gear, stopped-rotor parasite terms.
        horiz_tail_cd0 = (horiz_tail_area / wing_area) * emp_cd0
        vert_tail_cd0 = (vert_tail_area / wing_area) * emp_cd0
        landing_gear_cd0 = lg_drag_area / wing_area
        stopped_rotor_cd0 = (disk_area / ratio_disk_stopped) / wing_area
        outputs["horiz_tail_cd0"] = horiz_tail_cd0
        outputs["vert_tail_cd0"] = vert_tail_cd0
        outputs["landing_gear_cd0"] = landing_gear_cd0
        outputs["stopped_rotor_cd0"] = stopped_rotor_cd0

        # Per-component drag buildup, scaled by trim and excrescence factors.
        cruise_cd = (
            fuselage_cd0
            + wing_airfoil_cd
            + induced_drag_cdi
            + horiz_tail_cd0
            + vert_tail_cd0
            + landing_gear_cd0
            + stopped_rotor_cd0
        ) * trim_drag * excres_protub
        outputs["cruise_cd"] = cruise_cd

        # L/D with the rotor-momentum equivalent drag. As f_wing -> 1 the rotor
        # lift fraction goes to zero and this reduces to cruise_cl / cruise_cd.
        cl_total = cruise_cl / f_wing
        cl_rotor = (1.0 - f_wing) * cl_total
        q = 0.5 * rho * V**2.0
        rotor_lift_n = q * wing_area * cl_rotor
        v_induced = np.sqrt(rotor_lift_n / (2.0 * rho * disk_area))
        cd_rotor_equiv = cl_rotor * v_induced / V
        outputs["cruise_l_p_d"] = cl_total / (cruise_cd + cd_rotor_equiv)

        # Total parasite (CD0) drag coefficient: fuselage + empennage + gear.
        outputs["total_drag_coef"] = (
            fuselage_cd0 + horiz_tail_cd0 + vert_tail_cd0 + landing_gear_cd0
        )
