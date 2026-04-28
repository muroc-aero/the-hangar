"""Sweep driver for Adler 2022a Figs 7, 9, 10, 11, 12, 13.

Runs one MDO per (mission_range_nmi, method) cell and writes results to
results/sweep_<grid>.csv plus per-design spanwise data to
results/per_design/{range}/{method}.json.

Usage:
    uv run python packages/omd/demos/adler_2022a/sweep.py \
        --grid coarse --workers 4
    uv run python packages/omd/demos/adler_2022a/sweep.py \
        --grid full --methods mission_based --workers 4
    uv run python packages/omd/demos/adler_2022a/sweep.py \
        --grid coarse --methods mission_based --fine-mesh
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
PER_DESIGN_DIR = RESULTS_DIR / "per_design"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
PER_DESIGN_DIR.mkdir(parents=True, exist_ok=True)

METHOD_PLANS = {
    "single_point":            DEMO_DIR / "lane_b" / "single_point" / "plan.yaml",
    "multipoint":              DEMO_DIR / "lane_b" / "multipoint" / "plan.yaml",
    "mission_based":           DEMO_DIR / "lane_b" / "mission_based" / "plan.yaml",
    "single_point_plus_climb": DEMO_DIR / "lane_b" / "single_point_plus_climb" / "plan.yaml",
}
METHODS = list(METHOD_PLANS.keys())

# CSV columns. Stable contract for downstream plotting.
COLUMNS = [
    "mission_range_nmi", "method",
    "converged", "run_id",
    "fuel_burn_kg",          # Bréguet objective (Bréguet methods) or
                             # mission-integrated descent.fuel_used_final
                             # (mission-based)
    "climb_fuel_kg",         # mission_based only; NaN for Bréguet methods
    "cruise_fuel_kg",        # mission_based only
    "descent_fuel_kg",       # mission_based only
    "W_wing_maneuver_kg",
    "AR", "taper", "c4sweep_deg",
    "wall_time_s", "error",
]

# DV / output keys we read back from the recorder for warm-starting +
# the per-design JSON dump.
_OUTPUT_KEYS = [
    "ac|geom|wing|AR",
    "ac|geom|wing|taper",
    "ac|geom|wing|c4sweep",
    "ac|geom|wing|twist",
    "ac|geom|wing|toverc",
    "ac|geom|wing|skin_thickness",
    "ac|geom|wing|spar_thickness",
    "ac|weights|MTOW",
    "ac|weights|orig_W_wing",
    "W_wing_maneuver",
    "failure_maneuver",
    "2_5g_KS_failure",
    "breguet.fuel_burn_kg",
    "descent.fuel_used_final",
    # mission-based per-phase fuel breakdown for Fig 9
    "climb.fuel_used_final",
    "cruise.fuel_used_final",
    # cruise/maneuver lift distributions for Fig 11 (paths differ
    # between Bréguet and mission_based variants; pull all that exist)
    "cruise_0.drag.aero_surrogate.CL",
    "cruise_0.drag.aero_surrogate.CD",
    # 2.5 g maneuver panel forces for Fig 11. Shape (nx-1, ny-1, 3);
    # only this path emits real per-panel lift (cruise drag goes through
    # the AerostructDragPolar Kriging surrogate, which does not).
    "maneuver.aerostructural_maneuver.aerostruct_point.coupled.aero_states.wing_sec_forces",
]

# Paper coarse: 4 representative ranges from Tables 5-7
COARSE_RANGES = np.array([300.0, 900.0, 1500.0, 2900.0])
# Paper full: 14 ranges per Figure 7 abscissa
FULL_RANGES = np.arange(300.0, 3000.0, 200.0)


def _parse_grid(spec: str) -> np.ndarray:
    if spec == "coarse":
        return COARSE_RANGES.copy()
    if spec == "full":
        return FULL_RANGES.copy()
    # comma-separated explicit list
    return np.array([float(v) for v in spec.split(",")])


def _nan_row(rng: float, method: str, error: str, wall: float) -> dict:
    row = {c: np.nan for c in COLUMNS}
    row["mission_range_nmi"] = float(rng)
    row["method"] = method
    row["converged"] = False
    row["run_id"] = ""
    row["error"] = error[:240]
    row["wall_time_s"] = wall
    return row


# Scalar warm-start fields: (csv column, DV name in plan).
_WARM_FIELDS = [
    ("AR",          "ac|geom|wing|AR"),
    ("taper",       "ac|geom|wing|taper"),
    ("c4sweep_deg", "ac|geom|wing|c4sweep"),
]

# Vector warm-start fields: (per-design JSON key, DV name in plan).
# Read from results/per_design/{rng}/{method}.json (the sweep CSV is
# scalar-only by design). The 11 vector DV elements are the most
# expensive to discover from scratch and most worth warm-starting.
_WARM_VECTOR_FIELDS = [
    ("twist_cp_deg", "ac|geom|wing|twist"),
    ("toverc_cp",    "ac|geom|wing|toverc"),
    ("skin_cp_m",    "ac|geom|wing|skin_thickness"),
    ("spar_cp_m",    "ac|geom|wing|spar_thickness"),
]


def _read_warm_vectors(mission_range: float, method: str) -> dict:
    """Pull vector DV warm-starts from the nearest converged neighbour's
    per-design JSON dump. Returns a dict of {dv_name: list_of_floats}
    for each vector DV that has a non-null entry in the JSON. Caller is
    responsible for selecting the neighbour range.
    """
    path = PER_DESIGN_DIR / f"{int(mission_range)}" / f"{method}.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict = {}
    for json_key, dv_name in _WARM_VECTOR_FIELDS:
        v = data.get(json_key)
        if isinstance(v, list) and len(v) > 0:
            out[json_key] = v
    return out


def _patch_plan(
    plan: dict,
    mission_range: float,
    method: str,
    fine_mesh: bool,
    warm_dvs: dict | None,
) -> dict:
    """Deep-copy the base plan and substitute mission range + mesh."""
    import copy
    p = copy.deepcopy(plan)
    for comp in p.get("components", []):
        cfg = comp.setdefault("config", {})
        ctype = comp.get("type", "")
        if ctype == "ocp/BasicMission":
            cfg.setdefault("mission_params", {})["mission_range_NM"] = float(mission_range)
        elif ctype == "oas/AerostructBreguet":
            cfg["mission_range_nmi"] = float(mission_range)
        # Fine-mesh override
        if fine_mesh:
            grid = cfg.get("surface_grid")
            if grid:
                grid["num_y"] = 27
                grid["num_x"] = 3
            mn = cfg.get("maneuver")
            if mn:
                mn["num_y"] = 27
                mn["num_x"] = 3
            slots = cfg.get("slots")
            if slots:
                for slot_name, slot_cfg in slots.items():
                    if isinstance(slot_cfg, dict):
                        sc = slot_cfg.get("config", {})
                        if "num_y" in sc:
                            sc["num_y"] = 27
                            sc["num_x"] = 3
    if warm_dvs:
        for dv in p.get("design_variables", []):
            for col, name in _WARM_FIELDS:
                if dv["name"] == name and col in warm_dvs and not isinstance(dv.get("initial"), list):
                    dv["initial"] = float(warm_dvs[col])
            # Vector DV warm-starts come keyed by the per-design JSON key.
            for json_key, name in _WARM_VECTOR_FIELDS:
                if dv["name"] == name and json_key in warm_dvs:
                    val = warm_dvs[json_key]
                    if isinstance(val, list) and len(val) > 0:
                        dv["initial"] = [float(x) for x in val]
    p.setdefault("metadata", {})
    p["metadata"]["id"] = (
        f"{p['metadata'].get('id', 'adler')}-r{int(mission_range)}-{method}"
        + ("-fine" if fine_mesh else "")
    )
    p["metadata"].pop("content_hash", None)
    return p


def _read_final_values(run_id: str) -> dict:
    """Pull converged outputs from the OpenMDAO recorder's `final` case."""
    from openmdao.api import CaseReader

    sql_path = (
        Path(os.environ.get("OMD_DATA_ROOT", "hangar_data/omd"))
        / "recordings" / f"{run_id}.sql"
    )
    if not sql_path.exists():
        return {}
    cr = CaseReader(str(sql_path))
    out: dict[str, object] = {}
    cases = cr.list_cases("problem", out_stream=None) or []
    if "final" in cases:
        final = cr.get_case("final")
        for k in _OUTPUT_KEYS:
            if k in final.outputs:
                arr = np.asarray(final.outputs[k])
                if arr.size == 1:
                    out[k] = float(arr.flatten()[0])
                else:
                    out[k] = arr.tolist()
    return out


