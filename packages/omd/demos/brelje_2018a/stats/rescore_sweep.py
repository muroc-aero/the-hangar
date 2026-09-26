"""Re-score a sweep CSV's designs in the upstream truth model.

Every row of a sweep-style CSV (``results/fig{5,6}_grid.csv`` or any
file with the same design-variable columns) is evaluated once in
OpenConcept's own HybridTwin model (``upstream_truth.rescore_design``),
so a design is judged by what it does there -- feasibility under
upstream's constraints, and the upstream objective -- rather than by the
producing pipeline's numbers.

The omd sweep CSV has no ``W_fuel_max`` column; the design variable only
feeds structural weight, so every optimum sits on its 500 kg lower
bound, and that value is assumed when the column is absent (recorded in
the output's ``assumed`` column).

Output: ``results/rescored/<input stem>.csv`` with the upstream columns
plus ``src_objective`` and ``src_start_name``.

Usage:
    uv run python packages/omd/demos/brelje_2018a/stats/rescore_sweep.py \\
        packages/omd/demos/brelje_2018a/results/fig5_grid.csv --objective fuel
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import multiprocessing as mp
import os
import sys
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR / "lane_a_upstream"))

W_FUEL_MAX_DEFAULT_KG = 500.0


def _job(args):
    import warnings
    warnings.filterwarnings("ignore")
    import upstream_truth as u
    row, objective = args
    dvs = u._warm_from_row(row)
    assumed = ""
    if "ac|weights|W_fuel_max" not in dvs:
        dvs["ac|weights|W_fuel_max"] = W_FUEL_MAX_DEFAULT_KG
        assumed = f"W_fuel_max={W_FUEL_MAX_DEFAULT_KG:g}kg"
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn), \
            contextlib.redirect_stderr(dn):
        out = u.rescore_design(float(row["design_range_nm"]),
                               float(row["spec_energy_whkg"]), objective, dvs)
    out["src_objective"] = row.get("objective_value", "")
    out["src_start_name"] = row.get("start_name", "")
    out["src_converged"] = row.get("converged", "")
    out["assumed"] = assumed
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--objective", choices=["fuel", "cost"], required=True)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    import upstream_truth as u
    with open(args.csv) as f:
        rows = [r for r in csv.DictReader(f)
                if str(r.get("converged", "")).lower() == "true"]
    out_path = args.out or DEMO_DIR / "results" / "rescored" / f"{args.csv.stem}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = u.COLUMNS + ["src_objective", "src_start_name", "src_converged", "assumed"]
    results = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for i, r in enumerate(pool.imap_unordered(_job, [(r, args.objective) for r in rows]), 1):
            results.append(r)
            if i % 20 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    results.sort(key=lambda r: (r["design_range_nm"], r["spec_energy_whkg"]))
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    bad = [r for r in results if not r["feasible"]]
    print(f"{len(results)} designs re-scored -> {out_path.relative_to(DEMO_DIR)}; "
          f"{len(results) - len(bad)} feasible in upstream, {len(bad)} not")
    for r in bad:
        print(f"  r={r['design_range_nm']:g} e={r['spec_energy_whkg']:g} "
              f"start={r['src_start_name'] or '(retry)'} "
              f"viol={r['max_constraint_violation']:.3g} "
              f"margin={r['MTOW_margin_lb']:.1f} lb BFL={r['rotate_range_ft']:.0f} ft "
              f"{r['error'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
