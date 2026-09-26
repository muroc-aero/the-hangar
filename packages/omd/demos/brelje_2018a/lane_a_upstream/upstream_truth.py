"""Lane A (upstream): Brelje 2018a MDO on OpenConcept's own HybridTwin model.

This is the *truth* lane for the Brelje statistics harness. It does not
touch any hangar code: the aircraft model, mission, solver settings and
paper overrides come straight from ``openconcept.examples.HybridTwin``
(``ElectricTwinAnalysisGroup``, ``set_values``), and the DVs /
constraints / objective are the verbatim ``run_type == "optimization"``
block from ``HybridTwin.py``'s ``__main__`` (which cannot be imported,
so it is transcribed in :func:`add_mdo_problem`).

Two things are added on top of upstream, both documented:

1. **Cost model.** Upstream ships no DOC model, but Fig 5 plots trip
   DOC and Fig 6 minimises it. :class:`HybridTwinWithCost` subclasses
   the upstream group and appends the paper's Section IV.D cost model
   (the same coefficients as the omd factory's ``include_cost_model``;
   whether they reproduce the paper is exactly what
   ``stats/collect_stats.py`` measures against the digitized DOC panel).
   It is an output-only addition: it cannot move the fuel optimum.
2. **Multistart.** Upstream's sweep is "not tested" and single-start.
   Each cell runs the upstream start (template values, hybridization 0)
   plus the ``low`` / ``high`` brackets from ``pipeline/sweep.py``, and
   keeps the best *feasible* optimum. Every start is logged, so the
   start-sensitivity of the problem is itself a statistic.

Usage:
    # one cell (prints JSON)
    uv run python .../lane_a_upstream/upstream_truth.py cell \\
        --range 500 --spec-energy 450 --objective fuel

    # full paper grid (21 x 12), resumable, checkpointed per cell
    uv run python .../lane_a_upstream/upstream_truth.py grid \\
        --objective fuel --grid paper --workers 4
    uv run python ... grid --objective cost --grid paper --workers 4 --resume

Output: ``results/lane_a_upstream/fig{5,6}_<grid>.csv`` (same column
names as ``pipeline/sweep.py`` where they overlap) and
``fig{5,6}_<grid>_starts.csv`` (one row per start).
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np

DEMO_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = DEMO_DIR / "results" / "lane_a_upstream"

NUM_NODES = 11  # HybridTwin hard-codes nn = 11 in ElectricTwinAnalysisGroup

# Grids. "paper" is the 21 x 12 grid read off the published figures'
# pcolormesh cells (paper_ref/digitize_paper_figs.py); "demo" is the
# 11 x 12 grid of results/fig{5,6}_grid.csv; "anchors" is the 500 nmi
# column the README/cells.yaml Table-4 values refer to.
GRIDS = {
    "paper": (np.arange(300.0, 800.0 + 1e-9, 25.0), np.arange(250.0, 800.0 + 1e-9, 50.0)),
    "demo": (np.arange(300.0, 800.0 + 1e-9, 50.0), np.arange(250.0, 800.0 + 1e-9, 50.0)),
    "anchors": (np.array([500.0]), np.array([250.0, 450.0, 500.0, 750.0])),
}

# Same brackets as pipeline/sweep.py _MULTISTART_PRESETS; "upstream" is
# HybridTwin's own starting point (no overrides).
START_PRESETS: dict[str, dict[str, float]] = {
    "upstream": {},
    "low": {
        "cruise.hybridization": 0.05,
        "climb.hybridization": 0.05,
        "descent.hybridization": 0.05,
        "ac|weights|W_battery": 100.0,
        "ac|propulsion|motor|rating": 500.0,
    },
    "high": {
        "cruise.hybridization": 0.95,
        "climb.hybridization": 0.95,
        "descent.hybridization": 0.95,
        "ac|weights|W_battery": 2000.0,
        "ac|propulsion|motor|rating": 1500.0,
    },
}

# Units used for the preset values above (upstream's DV units).
_PRESET_UNITS = {
    "ac|weights|W_battery": "kg",
    "ac|propulsion|motor|rating": "hp",
}

COLUMNS = [
    "design_range_nm", "spec_energy_whkg", "objective",
    "converged", "feasible", "start_name", "starts_tried",
    "objective_value", "mixed_objective_kg", "doc_per_nmi", "trip_doc_usd",
    "MTOW_kg", "MTOW_lb", "fuel_burn_kg", "fuel_burn_lb",
    "fuel_mileage_lb_per_nmi", "W_battery_kg", "W_battery_lb",
    "S_ref_m2", "S_ref_ft2",
    "cruise_hybridization", "climb_hybridization", "descent_hybridization",
    "electric_percent", "electric_energy_frac", "battery_energy_frac",
    "engine_rating_hp", "motor_rating_hp", "generator_rating_hp",
    "W_fuel_max_kg", "OEW_kg",
    "MTOW_margin_lb", "rotate_range_ft", "Vstall_kn", "SOC_final",
    "engineoutclimb_gamma", "max_constraint_violation",
    "n_iter", "wall_time_s", "error",
]

FUEL_LHV_MJ_PER_KG = 43.0  # Jet-A, for the energy-fraction diagnostic only


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _cost_group_class():
    import openmdao.api as om
    from openconcept.examples.HybridTwin import ElectricTwinAnalysisGroup

    class HybridTwinWithCost(ElectricTwinAnalysisGroup):
        """Upstream ElectricTwinAnalysisGroup + paper Sec. IV.D trip DOC.

        Coefficients (Brelje & Martins 2018 EATS, Sec. IV.D): fuel
        $2.50/gal, electricity $36/MWh (x 0.9 usable-energy factor),
        airframe $277/kg of OEW less propulsion weights (1.1 OEM
        premium), engine $775/shp, motor & generator $100/shp,
        battery $50/kg over 1500 cycles, 5 flights/day x 365 x 15 yr
        depreciation.
        """

        def setup(self):
            super().setup()
            trip = (
                "fuel_burn_kg * 0.8116883116883117"
                " + 0.9 * W_battery_kg * spec_energy_whkg * 0.0036 * 0.01"
                " + (277.0 * (OEW_kg - W_engines_kg - W_motors_kg - W_generator_kg)"
                "    + 775.0 * engine_hp + 100.0 * motor_hp + 100.0 * generator_hp)"
                " * 1.1 / 27375.0"
                " + 50.0 * W_battery_kg / 1500.0"
            )
            self.add_subsystem(
                "cost_model",
                om.ExecComp(
                    [f"trip_doc_usd = {trip}",
                     f"doc_per_nmi = ({trip}) / mission_range_nm"],
                    trip_doc_usd={"units": None, "val": 1.0},
                    doc_per_nmi={"units": None, "val": 1.0},
                    fuel_burn_kg={"units": "kg", "val": 100.0},
                    OEW_kg={"units": "kg", "val": 2500.0},
                    W_battery_kg={"units": "kg", "val": 500.0},
                    W_engines_kg={"units": "kg", "val": 200.0},
                    W_motors_kg={"units": "kg", "val": 100.0},
                    W_generator_kg={"units": "kg", "val": 100.0},
                    engine_hp={"units": "hp", "val": 750.0},
                    motor_hp={"units": "hp", "val": 500.0},
                    generator_hp={"units": "hp", "val": 500.0},
                    spec_energy_whkg={"units": "W*h/kg", "val": 450.0},
                    mission_range_nm={"units": "NM", "val": 500.0},
                ),
                promotes_outputs=["doc_per_nmi", "trip_doc_usd"],
            )
            self.connect("descent.fuel_used_final", "cost_model.fuel_burn_kg")
            self.connect("cruise.OEW", "cost_model.OEW_kg")
            self.connect("ac|weights|W_battery", "cost_model.W_battery_kg")
            self.connect("ac|propulsion|engine|rating", "cost_model.engine_hp")
            self.connect("ac|propulsion|motor|rating", "cost_model.motor_hp")
            self.connect("ac|propulsion|generator|rating", "cost_model.generator_hp")
            self.connect("ac|propulsion|battery|specific_energy", "cost_model.spec_energy_whkg")
            self.connect("mission_range", "cost_model.mission_range_nm")
            self.connect("cruise.propmodel.eng1.component_weight", "cost_model.W_engines_kg")
            self.connect("cruise.propmodel.motors_weight", "cost_model.W_motors_kg")
            self.connect("cruise.propmodel.gen1.component_weight", "cost_model.W_generator_kg")

    return HybridTwinWithCost


def configure_problem():
    """``HybridTwin.configure_problem`` with the cost-augmented group.

    Solver settings are copied from upstream verbatim (they live on the
    model instance, so the group swap has to repeat them).
    """
    from openmdao.api import DirectSolver, NewtonSolver, Problem

    prob = Problem(reports=False)
    prob.model = _cost_group_class()()
    prob.model.nonlinear_solver = NewtonSolver(iprint=1)
    prob.model.options["assembled_jac_type"] = "csc"
    prob.model.linear_solver = DirectSolver(assemble_jac=True)
    prob.model.nonlinear_solver.options["solve_subsystems"] = True
    prob.model.nonlinear_solver.options["maxiter"] = 10
    prob.model.nonlinear_solver.options["atol"] = 1e-10
    prob.model.nonlinear_solver.options["rtol"] = 1e-10
    return prob


def add_mdo_problem(prob, objective: str) -> None:
    """Verbatim from HybridTwin.py ``run_type == "optimization"``."""
    num_nodes = NUM_NODES
    m = prob.model
    m.add_design_var("ac|weights|MTOW", lower=4000, upper=5700)
    m.add_design_var("ac|geom|wing|S_ref", lower=15, upper=40)
    m.add_design_var("ac|propulsion|engine|rating", lower=1, upper=3000)
    m.add_design_var("ac|propulsion|motor|rating", lower=450, upper=3000)
    m.add_design_var("ac|propulsion|generator|rating", lower=1, upper=3000)
    m.add_design_var("ac|weights|W_battery", lower=20, upper=2250)
    m.add_design_var("ac|weights|W_fuel_max", lower=500, upper=3000)
    m.add_design_var("cruise.hybridization", lower=0.001, upper=0.999)
    m.add_design_var("climb.hybridization", lower=0.001, upper=0.999)
    m.add_design_var("descent.hybridization", lower=0.01, upper=1.0)

    m.add_constraint("margins.MTOW_margin", lower=0.0)
    m.add_constraint("rotate.range_final", upper=1357)
    m.add_constraint("v0v1.Vstall_eas", upper=42.0)
    m.add_constraint("descent.propmodel.batt1.SOC_final", lower=0.0)
    m.add_constraint("climb.throttle", upper=1.05 * np.ones(num_nodes))
    for phase in ("climb", "cruise", "descent"):
        for comp in ("eng1", "gen1", "batt1"):
            m.add_constraint(f"{phase}.propmodel.{comp}.component_sizing_margin",
                             upper=1.0 * np.ones(num_nodes))
    m.add_constraint("v0v1.propmodel.batt1.component_sizing_margin",
                     upper=1.0 * np.ones(num_nodes))
    m.add_constraint("engineoutclimb.gamma", lower=0.02)

    if objective == "fuel":
        m.add_objective("mixed_objective")
    elif objective == "cost":
        m.add_objective("doc_per_nmi")
    else:
        raise ValueError(f"unknown objective {objective!r}")


def _max_violation(prob) -> float:
    """Largest bound violation over all constraints and DVs (unscaled)."""
    worst = 0.0
    for name, meta in prob.model.get_constraints().items():
        val = np.atleast_1d(prob.driver.get_constraint_values(driver_scaling=False)[name])
        lo, hi, eq = meta.get("lower"), meta.get("upper"), meta.get("equals")
        scale = max(1.0, float(np.max(np.abs(val))))
        if eq is not None:
            worst = max(worst, float(np.max(np.abs(val - eq))) / scale)
        if lo is not None and np.all(np.asarray(lo) > -1e29):
            worst = max(worst, float(np.max(np.asarray(lo) - val)) / scale)
        if hi is not None and np.all(np.asarray(hi) < 1e29):
            worst = max(worst, float(np.max(val - np.asarray(hi))) / scale)
    return worst


def _electric_energy_frac(prob) -> float:
    """Battery share of the electrical energy the motors draw over
    climb + cruise + descent (Simpson-weighted per phase). A candidate
    reading of the paper's "degree of hybridization (electric percent)"
    panel, recorded next to cruise hybridization so the stats can say
    which one the paper plotted."""
    n = NUM_NODES
    w = np.ones(n)
    w[1:-1:2], w[2:-1:2] = 4.0, 2.0
    w /= 3.0 * (n - 1)
    batt = total = 0.0
    for ph in ("climb", "cruise", "descent"):
        dur = float(prob.get_val(f"{ph}.duration", units="s")[0])
        batt += dur * float(w @ prob.get_val(f"{ph}.propmodel.hybrid_split.power_out_A", units="kW"))
        total += dur * float(w @ prob.get_val(f"{ph}.propmodel.motors_elec_load", units="kW"))
    return batt / total if total > 0 else float("nan")


def _fill_outputs(prob, row: dict, design_range: float, spec_energy: float,
                  objective: str) -> None:
    """Read the reported outputs and feasibility off a run problem."""
    g = prob.get_val
    mtow_kg = float(g("ac|weights|MTOW", units="kg")[0])
    fuel_kg = float(g("descent.fuel_used_final", units="kg")[0])
    wb_kg = float(g("ac|weights|W_battery", units="kg")[0])
    soc = float(g("descent.propmodel.batt1.SOC_final")[0])
    e_batt_mj = (1.0 - soc) * wb_kg * spec_energy * 0.0036
    e_fuel_mj = fuel_kg * FUEL_LHV_MJ_PER_KG
    row.update(
        mixed_objective_kg=float(g("mixed_objective", units="kg")[0]),
        doc_per_nmi=float(g("doc_per_nmi")[0]),
        trip_doc_usd=float(g("trip_doc_usd")[0]),
        MTOW_kg=mtow_kg, MTOW_lb=mtow_kg * 2.2046226218,
        fuel_burn_kg=fuel_kg, fuel_burn_lb=fuel_kg * 2.2046226218,
        fuel_mileage_lb_per_nmi=fuel_kg * 2.2046226218 / design_range,
        W_battery_kg=wb_kg, W_battery_lb=wb_kg * 2.2046226218,
        S_ref_m2=float(g("ac|geom|wing|S_ref", units="m**2")[0]),
        S_ref_ft2=float(g("ac|geom|wing|S_ref", units="ft**2")[0]),
        cruise_hybridization=float(g("cruise.hybridization")[0]),
        climb_hybridization=float(g("climb.hybridization")[0]),
        descent_hybridization=float(g("descent.hybridization")[0]),
        battery_energy_frac=e_batt_mj / max(e_batt_mj + e_fuel_mj, 1e-12),
        engine_rating_hp=float(g("ac|propulsion|engine|rating", units="hp")[0]),
        motor_rating_hp=float(g("ac|propulsion|motor|rating", units="hp")[0]),
        generator_rating_hp=float(g("ac|propulsion|generator|rating", units="hp")[0]),
        W_fuel_max_kg=float(g("ac|weights|W_fuel_max", units="kg")[0]),
        OEW_kg=float(g("cruise.OEW", units="kg")[0]),
        MTOW_margin_lb=float(g("margins.MTOW_margin", units="lbm")[0]),
        rotate_range_ft=float(g("rotate.range_final", units="ft")[0]),
        Vstall_kn=float(g("v0v1.Vstall_eas", units="kn")[0]),
        SOC_final=soc,
        engineoutclimb_gamma=float(g("engineoutclimb.gamma")[0]),
    )
    row["electric_percent"] = 100.0 * row["cruise_hybridization"]
    row["electric_energy_frac"] = _electric_energy_frac(prob)
    row["objective_value"] = (row["mixed_objective_kg"] if objective == "fuel"
                              else row["doc_per_nmi"])
    viol = _max_violation(prob)
    row["max_constraint_violation"] = viol
    row["feasible"] = bool(viol < 1e-4 and np.isfinite(row["objective_value"]))


def run_start(design_range: float, spec_energy: float, objective: str,
              start: str, init: dict[str, float] | None = None) -> dict:
    """Run one MDO from one start; never raises."""
    from openmdao.api import ScipyOptimizeDriver
    from openconcept.examples.HybridTwin import set_values

    t0 = time.time()
    row = {c: np.nan for c in COLUMNS}
    row.update(design_range_nm=design_range, spec_energy_whkg=spec_energy,
               objective=objective, start_name=start, converged=False,
               feasible=False, error="", starts_tried=start)
    try:
        prob = configure_problem()
        add_mdo_problem(prob, objective)
        prob.driver = ScipyOptimizeDriver()  # upstream: SLSQP, tol 1e-6, maxiter 200
        prob.setup(check=False)
        set_values(prob, NUM_NODES, design_range, spec_energy)
        # a named preset, or an explicit warm start (DV -> value in
        # DESIGN_DVS units) for polish passes
        start_vals = init if init is not None else START_PRESETS[start]
        units = {**DESIGN_DVS, **_PRESET_UNITS}
        for name, val in start_vals.items():
            prob.set_val(name, val, units=units.get(name))

        sink = io.StringIO()
        with contextlib.redirect_stdout(sink):
            fail = prob.run_driver()
        row["converged"] = not fail
        row["n_iter"] = int(getattr(prob.driver, "iter_count", -1))

        _fill_outputs(prob, row, design_range, spec_energy, objective)
    except Exception as exc:  # noqa: BLE001 -- a failed start is data
        row["error"] = f"{type(exc).__name__}: {exc}"[:240]
        row["_tb"] = traceback.format_exc()[-2000:]
    row["wall_time_s"] = time.time() - t0
    return row


# DV name -> units the rescored design values are given in.
DESIGN_DVS = {
    "ac|weights|MTOW": "kg",
    "ac|geom|wing|S_ref": "m**2",
    "ac|propulsion|engine|rating": "hp",
    "ac|propulsion|motor|rating": "hp",
    "ac|propulsion|generator|rating": "hp",
    "ac|weights|W_battery": "kg",
    "ac|weights|W_fuel_max": "kg",
    "cruise.hybridization": None,
    "climb.hybridization": None,
    "descent.hybridization": None,
}


def rescore_design(design_range: float, spec_energy: float, objective: str,
                   dvs: dict[str, float]) -> dict:
    """Evaluate a design produced elsewhere (e.g. by an agent) in the
    upstream model: one ``run_model`` at the given DV values, no
    optimization. Returns the same columns as :func:`run_start`, with
    ``feasible`` judged by upstream's own constraints -- so a design is
    graded by what it does in the truth model, not by what its producer
    reported. Missing DVs keep upstream's template value and are listed
    in ``error``."""
    t0 = time.time()
    row = {c: np.nan for c in COLUMNS}
    row.update(design_range_nm=design_range, spec_energy_whkg=spec_energy,
               objective=objective, start_name="rescore", converged=True,
               feasible=False, error="", starts_tried="rescore")
    try:
        from openmdao.api import ScipyOptimizeDriver
        from openconcept.examples.HybridTwin import set_values

        prob = configure_problem()
        add_mdo_problem(prob, objective)
        prob.driver = ScipyOptimizeDriver()
        with contextlib.redirect_stderr(io.StringIO()):
            prob.setup(check=False)
        set_values(prob, NUM_NODES, design_range, spec_energy)
        missing = []
        for name, units in DESIGN_DVS.items():
            if dvs.get(name) is None:
                missing.append(name)
                continue
            prob.set_val(name, float(dvs[name]), units=units)
        import warnings
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prob.final_setup()
            prob.run_model()
        _fill_outputs(prob, row, design_range, spec_energy, objective)
        if missing:
            row["error"] = "missing DVs (template values used): " + ",".join(missing)
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"[:240]
    row["wall_time_s"] = time.time() - t0
    return row


def pick_best(rows: list[dict]) -> dict:
    """Best feasible optimum (converged preferred); else best anything."""
    def key(r):
        obj = r["objective_value"]
        obj = obj if isinstance(obj, float) and np.isfinite(obj) else np.inf
        return (not r["feasible"], not r["converged"], obj)
    best = dict(min(rows, key=key))
    best["starts_tried"] = ",".join(
        f"{r['start_name']}="
        + ("OK" if r["feasible"] and r["converged"] else
           "FEAS" if r["feasible"] else "FAIL")
        + (f"({r['objective_value']:.5g})"
           if isinstance(r["objective_value"], float) and np.isfinite(r["objective_value"]) else "")
        for r in rows)
    best["wall_time_s"] = sum(r["wall_time_s"] for r in rows)
    return best


# ---------------------------------------------------------------------------
# Grid driver
# ---------------------------------------------------------------------------

def _worker(args):
    # Newton/OpenMDAO chatter goes to /dev/null; warnings too.
    import warnings
    warnings.filterwarnings("ignore")
    with open(os.devnull, "w") as dn, contextlib.redirect_stdout(dn), \
            contextlib.redirect_stderr(dn):
        return run_start(*args)


def _fig(objective: str) -> str:
    return "fig5" if objective == "fuel" else "fig6"


def _read_done(path: Path) -> set[tuple[float, float, str]]:
    if not path.exists():
        return set()
    with open(path) as f:
        return {(float(r["design_range_nm"]), float(r["spec_energy_whkg"]), r["start_name"])
                for r in csv.DictReader(f)}


def _append(path: Path, rows: list[dict]) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def _coerce(row: dict) -> dict:
    """CSV strings back to the types run_start produced."""
    out = {}
    for k, v in row.items():
        if k in ("converged", "feasible"):
            out[k] = str(v).lower() == "true"
        elif k in ("objective", "start_name", "starts_tried", "error"):
            out[k] = v or ""
        else:
            try:
                out[k] = float(v) if v not in ("", None) else np.nan
            except ValueError:
                out[k] = v
    return out


def rebuild_best(starts_path: Path, best_path: Path) -> int:
    """Collapse the per-start log into one best row per cell."""
    cells: dict[tuple[float, float], list[dict]] = {}
    with open(starts_path) as f:
        for r in csv.DictReader(f):
            r = _coerce(r)
            cells.setdefault((r["design_range_nm"], r["spec_energy_whkg"]), []).append(r)
    rows = [pick_best(cells[k]) for k in sorted(cells)]
    with open(best_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def cmd_grid(args) -> int:
    ranges, energies = GRIDS[args.grid]
    starts = args.starts.split(",")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{_fig(args.objective)}_{args.grid}"
    starts_path = OUT_DIR / f"{stem}_starts.csv"
    best_path = OUT_DIR / f"{stem}.csv"
    if not args.resume and starts_path.exists():
        raise SystemExit(f"{starts_path} exists; pass --resume to continue it "
                         "or delete it for a fresh run")
    done = _read_done(starts_path)
    jobs = [(float(r), float(e), args.objective, s)
            for r in ranges for e in energies for s in starts
            if (float(r), float(e), s) not in done]
    # Demo-grid cells (every other range column) first, so a partial run
    # already covers the 11 x 12 grid the omd sweep used.
    jobs.sort(key=lambda j: (j[0] % 50.0 != 0.0, j[0], j[1]))
    if args.subset:
        sub_r, sub_e = GRIDS[args.subset]
        keep = {(float(r), float(e)) for r in sub_r for e in sub_e}
        jobs = [j for j in jobs if (j[0], j[1]) in keep]
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    print(f"[upstream-truth] {stem}: {len(jobs)} start(s) to run "
          f"({len(done)} already logged), {args.workers} workers", flush=True)
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers, maxtasksperchild=1) as pool:
        for i, row in enumerate(pool.imap_unordered(_worker, jobs), 1):
            _append(starts_path, [row])
            status = ("OK" if row["converged"] and row["feasible"] else
                      "FEAS" if row["feasible"] else "FAIL")
            obj = row["objective_value"]
            print(f"  [{i}/{len(jobs)}] r={row['design_range_nm']:.0f} "
                  f"e={row['spec_energy_whkg']:.0f} {row['start_name']:<8} {status:<4} "
                  f"obj={obj:.5g} t={row['wall_time_s']:.0f}s "
                  f"elapsed={time.time() - t0:.0f}s {row['error'][:60]}", flush=True)
    n = rebuild_best(starts_path, best_path)
    print(f"[upstream-truth] {n} cells -> {best_path.relative_to(DEMO_DIR)}")
    return 0


# sweep-CSV column -> DV (units as DESIGN_DVS), for warm starts
_WARM_COLS = {
    "MTOW_kg": "ac|weights|MTOW",
    "S_ref_m2": "ac|geom|wing|S_ref",
    "engine_rating_hp": "ac|propulsion|engine|rating",
    "motor_rating_hp": "ac|propulsion|motor|rating",
    "generator_rating_hp": "ac|propulsion|generator|rating",
    "W_battery_kg": "ac|weights|W_battery",
    "W_fuel_max_kg": "ac|weights|W_fuel_max",
    "cruise_hybridization": "cruise.hybridization",
    "climb_hybridization": "climb.hybridization",
    "descent_hybridization": "descent.hybridization",
}


def _warm_from_row(row: dict) -> dict[str, float]:
    out = {}
    for col, dv in _WARM_COLS.items():
        try:
            v = float(row.get(col, ""))
        except (TypeError, ValueError):
            continue
        if np.isfinite(v):
            out[dv] = v
    return out


def _polish_jobs(objective: str, grid: str, ref_csvs: list[Path],
                 rel: float) -> list[tuple]:
    """Warm-start jobs for cells where truth is infeasible or another
    source reached a better objective (by more than ``rel``).

    Starts: the better source's design (ref CSVs, e.g. the omd sweep),
    each feasible 4-neighbour's truth design, and the ``low`` preset if
    it was never tried. Truth stays upstream-only -- a foreign design is
    just a starting point; the reported optimum is upstream's own."""
    stem = f"{_fig(objective)}_{grid}"
    best_path = OUT_DIR / f"{stem}.csv"
    starts_path = OUT_DIR / f"{stem}_starts.csv"
    with open(best_path) as f:
        best = {(float(r["design_range_nm"]), float(r["spec_energy_whkg"])): _coerce(r)
                for r in csv.DictReader(f)}
    tried = _read_done(starts_path)
    refs: dict[tuple[float, float], list[tuple[str, dict]]] = {}
    for path in ref_csvs:
        with open(path) as f:
            for r in csv.DictReader(f):
                if str(r.get("converged", r.get("feasible", ""))).lower() != "true":
                    continue
                k = (float(r["design_range_nm"]), float(r["spec_energy_whkg"]))
                refs.setdefault(k, []).append((path.stem, r))
    rs = sorted({k[0] for k in best})
    es = sorted({k[1] for k in best})
    jobs = []
    for k, row in best.items():
        obj = row["objective_value"]
        bad = not row["feasible"] or not np.isfinite(obj)
        better = []
        for name, r in refs.get(k, []):
            try:
                ov = float(r.get("objective_value") or r.get("mixed_objective_kg")
                           or r.get("doc_per_nmi"))
            except (TypeError, ValueError):
                continue
            if bad or ov < obj - rel * max(abs(obj), 1e-9):
                better.append((name, r))
        if not (bad or better):
            continue
        cand = [(f"warm:{name}", _warm_from_row(r)) for name, r in better]
        i, j = rs.index(k[0]), es.index(k[1])
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if 0 <= i + di < len(rs) and 0 <= j + dj < len(es):
                n = best.get((rs[i + di], es[j + dj]))
                if n and n["feasible"]:
                    cand.append((f"warm:nb{rs[i + di]:g}-{es[j + dj]:g}", _warm_from_row(n)))
        if (k[0], k[1], "low") not in tried:
            cand.append(("low", None))
        for name, init in cand:
            if (k[0], k[1], name) not in tried:
                jobs.append((k[0], k[1], objective, name, init))
    return jobs


