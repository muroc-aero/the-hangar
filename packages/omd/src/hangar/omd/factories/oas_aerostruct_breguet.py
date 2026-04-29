"""Aerostructural Bréguet fuel-burn factory.

Builds a standalone OpenMDAO problem that performs N aerostructural
analyses at fixed flight conditions plus a 2.5 g maneuver sizing,
then computes a fuel-burn objective using the Bréguet range equation
(or a modified Bréguet form with a climb-angle term for climb segments).

The factory is aircraft-agnostic. The caller must supply MTOW, TSFC,
payload, original wing weight estimate, and a maneuver flight
condition in ``component_config``. Three modes are exposed:

  * ``single_cruise_breguet`` -- one cruise point, one Bréguet eval.
  * ``averaged_cruise_breguet`` -- N cruise points, mean of N Bréguet
    evals (typical multipoint formulation).
  * ``cruise_plus_climb_breguet`` -- one climb point + one cruise
    point, modified Bréguet for climb plus standard Bréguet for cruise.

Design references:
  - upstream/openconcept/openconcept/examples/B738_aerostructural.py
    (lines 263-318: maneuver group + alpha balance pattern)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import openmdao.api as om

from hangar.omd.factory_metadata import FactoryMetadata
from hangar.sdk.errors import UserInputError


# OAS aerostruct coupled NLBGS defaults to maxiter=100 with
# err_on_non_converge=True. SLSQP probing the Bréguet objective with
# finite differences occasionally lands on poorly-conditioned wings where
# 100 NLBGS iterations are not enough; the AnalysisError then propagates
# up and kills the optimizer on first failure. Bump to 500 for any
# Problem whose model exposes the aerostructural coupled path. Triggers
# only on OAS topology, no effect on unrelated Problems in the process.
_NLBGS_MAXITER_OVERRIDE = 500
_AEROSTRUCT_PATCH_APPLIED = False


def _bump_aerostruct_nlbgs(system) -> None:
    """Walk the system tree, raising NLBGS maxiter on any subsystem named
    ``coupled`` whose nonlinear solver is the OAS aerostructural NLBGS."""
    for sub in system.system_iter(recurse=True, include_self=False):
        if sub.name != "coupled":
            continue
        solver = getattr(sub, "nonlinear_solver", None)
        if solver is None:
            continue
        try:
            solver.options["maxiter"] = _NLBGS_MAXITER_OVERRIDE
        except (KeyError, TypeError):
            pass


def _apply_aerostruct_solver_patch() -> None:
    global _AEROSTRUCT_PATCH_APPLIED
    if _AEROSTRUCT_PATCH_APPLIED:
        return
    original_setup = om.Problem.setup

    def _patched_setup(self, *args, **kwargs):
        result = original_setup(self, *args, **kwargs)
        try:
            _bump_aerostruct_nlbgs(self.model)
        except Exception:
            pass
        return result

    om.Problem.setup = _patched_setup
    _AEROSTRUCT_PATCH_APPLIED = True


_apply_aerostruct_solver_patch()


# Default surface mesh (kept coarse for tractable wall time). Mesh is
# the only optional config block; aircraft-specific values must be
# supplied explicitly.
_DEFAULT_SURFACE_GRID: dict[str, int] = {
    "num_x": 3,
    "num_y": 7,
    "num_twist": 4,
    "num_toverc": 4,
    "num_skin": 4,
    "num_spar": 4,
}

_VALID_MODES = (
    "single_cruise_breguet",
    "averaged_cruise_breguet",
    "cruise_plus_climb_breguet",
)


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
        self.options.declare("MTOW_kg", types=float)
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

        # Lift target: L = W_total * (1 - frac * fuel_frac_est) * g * cos(gamma)
        # W_total = MTOW + W_wing - orig_W_wing is computed at the parent
        # model level from the maneuver-sized W_wing, mirroring the
        # upstream B738_aerostructural.py:149-160 AddSubtractComp pattern.
        # Coupling W_wing into the lift balance is what gives the
        # optimizer a fuel-burn penalty for heavier wings.
        wf = float(self.options["weight_fraction"])
        ffe = float(self.options["fuel_fraction_estimate"])
        weight_const_factor = 1.0 - wf * ffe
        self.add_subsystem(
            "lift_target",
            om.ExecComp(
                "L_target = W_total * weight_factor * 9.807 * cos_gamma",
                L_target={"units": "N", "shape": (nn,)},
                W_total={"units": "kg", "shape": (nn,), "val": self.options["MTOW_kg"]},
                weight_factor={"shape": (nn,), "val": weight_const_factor},
                cos_gamma={"shape": (nn,), "val": float(np.cos(gamma_rad))},
            ),
            promotes_inputs=[("W_total", "ac|weights|W_total")],
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

        # Newton solver to drive AerostructDragPolar's BalanceComp
        # (alpha_bal: CL_OAS == fltcond|CL) to zero. Without this the
        # alpha stays at its initial guess of 1 deg and the surrogate
        # is evaluated off the lift target, polluting L/D gradients in
        # downstream optimization. Mirrors upstream usage at
        # openconcept/aerodynamics/openaerostruct/aerostructural.py:1549.
        self.nonlinear_solver = om.NewtonSolver(
            solve_subsystems=True, iprint=0,
        )
        self.nonlinear_solver.options["maxiter"] = 30
        self.nonlinear_solver.options["atol"] = 1e-8
        self.nonlinear_solver.options["rtol"] = 1e-8
        self.nonlinear_solver.options["err_on_non_converge"] = False
        self.linear_solver = om.DirectSolver()


def _build_breguet_objective(
    mode: str, n_cruise: int, MTOW_kg: float, tsfc_per_s: float,
) -> om.ExecComp:
    """Construct the fuel-burn ExecComp.

    For ``single_cruise_breguet`` and ``averaged_cruise_breguet`` modes
    the Bréguet range equation is evaluated at each cruise point and
    averaged. For ``cruise_plus_climb_breguet`` a modified Bréguet
    (with a climb-angle term) is evaluated at the climb point and
    summed with a standard Bréguet at the cruise point.

    Inputs (all scalar except where noted):
      L_over_D_i  : L/D at point i              (n_cruise of these)
      W_initial   : kg, initial weight for the segment
      R_m         : m, range used in the equation
      V_ms        : m/s, true airspeed at the point (or representative)
      TSFC        : 1/s
      gamma       : rad, flight-path angle (climb only)

    Output:
      fuel_burn_kg : kg
    """
    g = 9.807
    if mode == "single_cruise_breguet":
        return om.ExecComp(
            "fuel_burn_kg = W_total * weight_fraction_0 "
            "* (1.0 - exp(-R_0 * TSFC * g / (V_0 * L_over_D_0)))",
            fuel_burn_kg={"units": "kg"},
            W_total={"units": "kg", "val": MTOW_kg},
            weight_fraction_0={"val": 0.95},
            R_0={"units": "m", "val": 1500.0 * 1852.0},
            V_0={"units": "m/s", "val": 230.0},
            TSFC={"val": tsfc_per_s},
            L_over_D_0={"val": 18.0},
            g={"val": g},
        )
    if mode == "averaged_cruise_breguet":
        # average of n Bréguet evaluations, each scaled by W_total *
        # weight_fraction_i so the optimized wing weight feeds back.
        terms = []
        kw: dict[str, Any] = {
            "fuel_burn_kg": {"units": "kg"},
            "W_total": {"units": "kg", "val": MTOW_kg},
            "TSFC": {"val": tsfc_per_s},
            "g": {"val": g},
        }
        for i in range(n_cruise):
            terms.append(
                f"W_total * weight_fraction_{i} * (1.0 - exp(-R_{i} * TSFC * g / "
                f"(V_{i} * L_over_D_{i})))"
            )
            kw[f"weight_fraction_{i}"] = {"val": 0.95}
            kw[f"R_{i}"] = {"units": "m", "val": 1500.0 * 1852.0}
            kw[f"V_{i}"] = {"units": "m/s", "val": 230.0}
            kw[f"L_over_D_{i}"] = {"val": 18.0}
        expr = "fuel_burn_kg = (" + " + ".join(terms) + f") / {float(n_cruise)}"
        return om.ExecComp(expr, **kw)
    if mode == "cruise_plus_climb_breguet":
        # Modified Bréguet for climb (one segment) + standard Bréguet
        # for cruise (one segment), both scaled by W_total. Single-line
        # formula avoids ExecComp's chained-output issue: every name is
        # either purely an input or purely an output.
        # weight_fraction_climb=1.0 means climb starts at full W_total.
        # weight_fraction_cruise=0.985 approximates cruise-start weight
        # after a 1.5% fuel burn during climb.
        return om.ExecComp(
            "fuel_burn_kg = "
            "W_total * weight_fraction_climb * (exp((1.0 / L_over_D_climb + gamma_climb) "
            "* TSFC * R_climb * g / V_climb) - 1.0) "
            "+ W_total * weight_fraction_cruise * (1.0 - exp(-R_cruise * TSFC * g "
            "/ (V_cruise * L_over_D_cruise)))",
            fuel_burn_kg={"units": "kg"},
            W_total={"units": "kg", "val": MTOW_kg},
            weight_fraction_climb={"val": 1.0},
            weight_fraction_cruise={"val": 0.985},
            L_over_D_climb={"val": 12.0},
            L_over_D_cruise={"val": 18.0},
            R_climb={"units": "m", "val": 100.0 * 1852.0},
            R_cruise={"units": "m", "val": 1400.0 * 1852.0},
            V_climb={"units": "m/s", "val": 180.0},
            V_cruise={"units": "m/s", "val": 230.0},
            gamma_climb={"val": float(np.deg2rad(3.0))},
            TSFC={"val": tsfc_per_s},
            g={"val": g},
        )
    raise ValueError(f"Unknown mode: {mode!r}")


def _require_config(component_config: dict, key: str, kind: str) -> Any:
    """Fetch a required key from ``component_config`` or raise UserInputError."""
    if key not in component_config:
        raise UserInputError(
            f"oas/AerostructBreguet: required {kind} '{key}' missing from "
            "component_config. The factory is aircraft-agnostic; supply this "
            "value in the plan's component config (no module-level default).",
            details={"missing_key": key, "kind": kind},
        )
    return component_config[key]


def build_oas_aerostruct_breguet(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a standalone aerostructural optimization with a Bréguet
    fuel-burn objective.

    Required component_config keys:
      mode: 'single_cruise_breguet' | 'averaged_cruise_breguet'
            | 'cruise_plus_climb_breguet'
      flight_points: list of {mach, altitude_ft, weight_fraction,
                              gamma_deg, range_fraction (sp+climb only)}
        weight_fraction: fraction of MTOW used as W_initial for this
          segment's Bréguet eval (e.g. 0.5 means MTOW - 0.5 * fuel_burn,
          the standard "half-fuel" assumption)
      mission_range_nmi: full mission range in nautical miles
      MTOW_kg: maximum takeoff weight, kg
      tsfc_g_per_kN_s: thrust-specific fuel consumption (g/(kN·s))
      orig_W_wing_kg: initial wing-weight estimate, kg (used by the
        maneuver sizing group's W_wing self-feedback loop)
      payload_kg: payload weight, kg (used downstream for OEW residual)
      maneuver: {load_factor, mach, altitude_ft, num_x?, num_y?, ...}

    Optional component_config keys:
      surface_grid: {num_x, num_y, num_twist, num_toverc, num_skin,
                     num_spar, surf_options} -- defaults to a coarse mesh
      fuel_fraction_estimate: float, defaults to 0.10
      climb_range_nmi: float, only used for cruise_plus_climb_breguet
        (defaults to 100.0)
    """
    # Local import keeps OCP optional at registry time.
    from hangar.omd.slots import _OasManeuverGroup

    mode = _require_config(component_config, "mode", "config key")
    if mode not in _VALID_MODES:
        raise UserInputError(
            f"oas/AerostructBreguet: unknown mode {mode!r}; expected one of "
            f"{_VALID_MODES}",
            details={"mode": mode, "valid_modes": list(_VALID_MODES)},
        )

    # Required aircraft / engine config -- no defaults.
    MTOW = float(_require_config(component_config, "MTOW_kg", "aircraft config"))
    tsfc_units = float(
        _require_config(component_config, "tsfc_g_per_kN_s", "engine config")
    ) * 1.0e-6  # g/kN/s -> 1/s
    orig_W_wing = float(
        _require_config(component_config, "orig_W_wing_kg", "aircraft config")
    )
    # payload_kg currently only validates that the caller supplied it; it
    # is reserved for OEW-residual downstream consumers.
    _require_config(component_config, "payload_kg", "aircraft config")
    mission_range_nmi = float(
        _require_config(component_config, "mission_range_nmi", "mission config")
    )
    mission_range_m = mission_range_nmi * 1852.0

    maneuver_cfg_in = _require_config(component_config, "maneuver", "config block")
    if not isinstance(maneuver_cfg_in, dict):
        raise UserInputError(
            "oas/AerostructBreguet: 'maneuver' must be a dict with at least "
            "load_factor, mach, altitude_ft.",
            details={"maneuver": maneuver_cfg_in},
        )
    for required_key in ("load_factor", "mach", "altitude_ft"):
        if required_key not in maneuver_cfg_in:
            raise UserInputError(
                f"oas/AerostructBreguet: maneuver block missing required key "
                f"{required_key!r}.",
                details={"missing_key": required_key,
                         "supplied_maneuver": maneuver_cfg_in},
            )
    maneuver_cfg = dict(maneuver_cfg_in)

    grid = {**_DEFAULT_SURFACE_GRID, **(component_config.get("surface_grid") or {})}
    surf_options = grid.get("surf_options", {})

    flight_points = component_config.get("flight_points") or []
    if not flight_points:
        raise UserInputError(
            "oas/AerostructBreguet: component_config['flight_points'] must be "
            "non-empty.",
            details={"flight_points": flight_points},
        )

    # Categorise points: climb segments use gamma_deg > 0; everything
    # else is treated as cruise. For cruise_plus_climb_breguet expect
    # exactly one of each.
    climb_points = [fp for fp in flight_points if float(fp.get("gamma_deg", 0.0)) > 1e-6]
    cruise_points = [fp for fp in flight_points if float(fp.get("gamma_deg", 0.0)) <= 1e-6]
    n_cruise = len(cruise_points)
    if mode == "single_cruise_breguet" and n_cruise != 1:
        raise UserInputError(
            "single_cruise_breguet mode requires exactly 1 cruise flight point",
            details={"n_cruise": n_cruise},
        )
    if mode == "averaged_cruise_breguet" and n_cruise < 2:
        raise UserInputError(
            "averaged_cruise_breguet mode requires at least 2 cruise flight points",
            details={"n_cruise": n_cruise},
        )
    if mode == "cruise_plus_climb_breguet" and (
        len(climb_points) != 1 or n_cruise != 1
    ):
        raise UserInputError(
            "cruise_plus_climb_breguet mode requires exactly 1 climb point and 1 cruise point",
            details={"n_climb": len(climb_points), "n_cruise": n_cruise},
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
            MTOW_kg=MTOW,
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
                "ac|weights|W_total",
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

    # 2.5 g maneuver sizing group. Self-feedback W_wing so the
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

    # Aircraft total weight: MTOW + W_wing - orig_W_wing. Mirrors the
    # upstream B738_aerostructural.py:149-160 AddSubtractComp pattern.
    # This is what couples the maneuver-sized wing weight back into the
    # cruise lift-balance and the Bréguet objective. Without it, the
    # optimizer sees no fuel penalty for heavier wings.
    model.add_subsystem(
        "aircraft_weight",
        om.ExecComp(
            "W_total = MTOW + W_wing - orig_W_wing",
            W_total={"units": "kg", "val": MTOW},
            MTOW={"units": "kg", "val": MTOW},
            W_wing={"units": "kg", "val": orig_W_wing},
            orig_W_wing={"units": "kg", "val": orig_W_wing},
        ),
        promotes_inputs=[
            ("MTOW", "ac|weights|MTOW"),
            ("orig_W_wing", "ac|weights|orig_W_wing"),
        ],
        promotes_outputs=[("W_total", "ac|weights|W_total")],
    )
    model.connect("W_wing_maneuver", "aircraft_weight.W_wing")

    # Bréguet fuel-burn objective. Promote W_total so it auto-wires from
    # aircraft_weight; weight_fraction_* are constants set per segment.
    obj = _build_breguet_objective(mode, n_cruise, MTOW, tsfc_units)
    model.add_subsystem(
        "breguet", obj,
        promotes_inputs=[("W_total", "ac|weights|W_total")],
    )

    # Per-cruise-point L/D wiring into the objective component.
    # Each cruise-point Bréguet eval uses the FULL mission range (each
    # estimate is an estimate for the entire mission). The W_initial
    # for each segment is W_total * weight_fraction_i, where W_total is
    # computed in `aircraft_weight` and weight_fraction_i ≈ 1 - wf*ffe
    # captures fuel burned by mid-segment.
    for i, fp in enumerate(cruise_points):
        wf = float(fp.get("weight_fraction", 0.5))
        weight_fraction_const = 1.0 - wf * fuel_frac_est
        if mode == "single_cruise_breguet":
            model.connect(
                f"{cruise_subsys_names[i]}.lift_over_drag.L_over_D",
                "breguet.L_over_D_0",
                src_indices=[0],
            )
            model.set_input_defaults("breguet.weight_fraction_0", val=weight_fraction_const)
            model.set_input_defaults("breguet.R_0", val=mission_range_m, units="m")
            model.set_input_defaults("breguet.V_0", val=cruise_velocities_ms[i], units="m/s")
        elif mode == "averaged_cruise_breguet":
            model.connect(
                f"{cruise_subsys_names[i]}.lift_over_drag.L_over_D",
                f"breguet.L_over_D_{i}",
                src_indices=[0],
            )
            model.set_input_defaults(
                f"breguet.weight_fraction_{i}", val=weight_fraction_const,
            )
            model.set_input_defaults(
                f"breguet.R_{i}", val=mission_range_m, units="m",
            )
            model.set_input_defaults(
                f"breguet.V_{i}", val=cruise_velocities_ms[i], units="m/s",
            )
        elif mode == "cruise_plus_climb_breguet":
            model.connect(
                f"{cruise_subsys_names[i]}.lift_over_drag.L_over_D",
                "breguet.L_over_D_cruise",
                src_indices=[0],
            )

    if mode == "cruise_plus_climb_breguet":
        # Climb point connection
        model.connect(
            f"{climb_subsys_name}.lift_over_drag.L_over_D",
            "breguet.L_over_D_climb",
            src_indices=[0],
        )
        # Heuristic: use a fixed 100 nmi climb segment by default;
        # the plan can override via climb_range_nmi.
        climb_range_m = float(component_config.get("climb_range_nmi", 100.0)) * 1852.0
        cruise_range_m = max(0.0, mission_range_m - climb_range_m)
        # Initial-weight fractions: climb starts at full W_total
        # (weight_fraction_climb=1.0); cruise starts at ~0.985 W_total
        # (rough estimate of post-climb weight). W_total itself is
        # supplied by aircraft_weight via promotion.
        model.set_input_defaults("breguet.weight_fraction_climb", val=1.0)
        model.set_input_defaults("breguet.weight_fraction_cruise", val=0.985)
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

    # Explicit execution order. The default RunOnce respects add-order,
    # but cruise points were added before maneuver / aircraft_weight for
    # readability. Without this reorder, cruise's lift_target reads the
    # default W_total (= MTOW) instead of the maneuver-coupled value.
    order = ["ac", "maneuver", "aircraft_weight"]
    order.extend(cruise_subsys_names)
    if climb_subsys_name is not None:
        order.append(climb_subsys_name)
    order.extend(["breguet", "ks_alias"])
    model.set_order(order)

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
        "component_family": "oas_aerostruct_breguet",
    }

    return prob, metadata
