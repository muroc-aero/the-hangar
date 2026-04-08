"""pyCycle surrogate deck generation and OpenMDAO integration.

Provides two capabilities:

1. **Deck generation**: Run pyCycle off-design across a grid of
   (altitude, Mach, throttle) conditions and collect thrust, fuel flow,
   and other outputs into NumPy arrays suitable for Kriging training.

2. **Surrogate Group**: An OpenMDAO Group wrapping
   ``MetaModelUnStructuredComp`` with Kriging surrogates trained on a
   pyCycle deck. Matches the OCP propulsion interface (throttle,
   fltcond|h, fltcond|M -> thrust, fuel_flow).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import openmdao.api as om

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default grid specifications
# ---------------------------------------------------------------------------

# Turbojet: SLS design, narrow cruise envelope
DEFAULT_TURBOJET_GRID = {
    "alt_ft": [0.0, 5000.0, 10000.0, 15000.0, 20000.0],
    "MN": [0.05, 0.15, 0.25, 0.35, 0.45],
    "throttle": [0.5, 0.65, 0.8, 0.9, 1.0],
}

# HBTF: cruise design, wider envelope
DEFAULT_HBTF_GRID = {
    "alt_ft": [0.0, 10000.0, 20000.0, 30000.0, 40000.0],
    "MN": [0.2, 0.4, 0.55, 0.7, 0.85],
    "throttle": [0.3, 0.5, 0.7, 0.85, 1.0],
}


def _default_grid(archetype: str) -> dict:
    grids = {
        "turbojet": DEFAULT_TURBOJET_GRID,
        "hbtf": DEFAULT_HBTF_GRID,
    }
    return grids.get(archetype, DEFAULT_TURBOJET_GRID)


# ---------------------------------------------------------------------------
# Deck generation
# ---------------------------------------------------------------------------


def generate_deck(
    archetype: str = "turbojet",
    design_conditions: dict | None = None,
    engine_params: dict | None = None,
    grid_spec: dict | None = None,
) -> dict[str, np.ndarray]:
    """Run pyCycle off-design sweep and return training data arrays.

    Parameters
    ----------
    archetype : str
        Engine archetype name ("turbojet" or "hbtf").
    design_conditions : dict
        Design point: alt, MN, Fn_target, T4_target.
    engine_params : dict
        Engine parameters merged over archetype defaults.
    grid_spec : dict
        Grid arrays: alt_ft, MN, throttle. Full outer product is evaluated.

    Returns
    -------
    dict with keys:
        "alt_ft": (N,) array of altitudes in feet
        "MN": (N,) array of Mach numbers
        "throttle": (N,) array of throttle settings [0-1]
        "thrust_lbf": (N,) array of net thrust in lbf
        "fuel_flow_lbm_s": (N,) array of fuel flow in lbm/s
        "T4_degR": (N,) array of T4 in degR
        "converged": (N,) boolean mask of points that converged
    """
    from hangar.omd.pyc.archetypes import get_archetype
    from hangar.omd.pyc import defaults as defs

    params = dict(engine_params or {})
    grid = grid_spec or _default_grid(archetype)

    # Resolve design conditions
    if design_conditions is None:
        if archetype == "turbojet":
            design_conditions = dict(defs.DEFAULT_DESIGN_CONDITIONS)
        elif archetype == "hbtf":
            design_conditions = {
                "alt": 35000.0,
                "MN": 0.8,
                "Fn_target": defs.DEFAULT_HBTF_PARAMS["design_Fn"],
                "T4_target": defs.DEFAULT_HBTF_PARAMS["design_T4"],
            }
        else:
            design_conditions = dict(defs.DEFAULT_DESIGN_CONDITIONS)

    design_Fn = design_conditions["Fn_target"]

    # Build the outer product grid
    alt_vals = np.asarray(grid["alt_ft"])
    mn_vals = np.asarray(grid["MN"])
    thr_vals = np.asarray(grid["throttle"])

    alt_grid, mn_grid, thr_grid = np.meshgrid(
        alt_vals, mn_vals, thr_vals, indexing="ij"
    )
    alt_flat = alt_grid.ravel()
    mn_flat = mn_grid.ravel()
    thr_flat = thr_grid.ravel()
    n_points = len(alt_flat)

    # Build OD points for a multipoint problem
    od_points = []
    for i in range(n_points):
        fn_target = float(thr_flat[i] * design_Fn)
        od_points.append({
            "name": f"OD_{i}",
            "MN": float(mn_flat[i]),
            "alt": float(alt_flat[i]),
            "Fn_target": fn_target,
        })

    # Build and run the multipoint problem
    arch = get_archetype(archetype)
    if archetype == "turbojet":
        thrust_lbf, fuel_flow, T4, converged = _run_turbojet_deck(
            arch, params, design_conditions, od_points,
        )
    elif archetype == "hbtf":
        thrust_lbf, fuel_flow, T4, converged = _run_hbtf_deck(
            arch, params, design_conditions, od_points,
        )
    else:
        raise ValueError(f"Deck generation not supported for archetype: {archetype}")

    return {
        "alt_ft": alt_flat,
        "MN": mn_flat,
        "throttle": thr_flat,
        "thrust_lbf": thrust_lbf,
        "fuel_flow_lbm_s": fuel_flow,
        "T4_degR": T4,
        "converged": converged,
    }


def _run_turbojet_deck(
    arch: dict,
    params: dict,
    design_conditions: dict,
    od_points: list[dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Run turbojet off-design points individually for robustness.

    Each OD point is run as its own multipoint problem (1 design + 1 OD).
    This avoids one bad point killing an entire chunk, at the cost of
    re-solving the design point each time. For typical deck sizes
    (50-125 points) this takes 2-5 minutes.
    """
    from hangar.omd.pyc.builders import build_multipoint_problem

    n = len(od_points)
    thrust_all = np.zeros(n)
    fuel_all = np.zeros(n)
    T4_all = np.zeros(n)
    converged_all = np.ones(n, dtype=bool)

    for i, pt in enumerate(od_points):
        single_od = [{**pt, "name": "OD_0"}]
        try:
            prob = build_multipoint_problem(
                "turbojet", params, design_conditions, single_od,
            )
            _suppress_and_run(prob)
            thrust_all[i] = float(prob.get_val("OD_0.perf.Fn", units="lbf"))
            fuel_all[i] = float(prob.get_val("OD_0.burner.Wfuel", units="lbm/s"))
            T4_all[i] = float(prob.get_val("OD_0.burner.Fl_O:tot:T", units="degR"))
            # Sanity check: thrust and fuel must be positive
            if thrust_all[i] <= 0 or fuel_all[i] <= 0:
                converged_all[i] = False
            prob.cleanup()
        except Exception as e:
            logger.debug("OD point %d failed: %s", i, e)
            converged_all[i] = False

    n_ok = converged_all.sum()
    logger.info("Turbojet deck: %d/%d points converged", n_ok, n)
    return thrust_all, fuel_all, T4_all, converged_all