def _persist_per_design(
    mission_range: float, method: str, values: dict,
) -> None:
    """Write the spanwise wing arrays to a JSON file for the
    per-design figures (10, 11)."""
    rng_dir = PER_DESIGN_DIR / f"{int(mission_range)}"
    rng_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mission_range_nmi": float(mission_range),
        "method": method,
        "AR": values.get("ac|geom|wing|AR"),
        "taper": values.get("ac|geom|wing|taper"),
        "c4sweep_deg": values.get("ac|geom|wing|c4sweep"),
        "twist_cp_deg": values.get("ac|geom|wing|twist"),
        "toverc_cp": values.get("ac|geom|wing|toverc"),
        "skin_cp_m": values.get("ac|geom|wing|skin_thickness"),
        "spar_cp_m": values.get("ac|geom|wing|spar_thickness"),
        "W_wing_kg": values.get("W_wing_maneuver"),
        # 2.5 g maneuver wing_sec_forces, shape (nx-1, ny-1, 3); list-of-list-of-list
        # for JSON. Used by plotting.py:fig11.
        "lift_dist_maneuver_N": values.get(
            "maneuver.aerostructural_maneuver.aerostruct_point.coupled."
            "aero_states.wing_sec_forces"
        ),
    }
    with open(rng_dir / f"{method}.json", "w") as f:
        json.dump(payload, f, indent=2)


