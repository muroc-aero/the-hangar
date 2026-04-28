"""Aerostructural fixed-flight-point factory.

Builds a standalone OpenMDAO problem that performs N aerostructural
analyses at fixed flight conditions plus a 2.5 g maneuver sizing,
then computes a fuel-burn objective using the Bréguet range equation
(or Adler 2022a Eq. 2 for climb segments).

Used by the Adler 2022a reproduction demo for the three Bréguet-style
methods (single_point / multipoint / single_point_plus_climb) that
are not implemented in upstream OpenConcept. The mission-based
variant uses the OCP factory directly (full mission integration).

Design references:
  - upstream/openconcept/openconcept/examples/B738_aerostructural.py
    (lines 263-318: maneuver group + alpha balance pattern)
  - Adler & Martins (2022a) Section IV (TSFC, mission-range eq.)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import openmdao.api as om

from hangar.omd.factory_metadata import FactoryMetadata


# Paper Section IV: constant TSFC for the Bréguet methods
_DEFAULT_TSFC_G_PER_KN_S = 17.76
# B738 reference values (paper Table 1 / OCP b738 template)
_DEFAULT_MTOW_KG = 79002.0
# Raymer wing-weight estimate from upstream B738_aerostructural.py:240-249
_DEFAULT_ORIG_W_WING_KG = 6561.57
_DEFAULT_PAYLOAD_KG = 17260.0  # roughly 174 pax + bags

# Default surface mesh (kept coarse for tractable wall time)
_DEFAULT_SURFACE_GRID: dict[str, int] = {
    "num_x": 3,
    "num_y": 7,
    "num_twist": 4,
    "num_toverc": 4,
    "num_skin": 4,
    "num_spar": 4,
}

# Default 2.5 g maneuver flight condition (paper Section IV)
_DEFAULT_MANEUVER: dict[str, float] = {
    "load_factor": 2.5,
    "mach": 0.78,
    "altitude_ft": 20000.0,
}


def _isa_speed_of_sound(altitude_ft: float) -> float:
    """ISA speed of sound, m/s. Linear-temperature troposphere
    below 36,089 ft, isothermal stratosphere above."""
    h_m = altitude_ft * 0.3048
    if h_m < 11000.0:
        T = 288.15 - 0.0065 * h_m
    else:
        T = 216.65
    gamma = 1.4
    R_air = 287.05
    return float(np.sqrt(gamma * R_air * T))


def _isa_density(altitude_ft: float) -> float:
    """ISA air density, kg/m**3."""
    h_m = altitude_ft * 0.3048
    if h_m < 11000.0:
        T = 288.15 - 0.0065 * h_m
        p = 101325.0 * (T / 288.15) ** (9.80665 / (287.05 * 0.0065))
    else:
        T = 216.65
        p11 = 101325.0 * (T / 288.15) ** (9.80665 / (287.05 * 0.0065))
        p = p11 * np.exp(-9.80665 * (h_m - 11000.0) / (287.05 * T))
    return float(p / (287.05 * T))


class _FixedAerostructPoint(om.Group):
    """One aerostructural analysis at fixed (mach, altitude) plus a
    Lift + alpha-balance that drives `fltcond|CL` so L = W·cos γ.

    Reads `ac|geom|wing|*` from the parent (shared across all points
    and the maneuver). Reads `weight_at_point` (kg) from the parent
    and converts to a lift target. Outputs `drag` (N), `L_over_D`,
    `ac|weights|W_wing`, `failure`.
    """

    def initialize(self):
        self.options.declare("mach", types=float)
        self.options.declare("altitude_ft", types=float)
        self.options.declare("gamma_deg", types=float, default=0.0)
        self.options.declare(
            "weight_fraction", types=float, default=0.5,
            desc="Fraction of fuel burned at this point. Per-point lift "
            "target uses W = MTOW - frac * fuel_estimate; for the standalone "
            "Breguet methods we use the upper bound MTOW * (1 - 0.5 * 0.10) "
            "as a starting estimate.",
        )
        self.options.declare(
            "fuel_fraction_estimate", types=float, default=0.10,
            desc="Initial estimate for fuel-burned fraction of MTOW. "
            "10% is a typical narrowbody mission value; the optimizer will "
            "iterate around it. Affects the weight at the cruise point only.",
        )
        self.options.declare("num_x", types=int, default=3)
        self.options.declare("num_y", types=int, default=7)
        self.options.declare("num_twist", types=int, default=4)
        self.options.declare("num_toverc", types=int, default=4)
        self.options.declare("num_skin", types=int, default=4)
        self.options.declare("num_spar", types=int, default=4)
        self.options.declare(
            "surf_options", types=dict, default=None, allow_none=True,
        )

    def setup(self):
        from openconcept.aerodynamics.openaerostruct.aerostructural import (
            AerostructDragPolar,
        )

        mach = self.options["mach"]
        alt_ft = self.options["altitude_ft"]
        gamma_rad = float(np.deg2rad(self.options["gamma_deg"]))
        nn = 1

        # Pre-compute ISA atmospheric properties at this fixed altitude.
        rho = _isa_density(alt_ft)
        a_sound = _isa_speed_of_sound(alt_ft)
        v_true = mach * a_sound
        q = 0.5 * rho * v_true ** 2

        # Fixed flight-condition IVC. AerostructDragPolar wants
        # `fltcond|h, M, q, CL` as inputs (vector of length nn).
        ivc = om.IndepVarComp()
        ivc.add_output("fltcond|h", val=alt_ft, units="ft", shape=(nn,))
        ivc.add_output("fltcond|M", val=mach, shape=(nn,))
        ivc.add_output("fltcond|q", val=q, units="Pa", shape=(nn,))
        ivc.add_output("fltcond|rho", val=rho, units="kg/m**3", shape=(nn,))
        ivc.add_output("fltcond|Utrue", val=v_true, units="m/s", shape=(nn,))
        self.add_subsystem("ivc", ivc, promotes_outputs=["*"])

        # Lift target: L = MTOW * (1 - frac * fuel_frac_est) * g * cos(gamma)
        # MTOW is promoted from the parent's `ac|weights|MTOW` IVC so
        # all points share the same source value. frac and fuel_frac_est
        # are constants per point.
        wf = float(self.options["weight_fraction"])
        ffe = float(self.options["fuel_fraction_estimate"])
        weight_const_factor = 1.0 - wf * ffe
        self.add_subsystem(
            "lift_target",
            om.ExecComp(
                "L_target = MTOW * weight_factor * 9.807 * cos_gamma",
                L_target={"units": "N", "shape": (nn,)},
                MTOW={"units": "kg", "shape": (nn,), "val": _DEFAULT_MTOW_KG},
                weight_factor={"shape": (nn,), "val": weight_const_factor},
                cos_gamma={"shape": (nn,), "val": float(np.cos(gamma_rad))},
            ),
            promotes_inputs=[("MTOW", "ac|weights|MTOW")],
        )

        # CL_target = L_target / (q * S_ref)
        self.add_subsystem(
            "cl_target",
            om.ExecComp(
                "CL_target = L_target / (q * S_ref)",
                CL_target={"shape": (nn,)},
                L_target={"units": "N", "shape": (nn,)},
                q={"units": "Pa", "shape": (nn,)},
                S_ref={"units": "m**2", "val": 124.6},
            ),
            promotes_inputs=[("S_ref", "ac|geom|wing|S_ref")],
        )
        self.connect("lift_target.L_target", "cl_target.L_target")
        self.connect("fltcond|q", "cl_target.q")

        # AerostructDragPolar wants fltcond|CL as input. The "single
        # point" methods don't actually solve a force balance; they
        # set CL = CL_target and compute drag at that CL. This matches
        # how the paper computes L/D for the Bréguet objective.
        self.add_subsystem(
            "cl_passthrough",
            om.ExecComp(
                "fltcond_CL = CL_target",
                fltcond_CL={"shape": (nn,)},
                CL_target={"shape": (nn,)},
            ),
        )
        self.connect("cl_target.CL_target", "cl_passthrough.CL_target")

        # AerostructDragPolar (surrogate over Mach, AoA, altitude).
        self.add_subsystem(
            "drag",
            AerostructDragPolar(
                num_nodes=nn,
                num_x=self.options["num_x"],
                num_y=self.options["num_y"],
                num_twist=self.options["num_twist"],
                num_toverc=self.options["num_toverc"],
                num_skin=self.options["num_skin"],
                num_spar=self.options["num_spar"],
                surf_options=self.options["surf_options"] or {},
            ),
            promotes_inputs=[
                "ac|geom|wing|S_ref",
                "ac|geom|wing|AR",
                "ac|geom|wing|taper",
                "ac|geom|wing|c4sweep",
                "ac|geom|wing|twist",
                "ac|geom|wing|toverc",
                "ac|geom|wing|skin_thickness",
                "ac|geom|wing|spar_thickness",
                "ac|aero|CD_nonwing",
            ],
            promotes_outputs=[
                ("drag", "drag"),
                ("ac|weights|W_wing", "ac|weights|W_wing"),
                ("failure", "failure"),
            ],
        )
        self.connect("fltcond|h", "drag.fltcond|h")
        self.connect("fltcond|M", "drag.fltcond|M")
        self.connect("fltcond|q", "drag.fltcond|q")
        self.connect("cl_passthrough.fltcond_CL", "drag.fltcond|CL")

        # L/D for the Bréguet equation
        self.add_subsystem(
            "lift_over_drag",
            om.ExecComp(
                "L_over_D = L_target / drag",
                L_over_D={"shape": (nn,)},
                L_target={"units": "N", "shape": (nn,)},
                drag={"units": "N", "shape": (nn,)},
            ),
        )
        self.connect("lift_target.L_target", "lift_over_drag.L_target")
        self.connect("drag", "lift_over_drag.drag")


def _build_breguet_objective(mode: str, n_cruise: int) -> om.ExecComp:
    """Construct the fuel-burn ExecComp.

    For ``single_point`` and ``multipoint`` modes it evaluates the
    Bréguet range equation at each cruise point and averages. For
    ``single_point_plus_climb`` it evaluates Adler Eq. 2 at the climb
    point + Bréguet at the cruise point.

    Inputs (all scalar except where noted):
      L_over_D_i  : L/D at point i              (n_cruise of these)
      W_initial   : kg, initial weight for the segment
      R_m         : m, range used in the equation
      V_ms        : m/s, true airspeed at the point (or representative)
      TSFC        : 1/s, paper-spec 17.76e-6 (g/kN/s = 1e-6 / s)
      gamma       : rad, flight-path angle (climb only)

    Output:
      fuel_burn_kg : kg
    """
    g = 9.807
    if mode == "single_point":
        return om.ExecComp(
            "fuel_burn_kg = W_initial_0 * (1.0 - exp(-R_0 * TSFC * g / (V_0 * L_over_D_0)))",
            fuel_burn_kg={"units": "kg"},
            W_initial_0={"units": "kg", "val": _DEFAULT_MTOW_KG},
            R_0={"units": "m", "val": 1500.0 * 1852.0},
            V_0={"units": "m/s", "val": 230.0},
            TSFC={"val": _DEFAULT_TSFC_G_PER_KN_S * 1.0e-6 / 1.0},
            L_over_D_0={"val": 18.0},
            g={"val": g},
        )
    if mode == "multipoint":
        # average of n Bréguet evaluations
        terms = []
        kw: dict[str, Any] = {
            "fuel_burn_kg": {"units": "kg"},
            "TSFC": {"val": _DEFAULT_TSFC_G_PER_KN_S * 1.0e-6},
            "g": {"val": g},
        }
        for i in range(n_cruise):
            terms.append(
                f"W_initial_{i} * (1.0 - exp(-R_{i} * TSFC * g / "
                f"(V_{i} * L_over_D_{i})))"
            )
            kw[f"W_initial_{i}"] = {"units": "kg", "val": _DEFAULT_MTOW_KG}
            kw[f"R_{i}"] = {"units": "m", "val": 1500.0 * 1852.0}
            kw[f"V_{i}"] = {"units": "m/s", "val": 230.0}
            kw[f"L_over_D_{i}"] = {"val": 18.0}
        expr = "fuel_burn_kg = (" + " + ".join(terms) + f") / {float(n_cruise)}"
        return om.ExecComp(expr, **kw)
    if mode == "single_point_plus_climb":
        # Adler Eq. 2 for climb (one segment) + Bréguet for cruise
        # (one segment). Single-line formula avoids ExecComp's chained-
        # output issue: ExecComp wants every name to be either purely
        # an input or purely an output, never both.
        # NOTE: W_initial_cruise should equal MTOW - fuel_climb if
        # we wanted strict accounting, but for the simple Bréguet
        # estimator we use MTOW - 0.5 * 0.10 * MTOW as a starting
        # estimate (set via set_input_defaults at build time).
        return om.ExecComp(
            "fuel_burn_kg = "
            "W_initial_climb * (exp((1.0 / L_over_D_climb + gamma_climb) "
            "* TSFC * R_climb * g / V_climb) - 1.0) "
            "+ W_initial_cruise * (1.0 - exp(-R_cruise * TSFC * g "
            "/ (V_cruise * L_over_D_cruise)))",
            fuel_burn_kg={"units": "kg"},
            W_initial_climb={"units": "kg", "val": _DEFAULT_MTOW_KG},
            W_initial_cruise={"units": "kg", "val": _DEFAULT_MTOW_KG},
            L_over_D_climb={"val": 12.0},
            L_over_D_cruise={"val": 18.0},
            R_climb={"units": "m", "val": 100.0 * 1852.0},
            R_cruise={"units": "m", "val": 1400.0 * 1852.0},
            V_climb={"units": "m/s", "val": 180.0},
            V_cruise={"units": "m/s", "val": 230.0},
            gamma_climb={"val": float(np.deg2rad(3.0))},
            TSFC={"val": _DEFAULT_TSFC_G_PER_KN_S * 1.0e-6},
            g={"val": g},
        )
    raise ValueError(f"Unknown mode: {mode!r}")


def build_oas_aerostruct_fixed(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a standalone aerostructural optimization with a Bréguet
    objective.

    See module docstring for paper context.

    component_config keys:
      mode: 'single_point' | 'multipoint' | 'single_point_plus_climb'
      flight_points: list of {mach, altitude_ft, weight_fraction,
                              gamma_deg, range_fraction (sp+climb only)}
        weight_fraction: fraction of MTOW used as W_initial for this
          segment's Bréguet eval (e.g. 0.5 means MTOW - 0.5 * fuel_burn,
          the standard "half-fuel" assumption)
        range_fraction: fraction of mission range covered by this
          segment (climb is usually small, ~0.07 for a 1500 nmi mission
          at typical climb profiles). Only meaningful for
          single_point_plus_climb mode.
      tsfc_g_per_kN_s: paper Section IV uses 17.76 (default)
      mission_range_nmi: 1500 (default; sweep overrides)
      MTOW_kg: 79002 (B738 default)
      payload_kg: 17260 (default; needed for OEW residual)
      surface_grid: {num_x, num_y, num_twist, num_toverc, num_skin,
                     num_spar, surf_options}
      maneuver: {load_factor, mach, altitude_ft, num_x, num_y, ...}
        (defaults match paper Section IV: 2.5 g, M0.78, 20000 ft)
    """
    # Local import keeps OCP optional at registry time.
    from hangar.omd.slots import _OasManeuverGroup

    mode = component_config.get("mode", "single_point")
    if mode not in ("single_point", "multipoint", "single_point_plus_climb"):
        raise ValueError(
            f"Unknown mode {mode!r}; expected 'single_point', 'multipoint', "
            "or 'single_point_plus_climb'"
        )

    grid = {**_DEFAULT_SURFACE_GRID, **(component_config.get("surface_grid") or {})}
    maneuver_cfg = {**_DEFAULT_MANEUVER, **(component_config.get("maneuver") or {})}
    surf_options = grid.get("surf_options", {})
    mission_range_nmi = float(component_config.get("mission_range_nmi", 1500.0))
    mission_range_m = mission_range_nmi * 1852.0
    MTOW = float(component_config.get("MTOW_kg", _DEFAULT_MTOW_KG))
    orig_W_wing = float(
        component_config.get("orig_W_wing_kg", _DEFAULT_ORIG_W_WING_KG)
    )
    tsfc_units = float(
        component_config.get("tsfc_g_per_kN_s", _DEFAULT_TSFC_G_PER_KN_S)
    ) * 1.0e-6  # g/kN/s -> 1/s

    flight_points = component_config.get("flight_points") or []
    if not flight_points:
        raise ValueError("component_config['flight_points'] must be non-empty")

    # Categorise points: climb segments use gamma_deg > 0; everything
    # else is treated as cruise. For single_point_plus_climb expect
    # exactly one of each.
    climb_points = [fp for fp in flight_points if float(fp.get("gamma_deg", 0.0)) > 1e-6]
    cruise_points = [fp for fp in flight_points if float(fp.get("gamma_deg", 0.0)) <= 1e-6]
    n_cruise = len(cruise_points)
    if mode == "single_point" and n_cruise != 1:
        raise ValueError("single_point mode requires exactly 1 cruise flight point")
    if mode == "multipoint" and n_cruise < 2:
        raise ValueError("multipoint mode requires at least 2 cruise flight points")
    if mode == "single_point_plus_climb" and (len(climb_points) != 1 or n_cruise != 1):
        raise ValueError(
            "single_point_plus_climb mode requires exactly 1 climb point and 1 cruise point"
        )

    prob = om.Problem(reports=False)
    model = prob.model

    # Aircraft data IVC. These are the wing geometry / sizing values
    # that all aerostruct points + the maneuver share.
    dv_comp = om.IndepVarComp()
    dv_comp.add_output("ac|geom|wing|S_ref", val=124.6, units="m**2")
    dv_comp.add_output("ac|geom|wing|AR", val=9.45)
    dv_comp.add_output("ac|geom|wing|taper", val=0.159)
    dv_comp.add_output("ac|geom|wing|c4sweep", val=25.0, units="deg")
    dv_comp.add_output(
        "ac|geom|wing|twist",
        val=np.linspace(-2.0, 2.0, grid["num_twist"]),
        units="deg",
    )
    dv_comp.add_output(
        "ac|geom|wing|toverc",
        val=0.12 * np.ones(grid["num_toverc"]),
    )
    dv_comp.add_output(
        "ac|geom|wing|skin_thickness",
        val=np.linspace(0.005, 0.015, grid["num_skin"]),
        units="m",
    )
    dv_comp.add_output(
        "ac|geom|wing|spar_thickness",
        val=np.linspace(0.005, 0.010, grid["num_spar"]),
        units="m",
    )
    dv_comp.add_output("ac|aero|CD_nonwing", val=0.0145)
    dv_comp.add_output("ac|weights|MTOW", val=MTOW, units="kg")
    dv_comp.add_output("ac|weights|orig_W_wing", val=orig_W_wing, units="kg")
    dv_comp.add_output("load_factor", val=maneuver_cfg["load_factor"])
    model.add_subsystem("ac", dv_comp, promotes_outputs=["*"])

    fuel_frac_est = float(component_config.get("fuel_fraction_estimate", 0.10))

    def _add_aerostruct_point(name: str, fp: dict) -> float:
        """Add a fixed aerostruct point. Returns the point's TAS (m/s)."""
        sub = _FixedAerostructPoint(
            mach=float(fp["mach"]),
            altitude_ft=float(fp["altitude_ft"]),
            gamma_deg=float(fp.get("gamma_deg", 0.0)),
            weight_fraction=float(fp.get("weight_fraction", 0.5)),
            fuel_fraction_estimate=fuel_frac_est,
            num_x=grid["num_x"],
            num_y=grid["num_y"],
            num_twist=grid["num_twist"],
            num_toverc=grid["num_toverc"],
            num_skin=grid["num_skin"],
            num_spar=grid["num_spar"],
            surf_options=surf_options,
        )
        model.add_subsystem(
            name, sub,
            promotes_inputs=[
                "ac|geom|wing|S_ref", "ac|geom|wing|AR", "ac|geom|wing|taper",
                "ac|geom|wing|c4sweep", "ac|geom|wing|twist",
                "ac|geom|wing|toverc", "ac|geom|wing|skin_thickness",
                "ac|geom|wing|spar_thickness", "ac|aero|CD_nonwing",
                "ac|weights|MTOW",
            ],
        )
        return float(fp["mach"]) * _isa_speed_of_sound(float(fp["altitude_ft"]))

    # Per-cruise-point fixed aerostruct analyses
    cruise_subsys_names: list[str] = []
    cruise_velocities_ms: list[float] = []
    for i, fp in enumerate(cruise_points):
        name = f"cruise_{i}"
        cruise_subsys_names.append(name)
        cruise_velocities_ms.append(_add_aerostruct_point(name, fp))

    # Per-climb-point fixed aerostruct analysis
    climb_subsys_name = None
    climb_v_ms = None
    if climb_points:
        climb_subsys_name = "climb_pt"
        climb_v_ms = _add_aerostruct_point(climb_subsys_name, climb_points[0])

    # 2.5 g maneuver (paper Section IV.A). Self-feedback W_wing so the
    # maneuver's own structural weight feeds the lift-balance.
    maneuver = _OasManeuverGroup(
        num_x=int(maneuver_cfg.get("num_x", grid["num_x"])),
        num_y=int(maneuver_cfg.get("num_y", grid["num_y"])),
        num_twist=int(maneuver_cfg.get("num_twist", grid["num_twist"])),
        num_toverc=int(maneuver_cfg.get("num_toverc", grid["num_toverc"])),
        num_skin=int(maneuver_cfg.get("num_skin", grid["num_skin"])),
        num_spar=int(maneuver_cfg.get("num_spar", grid["num_spar"])),
        mach=float(maneuver_cfg["mach"]),
        altitude_ft=float(maneuver_cfg["altitude_ft"]),
        load_factor=float(maneuver_cfg["load_factor"]),
        surf_options=surf_options,
        self_feedback_W_wing=True,
    )
    model.add_subsystem(
        "maneuver", maneuver,
        promotes_inputs=[
            "ac|geom|wing|S_ref", "ac|geom|wing|AR", "ac|geom|wing|taper",
            "ac|geom|wing|c4sweep", "ac|geom|wing|toverc",
            "ac|geom|wing|skin_thickness", "ac|geom|wing|spar_thickness",
            "ac|geom|wing|twist", "ac|weights|MTOW",
            "ac|weights|orig_W_wing", "load_factor",
        ],
        promotes_outputs=[
            ("failure", "failure_maneuver"),
            ("ac|weights|W_wing", "W_wing_maneuver"),
        ],
    )

    # Bréguet / Adler-Eq.2 fuel-burn objective.
    # Build per-segment weight-at-point ExecComps and feed the
    # objective component.
    obj = _build_breguet_objective(mode, n_cruise)
    model.add_subsystem("breguet", obj)

    # Per-cruise-point L/D wiring into the objective component.
    # Each cruise-point Bréguet eval uses the FULL mission range
    # (paper: "averages fuel burn estimates from five flight
    # conditions"; each estimate is for the whole mission).
    for i, fp in enumerate(cruise_points):
        wf = float(fp.get("weight_fraction", 0.5))
        weight_const = MTOW * (1.0 - wf * fuel_frac_est)
        if mode == "single_point":
            model.connect(
                f"{cruise_subsys_names[i]}.lift_over_drag.L_over_D",
                "breguet.L_over_D_0",
                src_indices=[0],
            )
            model.set_input_defaults("breguet.W_initial_0", val=weight_const, units="kg")
            model.set_input_defaults("breguet.R_0", val=mission_range_m, units="m")
            model.set_input_defaults("breguet.V_0", val=cruise_velocities_ms[i], units="m/s")
        elif mode == "multipoint":
            model.connect(
                f"{cruise_subsys_names[i]}.lift_over_drag.L_over_D",
                f"breguet.L_over_D_{i}",
                src_indices=[0],
            )
            model.set_input_defaults(
                f"breguet.W_initial_{i}", val=weight_const, units="kg",
            )
            model.set_input_defaults(
                f"breguet.R_{i}", val=mission_range_m, units="m",
            )
            model.set_input_defaults(
                f"breguet.V_{i}", val=cruise_velocities_ms[i], units="m/s",
            )
        elif mode == "single_point_plus_climb":
            model.connect(
                f"{cruise_subsys_names[i]}.lift_over_drag.L_over_D",
                "breguet.L_over_D_cruise",
                src_indices=[0],
            )

    if mode == "single_point_plus_climb":
        # Climb point connection
        model.connect(
            f"{climb_subsys_name}.lift_over_drag.L_over_D",
            "breguet.L_over_D_climb",
            src_indices=[0],
        )
        # Heuristic: climb segment is ~7% of mission range below 1500
        # nmi, asymptoting down for longer missions. Use a fixed
        # 100 nmi climb segment by default; sweep can override via
        # config.
        climb_range_m = float(component_config.get("climb_range_nmi", 100.0)) * 1852.0
        cruise_range_m = max(0.0, mission_range_m - climb_range_m)
        # Initial weights: climb starts at MTOW; cruise starts at
        # MTOW - 0.5 * climb_fuel_estimate. For the optimizer's first
        # eval we use fixed estimates; the converged design will land
        # close to physical values.
        model.set_input_defaults("breguet.W_initial_climb", val=MTOW, units="kg")
        model.set_input_defaults(
            "breguet.W_initial_cruise", val=MTOW * 0.985, units="kg",
        )
        model.set_input_defaults("breguet.R_climb", val=climb_range_m, units="m")
        model.set_input_defaults("breguet.R_cruise", val=cruise_range_m, units="m")
        model.set_input_defaults(
            "breguet.V_climb", val=climb_v_ms or 180.0, units="m/s",
        )
        model.set_input_defaults(
            "breguet.V_cruise", val=cruise_velocities_ms[0], units="m/s",
        )
        model.set_input_defaults(
            "breguet.gamma_climb",
            val=float(np.deg2rad(climb_points[0].get("gamma_deg", 3.0))),
        )

    # Scalar `2_5g_KS_failure` alias so plans can match upstream's
    # constraint name (see B738_aerostructural.py:355).
    model.add_subsystem(
        "ks_alias",
        om.ExecComp(
            "two_5g_KS_failure = failure_maneuver",
            two_5g_KS_failure={"val": 0.0},
            failure_maneuver={"val": 0.0},
        ),
        promotes_inputs=[("failure_maneuver", "failure_maneuver")],
        promotes_outputs=[("two_5g_KS_failure", "2_5g_KS_failure")],
    )

    # Variable path mappings consumed by the materializer to resolve
    # plan-level short names.
    var_paths: dict[str, str] = {
        "aspect_ratio": "ac|geom|wing|AR",
        "ac|geom|wing|AR": "ac|geom|wing|AR",
        "taper": "ac|geom|wing|taper",
        "ac|geom|wing|taper": "ac|geom|wing|taper",
        "c4sweep": "ac|geom|wing|c4sweep",
        "ac|geom|wing|c4sweep": "ac|geom|wing|c4sweep",
        "twist_cp": "ac|geom|wing|twist",
        "toverc_cp": "ac|geom|wing|toverc",
        "skin_thickness_cp": "ac|geom|wing|skin_thickness",
        "spar_thickness_cp": "ac|geom|wing|spar_thickness",
        "fuel_burn_kg": "breguet.fuel_burn_kg",
        "failure_maneuver": "failure_maneuver",
        "2_5g_KS_failure": "2_5g_KS_failure",
        "W_wing_maneuver": "W_wing_maneuver",
    }

    metadata: FactoryMetadata = {
        "point_name": "breguet",
        "var_paths": var_paths,
        "output_names": [
            "breguet.fuel_burn_kg",
            "failure_maneuver",
            "W_wing_maneuver",
            "ac|geom|wing|AR",
            "ac|geom|wing|taper",
            "ac|geom|wing|c4sweep",
        ],
        "component_family": "oas_aerostruct_fixed",
    }

    return prob, metadata