def cmd_polish(args) -> int:
    refs = [Path(p) for p in args.ref]
    jobs = _polish_jobs(args.objective, args.grid, refs, args.rel)
    stem = f"{_fig(args.objective)}_{args.grid}"
    starts_path = OUT_DIR / f"{stem}_starts.csv"
    print(f"[upstream-truth] polish {stem}: {len(jobs)} warm start(s) over "
          f"{len({(j[0], j[1]) for j in jobs})} cell(s)", flush=True)
    if args.dry_run or not jobs:
        for j in jobs:
            print(f"  r={j[0]:g} e={j[1]:g} {j[3]}")
        return 0
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers, maxtasksperchild=1) as pool:
        for i, row in enumerate(pool.imap_unordered(_worker, jobs), 1):
            _append(starts_path, [row])
            print(f"  [{i}/{len(jobs)}] r={row['design_range_nm']:.0f} "
                  f"e={row['spec_energy_whkg']:.0f} {row['start_name']:<18} "
                  f"feas={row['feasible']} obj={row['objective_value']:.5g} "
                  f"elapsed={time.time() - t0:.0f}s", flush=True)
    n = rebuild_best(starts_path, OUT_DIR / f"{stem}.csv")
    print(f"[upstream-truth] {n} cells rebuilt")
    return 0