def _worker_init() -> None:
    """Worker init for the outer mp.Pool: cap each worker's BLAS thread
    count to 1 and shim multiprocessing.Pool so that anything inside the
    worker (notably OAS's AerostructDragPolar.compute_training_data) that
    calls `multiprocessing.Pool()` with no args defaults to 1 process
    instead of os.cpu_count(). Without this, an N-worker outer sweep
    fans out to N x cpu_count processes and silently dies.
    """
    import multiprocessing
    import multiprocessing.pool as _mp_pool

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

    _OriginalPool = _mp_pool.Pool

    class _SingleProcessPool(_OriginalPool):
        def __init__(self, processes=None, *args, **kwargs):
            if processes is None:
                processes = 1
            super().__init__(processes, *args, **kwargs)

    multiprocessing.Pool = _SingleProcessPool
    _mp_pool.Pool = _SingleProcessPool


def _run_one(args: tuple) -> dict:
    mission_range, method, fine_mesh, warm_dvs = args
    base_plan_path = METHOD_PLANS[method]
    t0 = time.perf_counter()
    try:
        with open(base_plan_path) as f:
            base_plan = yaml.safe_load(f)
        patched = _patch_plan(base_plan, mission_range, method, fine_mesh, warm_dvs)

        with tempfile.TemporaryDirectory() as td:
            cell_path = Path(td) / "plan.yaml"
            with open(cell_path, "w") as f:
                yaml.safe_dump(patched, f)
            from hangar.omd.run import run_plan
            result = run_plan(cell_path, mode="optimize")

        wall = time.perf_counter() - t0
        run_id = result.get("run_id") or ""
        status = result.get("status", "failed")
        converged = status == "converged"
        values = _read_final_values(run_id) if run_id else {}
        # Methods produce different fuel-burn outputs:
        if method == "mission_based":
            fuel = float(values.get("descent.fuel_used_final", np.nan))
        else:
            fuel = float(values.get("breguet.fuel_burn_kg", np.nan))

        row = {c: np.nan for c in COLUMNS}
        row.update({
            "mission_range_nmi": float(mission_range),
            "method": method,
            "converged": bool(converged),
            "run_id": run_id,
            "fuel_burn_kg": fuel,
            # Per-phase fuel for fig9. Only mission_based produces these
            # paths; Bréguet methods carry NaN.
            "climb_fuel_kg": values.get("climb.fuel_used_final", np.nan),
            "cruise_fuel_kg": values.get("cruise.fuel_used_final", np.nan),
            "descent_fuel_kg": values.get("descent.fuel_used_final", np.nan),
            "W_wing_maneuver_kg": values.get("W_wing_maneuver", np.nan),
            "AR": values.get("ac|geom|wing|AR", np.nan),
            "taper": values.get("ac|geom|wing|taper", np.nan),
            "c4sweep_deg": values.get("ac|geom|wing|c4sweep", np.nan),
            "wall_time_s": wall,
            "error": "" if converged else status,
        })
        if converged:
            _persist_per_design(mission_range, method, values)
        return row
    except Exception as exc:
        traceback.print_exc()
        return _nan_row(
            mission_range, method,
            f"{type(exc).__name__}: {exc}",
            time.perf_counter() - t0,
        )


