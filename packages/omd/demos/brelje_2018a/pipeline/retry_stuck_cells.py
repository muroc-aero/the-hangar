"""Targeted retry for the 2 fig5 cells that the standard
warm-start retry already failed on.

Strategy: for each stuck cell, walk the K nearest converged
neighbors (instead of just the single nearest one that
``retry_failed.py`` uses) and take the first warm start that
converges; if none converge, fall back to a multistart-style
cold start with the kingair template defaults perturbed by +/-30%.
Overwrites the failed row in fig5_grid.csv on success.

Usage:
    uv run python packages/omd/demos/brelje_2018a/retry_stuck_cells.py \
        --cells 700,450 750,550 --k-neighbors 6
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DEMO_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = DEMO_DIR / "results"
sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(DEMO_DIR / "lane_a"))


WARM_KEYS = [
    ("ac|weights|MTOW", "kg", "MTOW_kg"),
    ("ac|geom|wing|S_ref", "m**2", "S_ref_m2"),
    ("ac|propulsion|engine|rating", "hp", "engine_rating_hp"),
    ("ac|propulsion|motor|rating", "hp", "motor_rating_hp"),
    ("ac|propulsion|generator|rating", "hp", "generator_rating_hp"),
    ("ac|weights|W_battery", "kg", "W_battery_kg"),
    ("cruise.hybridization", None, "cruise_hybridization"),
    ("climb.hybridization", None, "climb_hybridization"),
    ("descent.hybridization", None, "descent_hybridization"),
]


def _row_to_overrides(row: pd.Series) -> dict:
    return {(p, u): float(row[c]) for (p, u, c) in WARM_KEYS}


def _run(design_range, spec_energy, overrides, objective, label):
    from hybrid_mdo import build_mdo_problem

    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        t0 = time.perf_counter()
        prob = build_mdo_problem(design_range, spec_energy, objective)
        for (path, units), val in overrides.items():
            try:
                if units:
                    prob.set_val(path, val, units=units)
                else:
                    prob.set_val(path, val)
            except Exception:
                pass
        fail = prob.run_driver()
        wall = time.perf_counter() - t0

        fuel_kg = float(prob.get_val("descent.fuel_used_final", units="kg")[0])
        MTOW_kg = float(prob.get_val("ac|weights|MTOW", units="kg")[0])
        cruise_h = float(prob.get_val("cruise.hybridization")[0])
        out = {
            "design_range_nm": design_range,
            "spec_energy_whkg": spec_energy,
            "converged": not fail,
            "run_id": f"retry-stuck:{label}",
            "objective_value": (
                fuel_kg + MTOW_kg / 100.0 if objective == "fuel"
                else float(prob.get_val("doc_per_nmi")[0])
            ),
            "MTOW_kg": MTOW_kg,
            "MTOW_lb": MTOW_kg * 2.20462,
            "fuel_burn_kg": fuel_kg,
            "fuel_burn_lb": fuel_kg * 2.20462,
            "fuel_mileage_lb_per_nmi": fuel_kg * 2.20462 / design_range,
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
            "start_name": label,
            "starts_tried": 1,
        }
        return out


def _bracket_starts():
    """A handful of varied starting designs to try if all warm starts fail.
    Each entry is (label, dict-of-DV-overrides).
    The "high-electric" bracket was removed because it pushes the OpenConcept
    propeller MetaModelStructured surrogate out of grid and produces NaNs."""
    return [
        ("low-electric", {
            ("ac|weights|MTOW", "kg"): 4500.0,
            ("ac|geom|wing|S_ref", "m**2"): 25.0,
            ("ac|propulsion|engine|rating", "hp"): 850.0,
            ("ac|propulsion|motor|rating", "hp"): 600.0,
            ("ac|propulsion|generator|rating", "hp"): 850.0,
            ("ac|weights|W_battery", "kg"): 100.0,
            ("cruise.hybridization", None): 0.05,
            ("climb.hybridization", None): 0.05,
            ("descent.hybridization", None): 0.05,
        }),
        ("mid-hybrid", {
            ("ac|weights|MTOW", "kg"): 5000.0,
            ("ac|geom|wing|S_ref", "m**2"): 28.0,
            ("ac|propulsion|engine|rating", "hp"): 700.0,
            ("ac|propulsion|motor|rating", "hp"): 850.0,
            ("ac|propulsion|generator|rating", "hp"): 700.0,
            ("ac|weights|W_battery", "kg"): 700.0,
            ("cruise.hybridization", None): 0.30,
            ("climb.hybridization", None): 0.20,
            ("descent.hybridization", None): 0.05,
        }),
    ]


def _retry_one_cell(df, target_range, target_energy, objective, k_neighbors):
    converged = df[df["converged"].astype(str).str.lower() == "true"].copy()
    span = 500.0
    d = np.hypot(
        (converged["design_range_nm"].to_numpy() - target_range) / span,
        (converged["spec_energy_whkg"].to_numpy() - target_energy) / span,
    )
    order = np.argsort(d)[: k_neighbors]
    print(f"\n  cell ({target_range:.0f}, {target_energy:.0f}):  "
          f"trying {len(order)} warm-start neighbors then {len(_bracket_starts())} cold brackets")

    candidates = []

    def _attempt(label, overrides):
        try:
            result = _run(target_range, target_energy, overrides, objective, label)
        except Exception as exc:
            print(f"    EXC   {label:<32s}  {type(exc).__name__}: {str(exc)[:60]}",
                  flush=True)
            return None
        tag = "OK  " if result["converged"] else "FAIL"
        print(f"    {tag}  {label:<32s}  obj={result['objective_value']:>9.3f}  "
              f"MTOW={result['MTOW_kg']:>6.0f} kg  wall={result['wall_time_s']:>5.1f}s",
              flush=True)
        return result if result["converged"] else None

    for rank, idx in enumerate(order):
        n = converged.iloc[int(idx)]
        label = f"warm-n{rank}-r{int(n['design_range_nm'])}-e{int(n['spec_energy_whkg'])}"
        ok = _attempt(label, _row_to_overrides(n))
        if ok:
            candidates.append(ok)

    for label, ovr in _bracket_starts():
        ok = _attempt(label, ovr)
        if ok:
            candidates.append(ok)

    if not candidates:
        print(f"    no converged candidate; leaving the cell as-is")
        return None
    best = min(candidates, key=lambda r: r["objective_value"])
    print(f"    BEST: {best['run_id']}  obj={best['objective_value']:.3f}")
    best["starts_tried"] = len(order) + len(_bracket_starts())
    return best


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--objective", choices=["fuel", "cost"], default="fuel")
    p.add_argument("--cells", nargs="+", required=True,
                   help="cell coordinates as range,energy  e.g. 700,450 750,550")
    p.add_argument("--k-neighbors", type=int, default=6,
                   help="how many nearest converged neighbors to warm-start from")
    args = p.parse_args()

    csv_path = RESULTS_DIR / (f"fig5_grid.csv" if args.objective == "fuel" else "fig6_grid.csv")
    df = pd.read_csv(csv_path)

    cells = [tuple(float(x) for x in c.split(",")) for c in args.cells]
    print(f"Targeted retry for {len(cells)} cells in {csv_path.name}")

    rows_by_cell = {(float(r["design_range_nm"]), float(r["spec_energy_whkg"])): i
                    for i, r in df.iterrows()}

    n_fixed = 0
    for r, e in cells:
        idx = rows_by_cell.get((r, e))
        if idx is None:
            print(f"  cell ({r}, {e}) not present in CSV; skipping")
            continue
        old = df.iloc[idx]
        if str(old["converged"]).lower() == "true":
            print(f"  cell ({r:.0f}, {e:.0f}) already converged; skipping")
            continue
        result = _retry_one_cell(df, r, e, args.objective, args.k_neighbors)
        if result is None:
            continue
        for k, v in result.items():
            if k not in df.columns:
                continue
            # pd.read_csv infers StringDtype for sparsely-populated text
            # columns (error, start_name, starts_tried).  Setting an int
            # into one raises TypeError -- cast first.
            if pd.api.types.is_string_dtype(df[k].dtype):
                v = "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)
            df.at[idx, k] = v
        n_fixed += 1

    df.sort_values(["design_range_nm", "spec_energy_whkg"], inplace=True)
    df.to_csv(csv_path, index=False)
    n_converged_now = (df["converged"].astype(str).str.lower() == "true").sum()
    print(f"\nUpdated {csv_path}: {n_converged_now}/{len(df)} converged "
          f"(fixed {n_fixed} of {len(cells)} requested)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