def cmd_cell(args) -> int:
    rows = [run_start(args.range, args.spec_energy, args.objective, s)
            for s in args.starts.split(",")]
    best = pick_best(rows)
    best.pop("_tb", None)
    print(json.dumps({k: (None if isinstance(v, float) and np.isnan(v) else v)
                      for k, v in best.items()}, indent=2, default=str))
    return 0 if best["feasible"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cell", help="one cell, all starts, print best as JSON")
    c.add_argument("--range", type=float, default=500.0)
    c.add_argument("--spec-energy", type=float, default=450.0)
    c.add_argument("--objective", choices=["fuel", "cost"], default="fuel")
    c.add_argument("--starts", default="upstream,low,high")
    g = sub.add_parser("grid", help="sweep a grid, checkpointed per start")
    g.add_argument("--objective", choices=["fuel", "cost"], required=True)
    g.add_argument("--grid", choices=sorted(GRIDS), default="paper")
    g.add_argument("--starts", default="upstream,high",
                   help="comma list from START_PRESETS (default: upstream,high; "
                        "the anchor pilot found low adds nothing)")
    g.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    g.add_argument("--resume", action="store_true")
    g.add_argument("--subset", choices=sorted(GRIDS), default=None,
                   help="only run the cells of this grid (results still go to "
                        "the --grid files), e.g. --grid paper --subset demo")
    g.add_argument("--max-jobs", type=int, default=0,
                   help="cap the number of starts this invocation runs (pilot)")
    r = sub.add_parser("rebuild", help="re-derive the best-per-cell CSV from the starts log")
    r.add_argument("--objective", choices=["fuel", "cost"], required=True)
    r.add_argument("--grid", choices=sorted(GRIDS), default="paper")
    pl = sub.add_parser("polish", help="warm-start cells where truth is infeasible "
                                       "or another source found a better optimum")
    pl.add_argument("--objective", choices=["fuel", "cost"], required=True)
    pl.add_argument("--grid", choices=sorted(GRIDS), default="paper")
    pl.add_argument("--ref", action="append", default=[],
                    help="sweep-style CSV of other designs (e.g. results/fig5_grid.csv)")
    pl.add_argument("--rel", type=float, default=1e-3,
                    help="relative objective improvement that triggers a polish")
    pl.add_argument("--workers", type=int, default=4)
    pl.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "polish":
        return cmd_polish(args)
    if args.cmd == "cell":
        return cmd_cell(args)
    if args.cmd == "rebuild":
        stem = f"{_fig(args.objective)}_{args.grid}"
        n = rebuild_best(OUT_DIR / f"{stem}_starts.csv", OUT_DIR / f"{stem}.csv")
        print(f"{n} cells")
        return 0
    return cmd_grid(args)


if __name__ == "__main__":
    sys.exit(main())