def _run_hbtf_deck(
    arch: dict,
    params: dict,
    design_conditions: dict,
    od_points: list[dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Run HBTF off-design points individually for robustness.

    HBTF off-design uses T4 throttle mode, so Fn_target is converted
    to a T4 value via linear mapping from throttle fraction.
    """
    from hangar.omd.pyc.archetypes import MPHbtf
    from hangar.omd.pyc.defaults import (
        DEFAULT_HBTF_PARAMS,
        DEFAULT_HBTF_DESIGN_GUESSES,
        DEFAULT_HBTF_OD_GUESSES,
    )

    merged = {**DEFAULT_HBTF_PARAMS, **params}
    n = len(od_points)
    design_T4 = design_conditions["T4_target"]
    design_Fn = design_conditions["Fn_target"]
    idle_T4 = 1800.0

    thrust_all = np.zeros(n)
    fuel_all = np.zeros(n)
    T4_all = np.zeros(n)
    converged_all = np.ones(n, dtype=bool)

    for i, pt in enumerate(od_points):
        thr_frac = pt["Fn_target"] / design_Fn
        t4_val = idle_T4 + thr_frac * (design_T4 - idle_T4)
        hbtf_od = [{
            "name": "OD_0",
            "MN": pt["MN"],
            "alt": pt["alt"],
            "throttle_mode": "T4",
        }]

        try:
            prob = om.Problem(reports=False)
            prob.model = MPHbtf(params=merged, od_points=hbtf_od)
            prob.setup(check=False)

            prob.set_val("DESIGN.fc.alt", design_conditions["alt"], units="ft")
            prob.set_val("DESIGN.fc.MN", design_conditions["MN"])
            prob.set_val("DESIGN.Fn_DES", design_Fn, units="lbf")
            prob.set_val("DESIGN.T4_MAX", design_T4, units="degR")

            dg = DEFAULT_HBTF_DESIGN_GUESSES
            prob.set_val("DESIGN.balance.FAR", dg["FAR"])
            prob.set_val("DESIGN.balance.W", dg["W"])
            prob.set_val("DESIGN.balance.lpt_PR", dg["lpt_PR"])
            prob.set_val("DESIGN.balance.hpt_PR", dg["hpt_PR"])
            prob.set_val("DESIGN.fc.conv.balance.Pt", dg["fc_Pt"])
            prob.set_val("DESIGN.fc.conv.balance.Tt", dg["fc_Tt"])

            og = DEFAULT_HBTF_OD_GUESSES
            prob.set_val("OD_0.fc.MN", pt["MN"])
            prob.set_val("OD_0.fc.alt", pt["alt"], units="ft")
            prob.set_val("OD_0.T4_MAX", t4_val, units="degR")
            prob.set_val("OD_0.balance.FAR", og["FAR"])
            prob.set_val("OD_0.balance.W", og["W"])
            prob.set_val("OD_0.balance.BPR", og["BPR"])
            prob.set_val("OD_0.balance.lp_Nmech", og["lp_Nmech"])
            prob.set_val("OD_0.balance.hp_Nmech", og["hp_Nmech"])

            _suppress_and_run(prob)

            thrust_all[i] = float(prob.get_val("OD_0.perf.Fn", units="lbf"))
            fuel_all[i] = float(prob.get_val("OD_0.burner.Wfuel", units="lbm/s"))
            T4_all[i] = float(prob.get_val("OD_0.burner.Fl_O:tot:T", units="degR"))
            if thrust_all[i] <= 0 or fuel_all[i] <= 0:
                converged_all[i] = False
            prob.cleanup()
        except Exception as e:
            logger.debug("HBTF OD point %d failed: %s", i, e)
            converged_all[i] = False

    n_ok = converged_all.sum()
    logger.info("HBTF deck: %d/%d points converged", n_ok, n)
    return thrust_all, fuel_all, T4_all, converged_all


def _suppress_and_run(prob: om.Problem) -> None:
    """Run problem with suppressed output."""
    import io
    import sys
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        prob.run_model()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


# ---------------------------------------------------------------------------
# Deck I/O
# ---------------------------------------------------------------------------


def save_deck(deck: dict[str, np.ndarray], path: str | Path) -> None:
    """Save a deck to a .npz file."""
    path = Path(path)
    np.savez_compressed(
        path,
        **{k: v for k, v in deck.items()},
    )


def load_deck(path: str | Path) -> dict[str, np.ndarray]:
    """Load a deck from a .npz file."""
    data = np.load(str(path))
    return {k: data[k] for k in data.files}


# ---------------------------------------------------------------------------
# OpenMDAO surrogate group
# ---------------------------------------------------------------------------


class PyCycleSurrogateGroup(om.Group):
    """Surrogate-coupled pyCycle propulsion model.

    Wraps ``MetaModelUnStructuredComp`` with Kriging surrogates trained
    on pyCycle off-design sweep data. Inputs match OCP propulsion
    interface: throttle (nn,), fltcond|h (nn,) in meters, fltcond|M (nn,).
    Outputs: thrust (nn,) in kN, fuel_flow (nn,) in kg/s.

    The deck is either loaded from ``deck_path`` (.npz file) or generated
    on-the-fly from the archetype + design conditions + grid spec.
    """

    def initialize(self):
        self.options.declare("nn", types=int)
        self.options.declare("archetype", default="turbojet")
        self.options.declare("design_alt", default=0.0)
        self.options.declare("design_MN", default=0.000001)
        self.options.declare("design_Fn", default=11800.0)
        self.options.declare("design_T4", default=2370.0)
        self.options.declare("engine_params", types=dict, default={})
        self.options.declare("deck_path", default=None, allow_none=True)
        self.options.declare("grid_spec", default=None, allow_none=True)

    def setup(self):
        nn = self.options["nn"]

        # Load or generate deck
        deck = self._get_deck()

        # Filter to converged points only
        mask = deck["converged"].astype(bool)
        alt_ft = deck["alt_ft"][mask]
        MN = deck["MN"][mask]
        throttle = deck["throttle"][mask]
        thrust_lbf = deck["thrust_lbf"][mask]
        fuel_flow_lbm_s = deck["fuel_flow_lbm_s"][mask]

        if len(alt_ft) < 4:
            raise RuntimeError(
                f"Only {len(alt_ft)} converged points in deck; need at least 4 "
                f"for Kriging. Check engine params and grid spec."
            )

        # Convert units to match OCP interface
        alt_m = alt_ft * 0.3048  # ft -> m
        thrust_kN = thrust_lbf * 4.44822e-3  # lbf -> kN
        fuel_flow_kg_s = fuel_flow_lbm_s * 0.453592  # lbm/s -> kg/s

        # Build surrogate for thrust
        thrust_mm = om.MetaModelUnStructuredComp(vec_size=nn)
        thrust_mm.add_input("throttle", training_data=throttle, val=np.ones(nn) * 0.8)
        thrust_mm.add_input("alt", training_data=alt_m, units="m",
                            val=np.ones(nn) * 10000.0)
        thrust_mm.add_input("MN", training_data=MN, val=np.ones(nn) * 0.5)
        thrust_mm.add_output(
            "thrust", training_data=thrust_kN, units="kN",
            val=np.ones(nn) * 10.0,
            surrogate=om.KrigingSurrogate(),
        )
        thrust_mm.add_output(
            "fuel_flow", training_data=fuel_flow_kg_s, units="kg/s",
            val=np.ones(nn) * 0.5,
            surrogate=om.KrigingSurrogate(),
        )

        self.add_subsystem(
            "surrogate",
            thrust_mm,
            promotes_inputs=[
                ("throttle", "throttle"),
                ("alt", "fltcond|h"),
                ("MN", "fltcond|M"),
            ],
            promotes_outputs=["thrust", "fuel_flow"],
        )

    def _get_deck(self) -> dict[str, np.ndarray]:
        """Load deck from file or generate on-the-fly."""
        deck_path = self.options["deck_path"]
        if deck_path is not None:
            return load_deck(deck_path)

        archetype = self.options["archetype"]
        design_conditions = {
            "alt": self.options["design_alt"],
            "MN": self.options["design_MN"],
            "Fn_target": self.options["design_Fn"],
            "T4_target": self.options["design_T4"],
        }
        grid_spec = self.options["grid_spec"]

        logger.info(
            "Generating %s surrogate deck (this may take a few minutes)...",
            archetype,
        )
        return generate_deck(
            archetype=archetype,
            design_conditions=design_conditions,
            engine_params=self.options["engine_params"],
            grid_spec=grid_spec,
        )
