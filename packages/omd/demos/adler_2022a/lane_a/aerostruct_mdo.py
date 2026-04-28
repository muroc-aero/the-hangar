"""Lane A: programmatic single-cell MDO for the Adler 2022a reproduction.

Two paths:
  --method mission_based  -> mirrors upstream
                              upstream/openconcept/openconcept/examples/B738_aerostructural.py
                              with the mission_range parameterized.
  --method single_point   -> builds the standalone problem the same way the
                              `oas/AerostructFixedPoint` factory does.

This script is the parity reference for Lane B. Run it and compare the
converged fuel_burn / W_wing / AR / taper / sweep against
`omd-cli run lane_b/<method>/plan.yaml --mode optimize`.

Usage:
    uv run python packages/omd/demos/adler_2022a/lane_a/aerostruct_mdo.py \
        --method single_point --range 1500
    uv run python packages/omd/demos/adler_2022a/lane_a/aerostruct_mdo.py \
        --method mission_based --range 1500
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import openmdao.api as om

# Ensure the demo package is importable from the lane_a/ subdir
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _run_single_point(mission_range: float) -> dict:
    """Use the omd factory directly to build + optimize a single-point
    Bréguet problem at the given mission range."""
    from hangar.omd.factories.oas_aerostruct_fixed import (
        build_oas_aerostruct_fixed,
    )
    config = {
        "mode": "single_point",
        "mission_range_nmi": float(mission_range),
        "MTOW_kg": 79002.0,
        "tsfc_g_per_kN_s": 17.76,
        "flight_points": [
            {"mach": 0.78, "altitude_ft": 35000.0, "weight_fraction": 0.5,
             "gamma_deg": 0.0},
        ],
        "surface_grid": dict(num_x=3, num_y=7, num_twist=4, num_toverc=4,
                             num_skin=4, num_spar=4),
        "maneuver": dict(load_factor=2.5, mach=0.78, altitude_ft=20000.0,
                         num_x=3, num_y=7, num_twist=4, num_toverc=4,
                         num_skin=4, num_spar=4),
    }
    prob, meta = build_oas_aerostruct_fixed(config, {})
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["maxiter"] = 150
    prob.driver.options["tol"] = 1.0e-6
    prob.driver.options["debug_print"] = ["objs", "nl_cons"]

    prob.model.add_objective("breguet.fuel_burn_kg", scaler=1.0e-3)
    prob.model.add_constraint("2_5g_KS_failure", upper=0.0)
    prob.model.add_design_var("ac|geom|wing|AR", lower=5.0, upper=10.4)
    prob.model.add_design_var("ac|geom|wing|c4sweep", lower=0.0, upper=35.0,
                              units="deg")
    prob.model.add_design_var("ac|geom|wing|taper", lower=0.01, upper=0.35,
                              scaler=10.0)
    prob.model.add_design_var(
        "ac|geom|wing|twist",
        lower=np.array([0.0, -10.0, -10.0, -10.0]),
        upper=np.array([0.0, 10.0, 10.0, 10.0]),
        units="deg",
    )
    prob.model.add_design_var(
        "ac|geom|wing|toverc",
        lower=np.array([0.030, 0.053, 0.077, 0.10]),
        upper=0.25,
    )
    prob.model.add_design_var("ac|geom|wing|skin_thickness", lower=0.003,
                              upper=0.10, units="m", scaler=100.0)
    prob.model.add_design_var("ac|geom|wing|spar_thickness", lower=0.003,
                              upper=0.10, units="m", scaler=100.0)
    prob.setup(check=False, mode="fwd")
    t0 = time.perf_counter()
    prob.run_driver()
    wall = time.perf_counter() - t0
    return {
        "fuel_burn_kg": float(prob.get_val("breguet.fuel_burn_kg", units="kg")),
        "W_wing_kg":   float(prob.get_val("W_wing_maneuver", units="kg")),
        "AR":          float(prob.get_val("ac|geom|wing|AR")),
        "taper":       float(prob.get_val("ac|geom|wing|taper")),
        "c4sweep_deg": float(prob.get_val("ac|geom|wing|c4sweep", units="deg")),
        "failure":     float(prob.get_val("failure_maneuver")),
        "wall_time_s": wall,
    }


def _run_mission_based(mission_range: float) -> dict:
    """Run the upstream B738_aerostructural.py optimization with the
    mission range parameterized. The upstream module exposes
    `configure_problem` and `set_values` which we reuse, only changing
    the mission_range argument to set_values."""
    # Repo root is parents[4] of this file
    # (lane_a -> adler_2022a -> demos -> omd -> packages -> ROOT).
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[4]
                / "upstream" / "openconcept"),
    )
    from openconcept.examples.B738_aerostructural import (
        configure_problem, set_values, NUM_X, NUM_Y,
    )
    num_nodes = 11
    prob = configure_problem(num_nodes)
    prob.setup(check=False, mode="fwd")
    set_values(prob, num_nodes, mission_range=mission_range)
    t0 = time.perf_counter()
    prob.run_driver()
    wall = time.perf_counter() - t0
    return {
        "fuel_burn_kg": float(prob.get_val("descent.fuel_used_final", units="kg")),
        "W_wing_kg":   float(prob.get_val("ac|weights|W_wing", units="kg")),
        "AR":          float(prob.get_val("ac|geom|wing|AR")),
        "taper":       float(prob.get_val("ac|geom|wing|taper")),
        "c4sweep_deg": float(prob.get_val("ac|geom|wing|c4sweep", units="deg")),
        "failure":     float(prob.get_val("2_5g_KS_failure")),
        "wall_time_s": wall,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--method", choices=["single_point", "mission_based"],
                   required=True)
    p.add_argument("--range", type=float, default=1500.0,
                   help="Mission range in nmi")
    args = p.parse_args()
    if args.method == "single_point":
        result = _run_single_point(args.range)
    else:
        result = _run_mission_based(args.range)
    print()
    print(f"Adler 2022a Lane A  ({args.method}, range={args.range:.0f} nmi)")
    print("-" * 60)
    for k, v in result.items():
        print(f"  {k:<14} {v:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