def _checkpoint_path(grid: str, fine_mesh: bool) -> Path:
    suffix = "_fine_mesh" if fine_mesh else ""
    return RESULTS_DIR / f"sweep_{grid}{suffix}.csv"


def _load_checkpoint(path: Path) -> set[tuple[float, str]]:
    done: set[tuple[float, str]] = set()
    if not path.exists():
        return done
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                done.add((float(row["mission_range_nmi"]), row["method"]))
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


def _warm_for(
    warm_df: "pd.DataFrame | None",
    mission_range: float,
    method: str,
) -> dict | None:
    """Return the closest converged neighbour's DVs for warm-starting.

    Mixes scalars (from the sweep CSV) and vectors (from the matching
    per-design JSON). Falls back silently to the factory IVC for any
    individual DV that is absent.
    """
    if warm_df is None:
        return None
    ok = warm_df[warm_df["converged"].astype(str).str.lower() == "true"]
    same_method = ok[ok["method"] == method]
    if len(same_method) == 0:
        return None
    d = np.abs(same_method["mission_range_nmi"].to_numpy() - mission_range)
    closest = same_method.iloc[int(np.argmin(d))]
    out: dict = {col: float(closest[col]) for col, _ in _WARM_FIELDS if col in closest}
    out.update(_read_warm_vectors(float(closest["mission_range_nmi"]), method))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--grid", default="coarse",
                   help="'coarse' (4 ranges), 'full' (14 ranges), or comma-separated list")
    p.add_argument("--methods", default=",".join(METHODS),
                   help="Comma-separated subset of methods")
    p.add_argument("--workers", type=int,
                   default=max(1, (os.cpu_count() or 4) // 2))
    p.add_argument("--fine-mesh", action="store_true",
                   help="Use 27x3 panel surface grid (paper-spec)")
    p.add_argument("--resume", action="store_true",
                   help="Skip cells already present in checkpoint CSV")
    p.add_argument("--fresh", action="store_true",
                   help="Delete checkpoint and start over")
    p.add_argument("--warm-from", type=str, default=None,
                   help="Path to a CSV from a prior sweep whose DVs warm-start each cell")
    args = p.parse_args()

    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    bad = [m for m in methods if m not in METHODS]
    if bad:
        print(f"Unknown methods: {bad}; available: {METHODS}", file=sys.stderr)
        return 2

    ranges = _parse_grid(args.grid)
    cells = [(r, m) for r in ranges for m in methods]

    ckpt = _checkpoint_path(args.grid, args.fine_mesh)
    if args.fresh and ckpt.exists():
        ckpt.unlink()
    done = _load_checkpoint(ckpt) if args.resume else set()
    pending = [c for c in cells if c not in done]
    print(f"Running {len(pending)} cells "
          f"({len(done)} already in {ckpt.name}) on {args.workers} workers.")

    warm_df = pd.read_csv(args.warm_from) if args.warm_from else None
    if warm_df is not None:
        print(f"Warm-starting from {Path(args.warm_from).name} ({len(warm_df)} cells)")

    work = [
        (rng, mth, args.fine_mesh, _warm_for(warm_df, rng, mth))
        for (rng, mth) in pending
    ]

    started = time.perf_counter()
    failures = 0
    if args.workers == 1:
        iterator = map(_run_one, work)
    else:
        pool = mp.Pool(args.workers, initializer=_worker_init)
        iterator = pool.imap_unordered(_run_one, work)
    for i, row in enumerate(iterator, 1):
        _append_row(ckpt, row)
        status = "OK" if row["converged"] else f"FAIL ({row['error']})"
        elapsed = time.perf_counter() - started
        print(
            f"[{i}/{len(work)}] r={row['mission_range_nmi']:.0f}nm "
            f"{row['method']:<25}  {status}  "
            f"fuel={row['fuel_burn_kg']:.1f}kg  "
            f"wall={row['wall_time_s']:.1f}s  total={elapsed:.0f}s"
        )
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
