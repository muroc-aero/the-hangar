"""Sweep driver for Brelje 2018a Figs 5 & 6.

Runs one MDO per (design_range, spec_energy) grid cell and writes
results to results/{fig5,fig6}_grid.csv. Uses multiprocessing and
checkpointing so partial sweeps are recoverable.

Usage:
    uv run python packages/omd/demos/brelje_2018a/sweep.py \
        --objective fuel --grid 5x5 --workers 4
    uv run python ... --objective cost --grid 21x12 --workers 8
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

DEMO_DIR = Path(__file__).resolve().parent
RESULTS_DIR = DEMO_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

FUEL_PLAN = DEMO_DIR / "lane_b" / "fuel_mdo" / "plan.yaml"
COST_PLAN = DEMO_DIR / "lane_b" / "cost_mdo" / "plan.yaml"

# CSV columns. Keep stable so downstream plotting can rely on them.
COLUMNS = [
    "design_range_nm", "spec_energy_whkg",
    "converged", "run_id",
    "objective_value",
    "MTOW_kg", "MTOW_lb",
    "fuel_burn_kg", "fuel_burn_lb", "fuel_mileage_lb_per_nmi",
    "W_battery_kg", "S_ref_m2",
    "cruise_hybridization", "climb_hybridization", "descent_hybridization",
    "electric_percent",
    "engine_rating_hp", "motor_rating_hp", "generator_rating_hp",
    "MTOW_margin_lb", "rotate_range_ft", "Vstall_kn", "SOC_final",
    "doc_per_nmi",
    "wall_time_s", "error",
]


def _parse_grid(spec: str) -> tuple[np.ndarray, np.ndarray]:
    """Parse ``--grid NxM`` into range and spec_energy linspaces over [300, 800]."""
    n_range, n_energy = spec.lower().split("x")
    ranges = np.linspace(300.0, 800.0, int(n_range))
    energies = np.linspace(300.0, 800.0, int(n_energy))
    return ranges, energies


def _nan_row(design_range: float, spec_energy: float, error: str,
             wall_time: float) -> dict:
    row = {c: np.nan for c in COLUMNS}
    row["design_range_nm"] = design_range
    row["spec_energy_whkg"] = spec_energy
    row["converged"] = False
    row["run_id"] = ""
    row["error"] = error[:240]
    row["wall_time_s"] = wall_time
    return row


_WARM_FIELDS: dict[str, tuple[str, str | None]] = {
    # csv column               -> (DV name, units)
    "MTOW_kg":                 ("ac|weights|MTOW", "kg"),
    "S_ref_m2":                ("ac|geom|wing|S_ref", "m**2"),
    "engine_rating_hp":        ("ac|propulsion|engine|rating", "hp"),
    "motor_rating_hp":         ("ac|propulsion|motor|rating", "hp"),
    "generator_rating_hp":     ("ac|propulsion|generator|rating", "hp"),
    "W_battery_kg":            ("ac|weights|W_battery", "kg"),
    "cruise_hybridization":    ("cruise.hybridization", None),
    "climb_hybridization":     ("climb.hybridization", None),
    "descent_hybridization":   ("descent.hybridization", None),
}


def _patch_plan(
    plan: dict,
    design_range: float,
    spec_energy: float,
    warm_dvs: dict | None = None,
) -> dict:
    """Return a deep-copied plan with this cell's range/spec_energy, and
    optional per-DV ``initial:`` warm starts applied via the omd
    plan-level ``design_variables[].initial`` field (materializer
    applies after prob.setup())."""
    import copy
    p = copy.deepcopy(plan)
    for comp in p.get("components", []):
        if comp.get("type") == "ocp/FullMission":
            mp = comp.setdefault("config", {}).setdefault("mission_params", {})
            mp["mission_range_NM"] = float(design_range)
            mp["battery_specific_energy"] = float(spec_energy)
            po = comp["config"].setdefault("propulsion_overrides", {})
            po["battery_specific_energy"] = float(spec_energy)
    if warm_dvs:
        for dv in p.get("design_variables", []):
            for col, (dv_name, _units) in _WARM_FIELDS.items():
                if dv["name"] == dv_name and col in warm_dvs:
                    dv["initial"] = float(warm_dvs[col])
    # Bump version so caches do not collide; id gets a suffix per cell
    p.setdefault("metadata", {})
    p["metadata"]["id"] = f"{p['metadata'].get('id', 'brelje')}-r{int(design_range)}-e{int(spec_energy)}"
    p["metadata"].pop("content_hash", None)
    return p


def _warm_dvs_for_cell(
    warm_df: "pd.DataFrame | None",
    design_range: float,
    spec_energy: float,
) -> dict | None:
    """Look up the matching cell in a warm-start CSV; fall back to the
    nearest converged cell if exact match is missing.  Returns a dict of
    DV column -> value (keys from _WARM_FIELDS) or None."""
    if warm_df is None:
        return None
    import pandas as pd
    ok = warm_df[warm_df["converged"].astype(str).str.lower() == "true"]
    if len(ok) == 0:
        return None
    exact = ok[(ok.design_range_nm == design_range) & (ok.spec_energy_whkg == spec_energy)]
    if len(exact) == 0:
        span = 500.0
        d = np.hypot(
            (ok["design_range_nm"].to_numpy() - design_range) / span,
            (ok["spec_energy_whkg"].to_numpy() - spec_energy) / span,
        )
        exact = ok.iloc[[int(np.argmin(d))]]
    neigh = exact.iloc[0]
    return {col: float(neigh[col]) for col in _WARM_FIELDS if col in neigh}


def _run_one(args: tuple) -> dict:
    """Worker: run one MDO cell."""
    base_plan_path, design_range, spec_energy, warm_dvs = args
    t0 = time.perf_counter()
    try:
        with open(base_plan_path) as f:
            base_plan = yaml.safe_load(f)
        patched = _patch_plan(base_plan, design_range, spec_energy, warm_dvs)

        with tempfile.TemporaryDirectory() as td:
            cell_path = Path(td) / "plan.yaml"
            with open(cell_path, "w") as f:
                yaml.safe_dump(patched, f)

            from hangar.omd.run import run_plan
            result = run_plan(cell_path, mode="optimize")

        wall = time.perf_counter() - t0
        summary = result.get("summary", {}) or {}
        run_id = result.get("run_id") or ""
        status = result.get("status", "failed")
        converged = status == "converged"

        # Pull final values from the recorder via CaseReader so every
        # cell reports the same column set regardless of omd's summary shape.
        values = _read_final_values(run_id) if run_id else {}

        fuel_kg = float(values.get("descent.fuel_used_final", np.nan))
        fuel_lb = fuel_kg * 2.20462 if np.isfinite(fuel_kg) else np.nan
        row = {c: np.nan for c in COLUMNS}
        row.update({
            "design_range_nm": float(design_range),
            "spec_energy_whkg": float(spec_energy),
            "converged": bool(converged),
            "run_id": run_id,
            "objective_value": values.get("__objective__", np.nan),
            "MTOW_kg": values.get("ac|weights|MTOW", np.nan),
            "MTOW_lb": values.get("ac|weights|MTOW", np.nan) * 2.20462,
            "fuel_burn_kg": fuel_kg,
            "fuel_burn_lb": fuel_lb,
            "fuel_mileage_lb_per_nmi": fuel_lb / design_range if np.isfinite(fuel_lb) else np.nan,
            "W_battery_kg": values.get("ac|weights|W_battery", np.nan),
            "S_ref_m2": values.get("ac|geom|wing|S_ref", np.nan),
            "cruise_hybridization": values.get("cruise.hybridization", np.nan),
            "climb_hybridization": values.get("climb.hybridization", np.nan),
            "descent_hybridization": values.get("descent.hybridization", np.nan),
            "electric_percent": 100.0 * values.get("cruise.hybridization", np.nan),
            "engine_rating_hp": values.get("ac|propulsion|engine|rating", np.nan),
            "motor_rating_hp": values.get("ac|propulsion|motor|rating", np.nan),
            "generator_rating_hp": values.get("ac|propulsion|generator|rating", np.nan),
            "MTOW_margin_lb": values.get("margins.MTOW_margin", np.nan),
            "rotate_range_ft": values.get("rotate.range_final", np.nan),
            "Vstall_kn": values.get("v0v1.Vstall_eas", np.nan),
            "SOC_final": values.get("descent.propmodel.batt1.SOC_final", np.nan),
            "doc_per_nmi": values.get("doc_per_nmi", np.nan),
            "wall_time_s": wall,
            "error": "" if converged else status,
        })
        return row
    except Exception as exc:
        return _nan_row(design_range, spec_energy,
                        f"{type(exc).__name__}: {exc}",
                        time.perf_counter() - t0)


_OUTPUT_KEYS = [
    "ac|weights|MTOW", "ac|weights|W_battery", "ac|geom|wing|S_ref",
    "ac|propulsion|engine|rating", "ac|propulsion|motor|rating",
    "ac|propulsion|generator|rating",
    "cruise.hybridization", "climb.hybridization", "descent.hybridization",
    "margins.MTOW_margin", "rotate.range_final", "v0v1.Vstall_eas",
    "descent.propmodel.batt1.SOC_final",
    "descent.fuel_used_final", "mixed_objective", "doc_per_nmi",
]


def _read_final_values(run_id: str) -> dict:
    """Extract converged outputs from the recorder's `final` problem case.

    The driver recorder tracks only DVs/objs/constraints; the post-driver
    ``final`` case snapshots all promoted outputs including
    ``descent.fuel_used_final`` (not declared as a DV/constraint here).
    """
    from openmdao.api import CaseReader

    sql_path = Path(os.environ.get("OMD_DATA_ROOT", "hangar_data/omd")) / "recordings" / f"{run_id}.sql"
    if not sql_path.exists():
        return {}
    cr = CaseReader(str(sql_path))

    out: dict[str, float] = {}
    if "final" in (cr.list_cases("problem", out_stream=None) or []):
        final = cr.get_case("final")
        for k in _OUTPUT_KEYS:
            if k in final.outputs:
                out[k] = float(np.asarray(final.outputs[k]).flatten()[0])
        if "mixed_objective" in out:
            out["__objective__"] = out["mixed_objective"]
        elif "doc_per_nmi" in out:
            out["__objective__"] = out["doc_per_nmi"]
    return out


def _checkpoint_path(objective: str) -> Path:
    return RESULTS_DIR / f"{'fig5' if objective == 'fuel' else 'fig6'}_grid.csv"


def _load_checkpoint(path: Path) -> set[tuple[float, float]]:
    """Return set of (range, energy) cells already in the CSV."""
    done: set[tuple[float, float]] = set()
    if not path.exists():
        return done
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                done.add((float(row["design_range_nm"]), float(row["spec_energy_whkg"])))
            except (KeyError, ValueError):
                continue
    return done


def _append_row(path: Path, row: dict) -> None:
    new_file = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({c: row.get(c, "") for c in COLUMNS})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--objective", choices=["fuel", "cost"], default="fuel")
    p.add_argument("--grid", default="5x5", help="NxM, e.g. 5x5 or 21x12")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    p.add_argument("--resume", action="store_true",
                   help="Skip cells already present in the checkpoint CSV.")
    p.add_argument("--fresh", action="store_true",
                   help="Delete checkpoint and start over.")
    p.add_argument("--warm-from", type=str, default=None,
                   help="Path to a CSV from a prior sweep whose converged "
                        "DVs will warm-start each cell via the plan-level "
                        "`design_variables[].initial` mechanism.  Use to "
                        "seed the cost sweep from the fuel sweep so it "
                        "escapes local minima.")
    args = p.parse_args()

    base_plan = FUEL_PLAN if args.objective == "fuel" else COST_PLAN
    if not base_plan.exists():
        print(f"Base plan not found: {base_plan}")
        if args.objective == "cost":
            print("Cost plan lands in Stage 4.  Run fuel objective first.")
        return 2

    ranges, energies = _parse_grid(args.grid)
    cells = [(r, e) for r in ranges for e in energies]

    ckpt = _checkpoint_path(args.objective)
    if args.fresh and ckpt.exists():
        ckpt.unlink()
    done = _load_checkpoint(ckpt) if args.resume else set()
    pending = [c for c in cells if (c[0], c[1]) not in done]
    print(f"Running {len(pending)} cells ({len(done)} already in {ckpt.name}) "
          f"on {args.workers} workers.")

    warm_df = pd.read_csv(args.warm_from) if args.warm_from else None
    if warm_df is not None:
        print(f"Warm-starting DVs from {Path(args.warm_from).name} "
              f"({len(warm_df)} cells).")
    work = [
        (base_plan, r, e, _warm_dvs_for_cell(warm_df, r, e))
        for (r, e) in pending
    ]
    started = time.perf_counter()
    failures = 0

    if args.workers == 1:
        iterator = map(_run_one, work)
    else:
        pool = mp.Pool(args.workers)
        iterator = pool.imap_unordered(_run_one, work)

    for i, row in enumerate(iterator, 1):
        _append_row(ckpt, row)
        status = "OK" if row["converged"] else f"FAIL ({row['error']})"
        elapsed = time.perf_counter() - started
        print(f"[{i}/{len(work)}] r={row['design_range_nm']:.0f} "
              f"e={row['spec_energy_whkg']:.0f}  {status}  "
              f"obj={row['objective_value']:.3f}  "
              f"wall={row['wall_time_s']:.1f}s  total={elapsed:.0f}s")
        if not row["converged"]:
            failures += 1

    if args.workers != 1:
        pool.close()
        pool.join()

    print(f"\nDone. {len(pending) - failures}/{len(pending)} converged, {failures} failures.")
    print(f"Results -> {ckpt}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
