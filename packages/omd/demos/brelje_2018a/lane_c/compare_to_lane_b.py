"""Lane C verification harness: prints the expected values a Lane C
agent run must reproduce for one cell from ``cells.yaml``, and (if a
Lane C result file is provided) checks the agent's converged values
against them within the cell's tolerance.

Two modes:

  1. baseline  -- print expected values for the cell.  Use this to
                  brief the Lane C agent before it runs.
                  If `source: paper-table-4`, the expected values
                  come from cells.yaml directly.
                  If `source: omd-sweep`, they come from
                  results/fig{5,6}_grid.csv at the matching cell.

  2. check     -- compare a Lane C result JSON to the expected values.
                  The result JSON must have flat keys matching
                  cells.yaml ``expect`` keys (e.g. mixed_objective,
                  MTOW_lb, fuel_lb).

Usage:

  # See what a Lane C run for paper-fuel-500-250 must reproduce
  uv run python packages/omd/demos/brelje_2018a/lane_c/compare_to_lane_b.py \\
      --cell paper-fuel-500-250 --mode baseline

  # Check a Lane C run's output JSON
  uv run python packages/omd/demos/brelje_2018a/lane_c/compare_to_lane_b.py \\
      --cell paper-fuel-500-250 --mode check \\
      --result lane_c_run.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

LANE_C_DIR = Path(__file__).resolve().parent
DEMO_DIR = LANE_C_DIR.parent
RESULTS_DIR = DEMO_DIR / "results"
CELLS_YAML = LANE_C_DIR / "cells.yaml"


# Translate cells.yaml ``expect`` keys to the columns sweep.py writes
# to results/fig{5,6}_grid.csv.  CSV is mostly SI; the lb/ft keys are
# computed once per row.
SWEEP_COL_MAP = {
    "mixed_objective": "objective_value",
    "MTOW_lb":         "MTOW_lb",
    "MTOW_kg":         "MTOW_kg",
    "fuel_lb":         "fuel_burn_lb",
    "fuel_kg":         "fuel_burn_kg",
    "W_battery_lb":    None,                 # SI-only in sweep CSV; converted
    "W_battery_kg":    "W_battery_kg",
    "Sref_m2":         "S_ref_m2",
    "Sref_ft2":        None,                 # SI-only in sweep CSV; converted
    "cruise_h":        "cruise_hybridization",
    "doc_per_nmi":     "doc_per_nmi",
}


def _load_cell(cell_id: str) -> dict:
    cells = yaml.safe_load(CELLS_YAML.read_text())["cells"]
    matches = [c for c in cells if c["id"] == cell_id]
    if not matches:
        raise SystemExit(f"cell '{cell_id}' not found in {CELLS_YAML.name}.\n"
                         f"Known: {[c['id'] for c in cells]}")
    return matches[0]


def _expected_from_sweep(cell: dict) -> dict:
    """Pull the expected values from the latest converged sweep CSV."""
    fig = "fig5" if cell["objective"] == "fuel" else "fig6"
    csv_path = RESULTS_DIR / f"{fig}_grid.csv"
    if not csv_path.exists():
        raise SystemExit(f"sweep CSV missing: {csv_path}\n"
                         f"Run `bash run_paper_grid.sh` first.")
    df = pd.read_csv(csv_path)
    row = df[(df.design_range_nm == cell["range_nm"])
             & (df.spec_energy_whkg == cell["spec_e"])]
    if len(row) == 0:
        raise SystemExit(
            f"cell ({cell['range_nm']}, {cell['spec_e']}) not in {csv_path.name}.\n"
            f"Sweep grid is {sorted(df.design_range_nm.unique())} x "
            f"{sorted(df.spec_energy_whkg.unique())}.")
    r = row.iloc[0]
    if str(r.converged).lower() != "true":
        raise SystemExit(f"cell ({cell['range_nm']}, {cell['spec_e']}) is not "
                         f"converged in {csv_path.name}.")
    expected = {
        "mixed_objective": float(r["objective_value"]) if cell["objective"] == "fuel"
                           else float(r["doc_per_nmi"]),
        "MTOW_lb":         float(r["MTOW_lb"]),
        "MTOW_kg":         float(r["MTOW_kg"]),
        "fuel_lb":         float(r["fuel_burn_lb"]),
        "fuel_kg":         float(r["fuel_burn_kg"]),
        "W_battery_kg":    float(r["W_battery_kg"]),
        "W_battery_lb":    float(r["W_battery_kg"]) * 2.20462,
        "Sref_m2":         float(r["S_ref_m2"]),
        "Sref_ft2":        float(r["S_ref_m2"]) * 10.7639,
        "cruise_h":        float(r["cruise_hybridization"]),
    }
    if cell["objective"] == "cost":
        expected["doc_per_nmi"] = float(r["doc_per_nmi"])
    return expected


def _expected_for(cell: dict) -> dict:
    """Resolve the expected values for `cell` according to its `source`."""
    if cell["source"] == "paper-table-4":
        return dict(cell["expect"])
    if cell["source"] == "omd-sweep":
        return _expected_from_sweep(cell)
    raise SystemExit(f"unknown source for cell {cell['id']}: {cell['source']!r}")


def cmd_baseline(cell: dict) -> int:
    expected = _expected_for(cell)
    tol_pct = float(cell.get("tol_pct", 5.0))
    print(f"\nLane C target -- cell {cell['id']}")
    print(f"  range_nm     : {cell['range_nm']}")
    print(f"  spec_energy  : {cell['spec_e']} Wh/kg")
    print(f"  objective    : {cell['objective']}")
    print(f"  source       : {cell['source']}")
    print(f"  tolerance    : +/- {tol_pct:.1f}% relative")
    print()
    print(f"  expected values for the agent run to reproduce:")
    width = max(len(k) for k in expected)
    for k, v in expected.items():
        print(f"    {k:<{width}}  {v:12.4g}")
    print()
    print(f"  brief the agent with:")
    print(f"    plan: lane_b/{'fuel' if cell['objective']=='fuel' else 'cost'}_mdo/plan.yaml")
    print(f"    overrides: mission_range_NM={cell['range_nm']}, "
          f"battery_specific_energy={cell['spec_e']}")
    return 0


def cmd_check(cell: dict, result_path: Path) -> int:
    expected = _expected_for(cell)
    tol_pct = float(cell.get("tol_pct", 5.0))
    if not result_path.exists():
        raise SystemExit(f"result JSON not found: {result_path}")
    actual = json.loads(result_path.read_text())

    keys = sorted(set(expected) & set(actual))
    if not keys:
        raise SystemExit(
            f"result JSON has no overlap with expected keys.\n"
            f"  expected keys: {sorted(expected)}\n"
            f"  actual keys  : {sorted(actual)}")

    width = max(len(k) for k in keys)
    print(f"\nLane C check -- cell {cell['id']}  (tol +/- {tol_pct:.1f}%)\n")
    print(f"  {'key':<{width}}  {'expected':>12s}  {'actual':>12s}  {'rel_err':>9s}  pass?")
    print("  " + "-" * (width + 50))
    n_pass = 0
    for k in keys:
        e, a = float(expected[k]), float(actual[k])
        rel = abs(a - e) / max(abs(e), 1e-30) * 100.0
        ok = rel <= tol_pct
        if ok:
            n_pass += 1
        print(f"  {k:<{width}}  {e:>12.4g}  {a:>12.4g}  {rel:>8.2f}%  {'OK' if ok else 'FAIL'}")
    print()
    print(f"  pass rate: {n_pass}/{len(keys)}")
    return 0 if n_pass == len(keys) else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cell", required=True,
                   help="cell id from cells.yaml (e.g. paper-fuel-500-250)")
    p.add_argument("--mode", choices=["baseline", "check"], default="baseline")
    p.add_argument("--result", type=Path, default=None,
                   help="Lane C result JSON (required for --mode check)")
    args = p.parse_args()

    cell = _load_cell(args.cell)
    if args.mode == "baseline":
        return cmd_baseline(cell)
    if args.result is None:
        raise SystemExit("--mode check requires --result <path>")
    return cmd_check(cell, args.result)


if __name__ == "__main__":
    sys.exit(main())
