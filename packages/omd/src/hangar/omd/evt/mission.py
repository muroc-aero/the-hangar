"""Mission-energy component (faithful transcription of the 18-segment model in
evtolpy ``aircraft_performance.py``).

Each of the 18 mission segments computes an average shaft power, scales it to
average electric power by ``epu_effic``, and integrates over the segment
duration to energy in kW*h. The segment kernels are transcribed one-for-one
from the upstream ``_calc_<seg>_avg_shaft_power_kw`` functions; the winged-aero
block (lift, induced drag, parasite drag) is shared because it is identical
across the aerodynamic segments, but the kinematics and force balance of each
segment family are transcribed explicitly so the numbers match the black box to
floating point.

numpy math only (``np.sqrt``/``np.arctan2``/``np.cos``/``np.pi``/``np.abs``) and
no float-branching, so the whole component is complex-step safe. The genuine
runtime branches -- ``max(0, ...)`` thrust floors, the gravity-deficit vertical
assist, and the spoiler-drag recompute when descent shaft power goes negative --
are reproduced with ``np.where`` / ``np.maximum`` so they stay differentiable
under complex step and give the same branch selection as the source.

All upstream-domain quantities (geometry, aero coefficients, disk area,
efficiencies, densities, MTOW) are taken as inputs -- nothing is recomputed.
Rotor counts are integer options, not differentiated inputs (parity with
``PropulsionComp``), even though the energy model does not read them; they are
declared so the component shares the propulsion option surface.

The baseline (``test_all``) is a winged lift+cruise vehicle, so the winged-aero
path is active. The multicopter/no-wing branch in the source is not transcribed:
that path is selected by build-time geometry (zero wingspan/area), which is a
different vehicle class, not a runtime float branch of this component. The
component assumes the winged path; see ``_WINGED`` below.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from hangar.omd.evt.labels import SEGMENT_KEYS
from hangar.omd.evt.units import u

# Upstream constants (W_P_KW, S_P_HR) from aircraft_performance.py.
_W_P_KW = 1000.0
_S_P_HR = 3600.0

# This component transcribes the winged lift+cruise path. The no-wing branch is
# a distinct vehicle class selected by zero wing geometry at build time, not a
# runtime float branch, so it is intentionally not reproduced here.
_WINGED = True


def _atan2(y, x):
    """Complex-step-safe ``arctan2`` for the segment kernels.

    ``np.arctan2`` does not accept complex inputs, so under complex step it
    fails. Every segment calls this with a positive horizontal speed ``x`` (the
    aircraft is always moving forward in the aero segments), where
    ``arctan2(y, x) == arctan(y / x)`` and ``np.arctan`` *is* complex-safe.

    For the real-valued forward pass we still call ``np.arctan2`` so the result
    is bit-identical to upstream's ``math.atan2``; only the complex (derivative)
    pass uses the ``arctan(y/x)`` identity. Switching on dtype is a build/runtime
    type check, not a float branch on a working value, so it stays cs-safe.
    """
    y = np.asarray(y)
    x = np.asarray(x)
    if np.iscomplexobj(y) or np.iscomplexobj(x):
        return np.arctan(y / x)
    return np.arctan2(y, x)

# Upstream-domain inputs (geometry, aero, propulsion, environ, mass, efficiencies)
# the segments read. Taken as inputs; never recomputed.
_DOMAIN_INPUTS = (
    "max_takeoff_mass_kg",
    "wing_area_m2",
    "wing_aspect_ratio",
    "wingspan_m",
    "span_effic_factor",
    "total_drag_coef",
    "wing_airfoil_cd_at_cruise_cl",
    "stopped_rotor_cd0",
    "cruise_wing_lift_fraction",
    "trim_drag_factor",
    "excres_protub_factor",
    "disk_area_m2",
    "rotor_effic",
    "epu_effic",
    "g_m_p_s2",
    "air_density_sea_lvl_kg_p_m3",
    "air_density_max_alt_kg_p_m3",
)

# Every mission-section config key the segments read.
_MISSION_INPUTS = (
    "depart_taxi_avg_h_m_p_s",
    "depart_taxi_s",
    "hover_climb_avg_v_m_p_s",
    "hover_climb_s",
    "trans_climb_avg_h_m_p_s",
    "trans_climb_v_m_p_s",
    "trans_climb_s",
    "depart_proc_h_m_p_s",
    "depart_proc_s",
    "accel_climb_avg_h_m_p_s",
    "accel_climb_v_m_p_s",
    "accel_climb_s",
    "cruise_h_m_p_s",
    "cruise_s",
    "decel_descend_avg_h_m_p_s",
    "decel_descend_v_m_p_s",
    "decel_descend_s",
    "arrive_proc_h_m_p_s",
    "arrive_proc_s",
    "trans_descend_avg_h_m_p_s",
    "trans_descend_v_m_p_s",
    "trans_descend_s",
    "hover_descend_avg_v_m_p_s",
    "hover_descend_s",
    "arrive_taxi_avg_h_m_p_s",
    "arrive_taxi_s",
    "reserve_hover_climb_avg_v_m_p_s",
    "reserve_hover_climb_s",
    "reserve_trans_climb_avg_h_m_p_s",
    "reserve_trans_climb_v_m_p_s",
    "reserve_trans_climb_s",
    "reserve_accel_climb_avg_h_m_p_s",
    "reserve_accel_climb_v_m_p_s",
    "reserve_accel_climb_s",
    "reserve_cruise_h_m_p_s",
    "reserve_cruise_s",
    "reserve_decel_descend_avg_h_m_p_s",
    "reserve_decel_descend_v_m_p_s",
    "reserve_decel_descend_s",
    "reserve_trans_descend_avg_h_m_p_s",
    "reserve_trans_descend_v_m_p_s",
    "reserve_trans_descend_s",
    "reserve_hover_descend_avg_v_m_p_s",
    "reserve_hover_descend_s",
)

_INPUTS = _DOMAIN_INPUTS + _MISSION_INPUTS

# Durations matched to SEGMENT_KEYS order, for the power->energy integration.
_DURATION_KEY = {
    "depart_taxi": "depart_taxi_s",
    "hover_climb": "hover_climb_s",
    "trans_climb": "trans_climb_s",
    "depart_proc": "depart_proc_s",
    "accel_climb": "accel_climb_s",
    "cruise": "cruise_s",
    "decel_descend": "decel_descend_s",
    "arrive_proc": "arrive_proc_s",
    "trans_descend": "trans_descend_s",
    "hover_descend": "hover_descend_s",
    "arrive_taxi": "arrive_taxi_s",
    "reserve_hover_climb": "reserve_hover_climb_s",
    "reserve_trans_climb": "reserve_trans_climb_s",
    "reserve_accel_climb": "reserve_accel_climb_s",
    "reserve_cruise": "reserve_cruise_s",
    "reserve_decel_descend": "reserve_decel_descend_s",
    "reserve_trans_descend": "reserve_trans_descend_s",
    "reserve_hover_descend": "reserve_hover_descend_s",
}

# Indices of the seven reserve segments within SEGMENT_KEYS (for reserve total).
_RESERVE_KEYS = (
    "reserve_hover_climb",
    "reserve_trans_climb",
    "reserve_accel_climb",
    "reserve_cruise",
    "reserve_decel_descend",
    "reserve_trans_descend",
    "reserve_hover_descend",
)


class MissionEnergyComp(om.ExplicitComponent):
    """18-segment mission energy/power model (faithful evtolpy transcription)."""

    def initialize(self) -> None:
        # Rotor counts are integer build-time constants (parity with
        # PropulsionComp). The energy model does not read them, but they are
        # declared so the component shares the propulsion option surface.
        self.options.declare("rotor_count", types=int, default=0)
        self.options.declare("lift_rotor_count", types=int, default=0)
        self.options.declare("tilt_rotor_count", types=int, default=0)
        self.options.declare("pusher_rotor_count", types=int, default=0)

    def setup(self) -> None:
        for name in _INPUTS:
            self.add_input(name, val=1.0, units=u(name))

        n = len(SEGMENT_KEYS)
        self.add_output("segment_energy_kw_hr", val=np.zeros(n), units="kW*h")
        self.add_output("segment_power_kw", val=np.zeros(n), units="kW")
        self.add_output("total_mission_energy_kw_hr", val=1.0, units="kW*h")
        self.add_output(
            "total_reserve_mission_energy_kw_hr", val=1.0, units="kW*h"
        )
        self.add_output("peak_power_kw", val=1.0, units="kW")
        self.add_output("cruise_avg_shaft_power_kw", val=1.0, units="kW")

        self.declare_partials("*", "*", method="cs")

    # ----- shared winged-aero block -------------------------------------
    def _winged_aero(self, q, lift_n, wing_area, ar, eff, cd0,
                     trim, excres):
        """Induced + parasite drag for the winged path (matches the source's
        winged branch). ``lift_n`` is the aerodynamic (wing) lift in N."""
        di_n = (lift_n**2.0) / (q * wing_area * np.pi * ar * eff)
        dp_n = q * wing_area * cd0
        total_drag_n = (di_n + dp_n) * trim * excres
        return di_n, dp_n, total_drag_n

    def compute(self, inputs, outputs) -> None:
        # --- domain scalars ---
        m = inputs["max_takeoff_mass_kg"]
        g = inputs["g_m_p_s2"]
        rho_sl = inputs["air_density_sea_lvl_kg_p_m3"]
        rho_alt = inputs["air_density_max_alt_kg_p_m3"]
        wing_area = inputs["wing_area_m2"]
        ar = inputs["wing_aspect_ratio"]
        eff = inputs["span_effic_factor"]
        cd0 = inputs["total_drag_coef"]
        wing_cd_cruise = inputs["wing_airfoil_cd_at_cruise_cl"]
        stopped_rotor_cd0 = inputs["stopped_rotor_cd0"]
        f_wing = inputs["cruise_wing_lift_fraction"]
        trim = inputs["trim_drag_factor"]
        excres = inputs["excres_protub_factor"]
        disk_area = inputs["disk_area_m2"]
        rotor_effic = inputs["rotor_effic"]
        epu_effic = inputs["epu_effic"]

        weight_n = m * g
        rotor_kw = rotor_effic * _W_P_KW  # common denominator
        two_rho_sl_A = 2.0 * rho_sl * disk_area

        def get(name):
            return inputs[name]

        # SEGMENT_KEYS order shaft powers, filled below.
        shaft = {}

        # ===== A: depart_taxi =====
        # horizontal only, v0=0, drag neglected.
        dt_avg = get("depart_taxi_avg_h_m_p_s")
        dt_s = get("depart_taxi_s")
        d_h_m = dt_avg * dt_s
        vf_h = (2.0 * d_h_m) / dt_s
        a_h = vf_h**2.0 / (2.0 * d_h_m)
        shaft["depart_taxi"] = (m * a_h * dt_avg) / rotor_kw

        # ===== B: hover_climb =====
        hc_avg = get("hover_climb_avg_v_m_p_s")
        hc_s = get("hover_climb_s")
        d_v_m = hc_avg * hc_s
        vf_v = (2.0 * d_v_m) / hc_s
        a_v = vf_v**2.0 / (2.0 * d_v_m)
        T_req = m * (g + a_v)
        v_i = np.sqrt(T_req / two_rho_sl_A)
        shaft["hover_climb"] = (T_req * v_i) / rotor_kw

        # ===== C: trans_climb =====
        # winged, vertical constant velocity (a_v=0), horizontal v0=0.
        tc_h = get("trans_climb_avg_h_m_p_s")
        tc_v = get("trans_climb_v_m_p_s")
        tc_s = get("trans_climb_s")
        q = 0.5 * rho_sl * tc_h**2.0
        theta = _atan2(tc_v, tc_h)
        lift_n = weight_n * np.cos(theta)
        _, _, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )
        vf_h = 2.0 * tc_h
        d_h_m = tc_h * tc_s
        a_h = (vf_h**2.0 - 0.0) / (2.0 * d_h_m)
        a_v = 0.0
        T_req = np.maximum(0.0, weight_n - lift_n + m * a_v)
        v_i = np.sqrt(T_req / two_rho_sl_A)
        P_hover = T_req * v_i
        force_h = total_drag_n + m * a_h
        shaft["trans_climb"] = (P_hover + force_h * tc_h) / rotor_kw

        # ===== D: depart_proc =====
        # winged, lift = full weight, constant velocity. rotor lift power if
        # rotor_lift > 0 (here lift==weight so rotor_lift==0).
        dp_h = get("depart_proc_h_m_p_s")
        dp_s = get("depart_proc_s")
        q = 0.5 * rho_sl * dp_h**2.0
        lift_n = weight_n
        _, _, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )
        force_h = total_drag_n
        rotor_lift_n = np.maximum(0.0, weight_n - lift_n)
        # P_vertical only when rotor_lift > 0; np.where keeps it cs-safe.
        v_induced = np.sqrt(rotor_lift_n / two_rho_sl_A)
        P_vertical_kw = np.where(
            rotor_lift_n > 0.0, (rotor_lift_n * v_induced) / rotor_kw, 0.0
        )
        shaft["depart_proc"] = (force_h * dp_h) / rotor_kw + P_vertical_kw

        # ===== E: accel_climb =====
        ac_h = get("accel_climb_avg_h_m_p_s")
        ac_v = get("accel_climb_v_m_p_s")
        ac_s = get("accel_climb_s")
        q = 0.5 * rho_sl * ac_h**2.0
        theta = _atan2(ac_v, ac_h)
        lift_n = weight_n * np.cos(theta)
        _, _, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )
        v0_h = get("depart_proc_h_m_p_s")
        vf_h = 2.0 * ac_h - v0_h
        d_h_m = ac_h * ac_s
        a_h = (vf_h**2.0 - v0_h**2.0) / (2.0 * d_h_m)
        v0_v = 0.0
        vf_v = ac_v
        d_v_m = 0.5 * (v0_v + vf_v) * ac_s
        a_v = (vf_v**2.0 - v0_v**2.0) / (2.0 * d_v_m)
        force_h = total_drag_n + m * a_h
        force_v = (weight_n - lift_n) + m * a_v
        shaft["accel_climb"] = (
            force_h * ac_h + force_v * (0.5 * (v0_v + vf_v))
        ) / rotor_kw

        # ===== F: cruise =====
        # uses max-alt density; powered-lift fraction f_wing.
        cr_h = get("cruise_h_m_p_s")
        q = 0.5 * rho_alt * cr_h**2.0
        V = cr_h
        wing_lift_n = f_wing * weight_n
        rotor_lift_n = (1.0 - f_wing) * weight_n
        di_n = (wing_lift_n**2.0) / (q * wing_area * np.pi * ar * eff)
        cd0_cruise = cd0 + wing_cd_cruise + stopped_rotor_cd0
        dp_n = q * wing_area * cd0_cruise
        total_drag_n = (di_n + dp_n) * trim * excres
        P_horizontal_kw = (total_drag_n * V) / rotor_kw
        v_induced = np.sqrt(rotor_lift_n / (2.0 * rho_alt * disk_area))
        P_vertical_kw = np.where(
            rotor_lift_n > 0.0, (rotor_lift_n * v_induced) / rotor_kw, 0.0
        )
        shaft["cruise"] = P_horizontal_kw + P_vertical_kw
        cruise_avg_shaft_power_kw = shaft["cruise"]

        # ===== G: decel_descend =====
        shaft["decel_descend"] = self._descend_with_assist_and_spoiler(
            avg_h=get("decel_descend_avg_h_m_p_s"),
            seg_v=get("decel_descend_v_m_p_s"),
            seg_s=get("decel_descend_s"),
            v0_h=get("cruise_h_m_p_s"),
            rho=rho_sl,
            weight_n=weight_n, m=m, wing_area=wing_area, ar=ar, eff=eff,
            cd0=cd0, trim=trim, excres=excres, two_rho_A=two_rho_sl_A,
            rotor_kw=rotor_kw,
        )

        # ===== H: arrive_proc =====  (identical structure to depart_proc)
        ap_h = get("arrive_proc_h_m_p_s")
        ap_s = get("arrive_proc_s")
        q = 0.5 * rho_sl * ap_h**2.0
        lift_n = weight_n
        _, _, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )
        force_h = total_drag_n
        rotor_lift_n = np.maximum(0.0, weight_n - lift_n)
        v_induced = np.sqrt(rotor_lift_n / two_rho_sl_A)
        P_vertical_kw = np.where(
            rotor_lift_n > 0.0, (rotor_lift_n * v_induced) / rotor_kw, 0.0
        )
        shaft["arrive_proc"] = (force_h * ap_h) / rotor_kw + P_vertical_kw

        # ===== I: trans_descend =====
        shaft["trans_descend"] = self._trans_descend(
            avg_h=get("trans_descend_avg_h_m_p_s"),
            seg_v=get("trans_descend_v_m_p_s"),
            seg_s=get("trans_descend_s"),
            v0_h=2.0 * get("trans_descend_avg_h_m_p_s"),
            v0_v=get("decel_descend_v_m_p_s"),
            vf_v=get("trans_descend_v_m_p_s"),
            d_v_abs=True,
            rho=rho_sl,
            weight_n=weight_n, m=m, wing_area=wing_area, ar=ar, eff=eff,
            cd0=cd0, trim=trim, excres=excres, two_rho_A=two_rho_sl_A,
            rotor_kw=rotor_kw,
        )

        # ===== J: hover_descend =====
        hd_avg = get("hover_descend_avg_v_m_p_s")
        hd_s = get("hover_descend_s")
        v0_v = 2.0 * hd_avg
        vf_v = 0.0
        d_v_m = hd_avg * hd_s
        a_v = (vf_v**2.0 - v0_v**2.0) / (2.0 * d_v_m)
        T_req = np.maximum(0.0, m * (g + a_v))
        v_i = np.sqrt(T_req / two_rho_sl_A)
        shaft["hover_descend"] = (T_req * v_i) / rotor_kw

        # ===== K: arrive_taxi =====
        at_avg = get("arrive_taxi_avg_h_m_p_s")
        at_s = get("arrive_taxi_s")
        v0_h = 0.0
        vf_h = 2.0 * at_avg
        d_h_m = at_avg * at_s
        a_h = (vf_h**2.0 - v0_h**2.0) / (2.0 * d_h_m)
        force_h = m * a_h
        shaft["arrive_taxi"] = (force_h * at_avg) / rotor_kw

        # ===== B': reserve_hover_climb =====
        rhc_avg = get("reserve_hover_climb_avg_v_m_p_s")
        rhc_s = get("reserve_hover_climb_s")
        d_v_m = rhc_avg * rhc_s
        vf_v = (2.0 * d_v_m) / rhc_s
        a_v = vf_v**2.0 / (2.0 * d_v_m)
        T_req = m * (g + a_v)
        v_i = np.sqrt(T_req / two_rho_sl_A)
        shaft["reserve_hover_climb"] = (T_req * v_i) / rotor_kw

        # ===== C': reserve_trans_climb =====  (same as trans_climb)
        rtc_h = get("reserve_trans_climb_avg_h_m_p_s")
        rtc_v = get("reserve_trans_climb_v_m_p_s")
        rtc_s = get("reserve_trans_climb_s")
        q = 0.5 * rho_sl * rtc_h**2.0
        theta = _atan2(rtc_v, rtc_h)
        lift_n = weight_n * np.cos(theta)
        _, _, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )
        vf_h = 2.0 * rtc_h
        d_h_m = rtc_h * rtc_s
        a_h = (vf_h**2.0 - 0.0) / (2.0 * d_h_m)
        a_v = 0.0
        T_req = np.maximum(0.0, weight_n - lift_n + m * a_v)
        v_i = np.sqrt(T_req / two_rho_sl_A)
        P_hover = T_req * v_i
        force_h = total_drag_n + m * a_h
        shaft["reserve_trans_climb"] = (P_hover + force_h * rtc_h) / rotor_kw

        # ===== E': reserve_accel_climb =====
        # NOTE: source uses reserve_accel_climb_v_m_p_s (NOT 0.5*(v0+vf)) in the
        # vertical-power term, and a_v = 0. Transcribed exactly.
        rac_h = get("reserve_accel_climb_avg_h_m_p_s")
        rac_v = get("reserve_accel_climb_v_m_p_s")
        rac_s = get("reserve_accel_climb_s")
        q = 0.5 * rho_sl * rac_h**2.0
        theta = _atan2(rac_v, rac_h)
        lift_n = weight_n * np.cos(theta)
        _, _, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )
        v0_h = 2.0 * rtc_h  # final of reserve_trans_climb
        vf_h = 2.0 * rac_h - v0_h
        d_h_m = rac_h * rac_s
        a_h = (vf_h**2.0 - v0_h**2.0) / (2.0 * d_h_m)
        a_v = 0.0
        force_h = total_drag_n + m * a_h
        force_v = (weight_n - lift_n) + m * a_v
        shaft["reserve_accel_climb"] = (
            force_h * rac_h + force_v * rac_v
        ) / rotor_kw

        # ===== F': reserve_cruise =====  (same as cruise, sea-... no: max-alt)
        rcr_h = get("reserve_cruise_h_m_p_s")
        q = 0.5 * rho_alt * rcr_h**2.0
        V = rcr_h
        wing_lift_n = f_wing * weight_n
        rotor_lift_n = (1.0 - f_wing) * weight_n
        di_n = (wing_lift_n**2.0) / (q * wing_area * np.pi * ar * eff)
        cd0_cruise = cd0 + wing_cd_cruise + stopped_rotor_cd0
        dp_n = q * wing_area * cd0_cruise
        total_drag_n = (di_n + dp_n) * trim * excres
        P_horizontal_kw = (total_drag_n * V) / rotor_kw
        v_induced = np.sqrt(rotor_lift_n / (2.0 * rho_alt * disk_area))
        P_vertical_kw = np.where(
            rotor_lift_n > 0.0, (rotor_lift_n * v_induced) / rotor_kw, 0.0
        )
        shaft["reserve_cruise"] = P_horizontal_kw + P_vertical_kw

        # ===== G': reserve_decel_descend =====
        shaft["reserve_decel_descend"] = self._descend_with_assist_and_spoiler(
            avg_h=get("reserve_decel_descend_avg_h_m_p_s"),
            seg_v=get("reserve_decel_descend_v_m_p_s"),
            seg_s=get("reserve_decel_descend_s"),
            v0_h=get("reserve_cruise_h_m_p_s"),
            rho=rho_sl,
            weight_n=weight_n, m=m, wing_area=wing_area, ar=ar, eff=eff,
            cd0=cd0, trim=trim, excres=excres, two_rho_A=two_rho_sl_A,
            rotor_kw=rotor_kw,
        )

        # ===== I': reserve_trans_descend =====
        # v0_h = 2*reserve_decel_descend_avg_h - reserve_cruise_h
        shaft["reserve_trans_descend"] = self._trans_descend(
            avg_h=get("reserve_trans_descend_avg_h_m_p_s"),
            seg_v=get("reserve_trans_descend_v_m_p_s"),
            seg_s=get("reserve_trans_descend_s"),
            v0_h=2.0 * get("reserve_decel_descend_avg_h_m_p_s")
            - get("reserve_cruise_h_m_p_s"),
            v0_v=get("reserve_decel_descend_v_m_p_s"),
            vf_v=get("reserve_trans_descend_v_m_p_s"),
            d_v_abs=False,
            rho=rho_sl,
            weight_n=weight_n, m=m, wing_area=wing_area, ar=ar, eff=eff,
            cd0=cd0, trim=trim, excres=excres, two_rho_A=two_rho_sl_A,
            rotor_kw=rotor_kw,
        )

        # ===== J': reserve_hover_descend =====  (same as hover_descend)
        rhd_avg = get("reserve_hover_descend_avg_v_m_p_s")
        rhd_s = get("reserve_hover_descend_s")
        v0_v = 2.0 * rhd_avg
        vf_v = 0.0
        d_v_m = rhd_avg * rhd_s
        a_v = (vf_v**2.0 - v0_v**2.0) / (2.0 * d_v_m)
        T_req = np.maximum(0.0, m * (g + a_v))
        v_i = np.sqrt(T_req / two_rho_sl_A)
        shaft["reserve_hover_descend"] = (T_req * v_i) / rotor_kw

        # ----- assemble outputs in SEGMENT_KEYS order -----
        # Build via np.array so the dtype follows the inputs (real or complex
        # under complex step). Each shaft value is a length-1 input-derived
        # array; reshape to scalar before stacking.
        power_list = []
        energy_list = []
        for key in SEGMENT_KEYS:
            shaft_kw = np.reshape(shaft[key], ())
            elec_kw = shaft_kw / epu_effic  # electric = shaft / epu_effic
            seg_s = np.reshape(get(_DURATION_KEY[key]), ())
            power_list.append(elec_kw)
            energy_list.append((elec_kw * seg_s) / _S_P_HR)
        power = np.array(power_list)
        energy = np.array(energy_list)

        outputs["segment_energy_kw_hr"] = energy
        outputs["segment_power_kw"] = power
        outputs["total_mission_energy_kw_hr"] = np.sum(energy)
        reserve_idx = [SEGMENT_KEYS.index(k) for k in _RESERVE_KEYS]
        outputs["total_reserve_mission_energy_kw_hr"] = np.sum(
            energy[reserve_idx]
        )
        outputs["peak_power_kw"] = np.max(power)
        outputs["cruise_avg_shaft_power_kw"] = np.reshape(
            cruise_avg_shaft_power_kw, ()
        )

    # ----- descent kernels (vertical assist + spoiler recompute) ----------
    def _descend_with_assist_and_spoiler(
        self, *, avg_h, seg_v, seg_s, v0_h, rho, weight_n, m, wing_area, ar,
        eff, cd0, trim, excres, two_rho_A, rotor_kw,
    ):
        """decel_descend / reserve_decel_descend kernel.

        Baseline force balance + gravity-deficit vertical assist + spoiler-drag
        recompute when net shaft power goes negative. The two ``if`` branches in
        the source (``vertical_deficit_n > 0`` and ``shaft_power_kw < 0``) are
        reproduced with ``np.where`` so the result matches exactly and stays
        complex-safe.
        """
        q = 0.5 * rho * avg_h**2.0
        theta = _atan2(seg_v, avg_h)
        lift_n = weight_n * np.cos(theta)
        di_n, dp_n, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )

        vf_h = 2.0 * avg_h - v0_h
        d_h_m = avg_h * seg_s
        a_h = (vf_h**2.0 - v0_h**2.0) / (2.0 * d_h_m)

        v0_v = 0.0
        vf_v = seg_v
        d_v_m = 0.5 * (v0_v + vf_v) * seg_s
        a_v = (vf_v**2.0 - v0_v**2.0) / (2.0 * d_v_m)
        v_avg_v = 0.5 * (v0_v + vf_v)

        force_h = total_drag_n + m * a_h
        force_v = (weight_n - lift_n) - m * a_v  # downward, speeding up

        shaft_baseline = (force_h * avg_h + force_v * v_avg_v) / rotor_kw

        # vertical assist if gravity insufficient
        vertical_deficit_n = m * a_v - (weight_n - lift_n)
        deficit_kw = np.where(
            vertical_deficit_n > 0.0,
            (vertical_deficit_n * v_avg_v) / rotor_kw,
            0.0,
        )
        shaft_kw = shaft_baseline + deficit_kw

        # spoiler-drag recompute when net power negative (and q>0, wing_area>0).
        required_extra_force_n = -force_h
        delta_cd_spoiler = required_extra_force_n / (q * wing_area)
        delta_cd_spoiler = np.maximum(0.0, delta_cd_spoiler)
        dp_spoiler_n = q * wing_area * delta_cd_spoiler
        total_drag_spoiler = (di_n + dp_n + dp_spoiler_n) * trim * excres
        force_h_spoiler = total_drag_spoiler + m * a_h
        shaft_spoiler = (
            force_h_spoiler * avg_h + force_v * v_avg_v
        ) / rotor_kw + deficit_kw

        return np.where(shaft_kw < 0.0, shaft_spoiler, shaft_kw)

    def _trans_descend(
        self, *, avg_h, seg_v, seg_s, v0_h, v0_v, vf_v, d_v_abs, rho,
        weight_n, m, wing_area, ar, eff, cd0, trim, excres, two_rho_A,
        rotor_kw,
    ):
        """trans_descend / reserve_trans_descend kernel.

        Hover-induced vertical assist (T_req floored at 0) + horizontal forces,
        with a spoiler-drag recompute when net shaft power goes negative.
        ``d_v_abs`` selects ``0.5*(|v0_v|+|vf_v|)`` (trans_descend) vs
        ``0.5*(v0_v+vf_v)`` (reserve_trans_descend) for the vertical distance.
        """
        q = 0.5 * rho * avg_h**2.0
        theta = _atan2(seg_v, avg_h)
        lift_n = weight_n * np.cos(theta)
        di_n, dp_n, total_drag_n = self._winged_aero(
            q, lift_n, wing_area, ar, eff, cd0, trim, excres
        )

        vf_h = 0.0
        d_h_m = avg_h * seg_s
        a_h = (vf_h**2.0 - v0_h**2.0) / (2.0 * d_h_m)

        if d_v_abs:
            d_v_m = 0.5 * (np.abs(v0_v) + np.abs(vf_v)) * seg_s
        else:
            d_v_m = 0.5 * (v0_v + vf_v) * seg_s
        a_v = (vf_v**2.0 - v0_v**2.0) / (2.0 * d_v_m)

        force_h = total_drag_n + m * a_h
        T_req = np.maximum(0.0, (weight_n - lift_n) + m * a_v)
        v_i = np.sqrt(T_req / two_rho_A)
        P_hover = T_req * v_i

        shaft_kw = (P_hover + force_h * avg_h) / rotor_kw

        # spoiler recompute when power negative
        required_extra_force_n = -force_h
        delta_cd_spoiler = required_extra_force_n / (q * wing_area)
        delta_cd_spoiler = np.maximum(0.0, delta_cd_spoiler)
        dp_spoiler_n = q * wing_area * delta_cd_spoiler
        total_drag_spoiler = (di_n + dp_n + dp_spoiler_n) * trim * excres
        force_h_spoiler = total_drag_spoiler + m * a_h
        shaft_spoiler = (P_hover + force_h_spoiler * avg_h) / rotor_kw

        return np.where(shaft_kw < 0.0, shaft_spoiler, shaft_kw)
