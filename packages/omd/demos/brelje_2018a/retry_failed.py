"""Re-run failed sweep cells with warm-started DV values from the
nearest converged neighbor.

Rationale: Brelje's 2018 paper notes that 1/252 runs failed on the
initial pass and was "easily rectified by changing the starting guess
to a more realistic set of design weights and component sizes."  Our
sweep.py starts every cell from the kingair template defaults, so the
long-range / low-spec-energy corner fails SLSQP.  This script reads
the current results CSV, finds each failed cell's nearest converged
neighbor (2-norm in the (range, spec_energy) grid), runs the Lane A
MDO entry point with that neighbor's converged DV values set before
run_driver, and overwrites the failed row in place.

Usage:
    uv run python packages/omd/demos/brelje_2018a/retry_failed.py \
        --objective fuel
    uv run python packages/omd/demos/brelje_2018a/retry_failed.py \
        --objective cost
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DEMO_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DEMO_DIR / "results"

sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(DEMO_DIR / "lane_a"))


def _warm_start_overrides(neighbor: pd.Series) -> dict[tuple[str, str | None], float]:
    """Return {(path, units): value} dict to feed prob.set_val()."""
    return {
        ("ac|weights|MTOW", "kg"):                 float(neighbor["MTOW_kg"]),
        ("ac|geom|wing|S_ref", "m**2"):            float(neighbor["S_ref_m2"]),
        ("ac|propulsion|engine|rating", "hp"):     float(neighbor["engine_rating_hp"]),
        ("ac|propulsion|motor|rating", "hp"):      float(neighbor["motor_rating_hp"]),
        ("ac|propulsion|generator|rating", "hp"):  float(neighbor["generator_rating_hp"]),
        ("ac|weights|W_battery", "kg"):            float(neighbor["W_battery_kg"]),
        ("cruise.hybridization", None):            float(neighbor["cruise_hybridization"]),
        ("climb.hybridization", None):             float(neighbor["climb_hybridization"]),
        ("descent.hybridization", None):           float(neighbor["descent_hybridization"]),
    }


def _retry_cell(
    design_range: float,
    spec_energy: float,
    overrides: dict,
    objective: str,
) -> dict:
    """Build and run a warm-started MDO; return the new result row."""
    from hybrid_mdo import build_mdo_problem

    t0 = time.perf_counter()
    prob = build_mdo_problem(design_range, spec_energy, objective)
    for (path, units), val in overrides.items():
        try:
            if units:
                prob.set_val(path, val, units=units)
            else:
                prob.set_val(path, val)
        except Exception:
            # Defensive: a bound violation or missing path shouldn't
            # abort the retry -- just skip the override.
            pass

    fail = prob.run_driver()
    wall = time.perf_counter() - t0

    fuel_kg = float(prob.get_val("descent.fuel_used_final", units="kg")[0])
    fuel_lb = fuel_kg * 2.20462
    MTOW_kg = float(prob.get_val("ac|weights|MTOW", units="kg")[0])
    cruise_h = float(prob.get_val("cruise.hybridization")[0])

    row = {
        "design_range_nm": design_range,
        "spec_energy_whkg": spec_energy,
        "converged": not fail,
        "run_id": "retry-warm-start",
        "objective_value": fuel_kg + MTOW_kg / 100.0 if objective == "fuel"
                           else float(prob.get_val("doc_per_nmi")[0]),
        "MTOW_kg": MTOW_kg,
        "MTOW_lb": MTOW_kg * 2.20462,
        "fuel_burn_kg": fuel_kg,
        "fuel_burn_lb": fuel_lb,
        "fuel_mileage_lb_per_nmi": fuel_lb / design_range,
        "W_battery_kg": float(prob.get_val("ac|weights|W_battery", units="kg")[0]),
        "S_ref_m2": float(prob.get_val("ac|geom|wing|S_ref", units="m**2")[0]),
        "cruise_hybridization": cruise_h,
        "climb_hybridization": float(prob.get_val("climb.hybridization")[0]),
        "descent_hybridization": float(prob.get_val("descent.hybridization")[0]),
        "electric_percent": 100.0 * cruise_h,
        "engine_rating_hp": float(prob.get_val("ac|propulsion|engine|rating", units="hp")[0]),
        "motor_rating_hp": float(prob.get_val("ac|propulsion|motor|rating", units="hp")[0]),
        "generator_rating_hp": float(prob.get_val("ac|propulsion|generator|rating", units="hp")[0]),
        "MTOW_margin_lb": float(prob.get_val("margins.MTOW_margin", units="lbm")[0]),
        "rotate_range_ft": float(prob.get_val("rotate.range_final", units="ft")[0]),
        "Vstall_kn": float(prob.get_val("v0v1.Vstall_eas", units="kn")[0]),
        "SOC_final": float(prob.get_val("descent.propmodel.batt1.SOC_final")[0]),
        "doc_per_nmi": float(prob.get_val("doc_per_nmi")[0]) if objective == "cost" else np.nan,
        "wall_time_s": wall,
        "error": "" if not fail else "slsqp-iter-limit-or-infeasible",
    }
    return row


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--objective", choices=["fuel", "cost"], default="fuel")
    p.add_argument("--warm-from", type=str, default=None,
                   help="Re-run EVERY cell using DVs from this CSV (same "
                        "grid) as warm starts.  Use to re-seed the cost "
                        "sweep from fig5_grid.csv (fuel optimum) to "
                        "escape a local minimum.")
    args = p.parse_args()

    csv_path = RESULTS_DIR / (f"fig5_grid.csv" if args.objective == "fuel" else "fig6_grid.csv")
    df = pd.read_csv(csv_path)

    if args.warm_from:
        warm_df = pd.read_csv(args.warm_from)
        warm_df = warm_df[warm_df["converged"].astype(str).str.lower() == "true"].copy()
        new_rows = []
        for _, cell in df.iterrows():
            r, e = float(cell["design_range_nm"]), float(cell["spec_energy_whkg"])
            match = warm_df[(warm_df.design_range_nm == r) & (warm_df.spec_energy_whkg == e)]
            if len(match) == 0:
                # Fall back to nearest neighbor in warm_df
                span = 500.0
                d = np.hypot(
                    (warm_df["design_range_nm"].to_numpy() - r) / span,
                    (warm_df["spec_energy_whkg"].to_numpy() - e) / span,
                )
                match = warm_df.iloc[[int(np.argmin(d))]]
            neigh = match.iloc[0]
            overrides = _warm_start_overrides(neigh)
            print(f"  cell r={r:.0f} e={e:.0f}  <- {Path(args.warm_from).name} "
                  f"r={neigh['design_range_nm']:.0f} e={neigh['spec_energy_whkg']:.0f} "
                  f"(MTOW={neigh['MTOW_kg']:.0f} kg)")
            try:
                new_row = _retry_cell(r, e, overrides, args.objective)
                status = "OK" if new_row["converged"] else f"FAIL ({new_row['error']})"
                print(f"    {status}  obj={new_row['objective_value']:.3f}  "
                      f"MTOW={new_row['MTOW_kg']:.0f} kg  "
                      f"doc={new_row['doc_per_nmi']:.4f}  "
                      f"wall={new_row['wall_time_s']:.1f}s")
                new_rows.append(new_row)
            except Exception as exc:
                print(f"    EXCEPTION: {type(exc).__name__}: {str(exc)[:80]}")
                new_rows.append(cell.to_dict())
        merged = pd.DataFrame(new_rows)
        merged.sort_values(["design_range_nm", "spec_energy_whkg"], inplace=True)
        merged.to_csv(csv_path, index=False)
        n_converged_now = (merged["converged"].astype(str).str.lower() == "true").sum()
        print(f"\nUpdated {csv_path}: {n_converged_now}/{len(merged)} converged.")
        return 0

    converged_mask = df["converged"].astype(str).str.lower() == "true"
    failed = df[~converged_mask].copy()
    converged = df[converged_mask].copy()
    if len(failed) == 0:
        print(f"No failed cells in {csv_path.name}.")
        return 0

    print(f"Retrying {len(failed)} failed cells from {csv_path.name} "
          f"with warm starts from {len(converged)} converged neighbors.")

    new_rows = []
    for _, cell in failed.iterrows():
        r, e = float(cell["design_range_nm"]), float(cell["spec_energy_whkg"])
        # Nearest converged neighbor by normalized L2 on the grid
        span = 500.0
        d = np.hypot(
            (converged["design_range_nm"].to_numpy() - r) / span,
            (converged["spec_energy_whkg"].to_numpy() - e) / span,
        )
        idx = int(np.argmin(d))
        neigh = converged.iloc[idx]
        overrides = _warm_start_overrides(neigh)
        print(f"  cell r={r:.0f} e={e:.0f}  <- neighbor r={neigh['design_range_nm']:.0f} "
              f"e={neigh['spec_energy_whkg']:.0f} (MTOW={neigh['MTOW_kg']:.0f} kg)")

        try:
            new_row = _retry_cell(r, e, overrides, args.objective)
            status = "OK" if new_row["converged"] else f"FAIL ({new_row['error']})"
            print(f"    {status}  obj={new_row['objective_value']:.3f}  "
                  f"fuel={new_row['fuel_burn_kg']:.1f} kg  "
                  f"MTOW={new_row['MTOW_kg']:.0f} kg  "
                  f"wall={new_row['wall_time_s']:.1f}s")
            new_rows.append(new_row)
        except Exception as exc:
            print(f"    EXCEPTION: {type(exc).__name__}: {str(exc)[:80]}")
            # Keep the original failed row so the CSV grid stays the
            # same shape; plotting masks non-converged cells anyway.
            new_rows.append(cell.to_dict())

    # Replace failed rows in place: drop all failed, append new rows
    merged = pd.concat(
        [converged, pd.DataFrame(new_rows)],
        ignore_index=True,
    )
    merged.sort_values(["design_range_nm", "spec_energy_whkg"], inplace=True)
    merged.to_csv(csv_path, index=False)
    n_converged_now = (merged["converged"].astype(str).str.lower() == "true").sum()
    print(f"\nUpdated {csv_path}: {n_converged_now}/{len(merged)} now converged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
