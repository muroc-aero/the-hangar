"""Brelje 2018a statistics harness: paper vs truth vs scripted vs agent.

Puts every source of Fig 5 / Fig 6 numbers on one per-cell table and
scores each against a reference, so "does the agent reproduce the
paper?" becomes a set of numbers instead of a side-by-side PNG.

Sources (each optional except where a comparison needs it):

  paper   -- the published figures, digitized per cell
             (paper_ref/fig{5,6}_paper_digitized.csv; 21 x 12)
  truth   -- Lane A (upstream): OpenConcept's own HybridTwin MDO
             (results/lane_a_upstream/fig{5,6}_paper.csv)
  lane_b  -- the scripted omd pipeline sweep (results/fig{5,6}_grid.csv)
  <agent> -- any number of agent-driven runs, each an omd study
             directory (hangar_data/studies/<id>/, reads cases.csv), a
             cases.csv, a sweep-style CSV, or a directory of per-cell
             Lane C JSON files. Pass ``--agent NAME=PATH``; repeat the
             same NAME for several seeds of one arm.

Comparisons made:

  truth  vs paper  -- validates the truth lane against the publication
                      (the only check that does not assume a model)
  X      vs truth  -- for X in lane_b + every agent seed: optimality gap
                      on the objective, per-metric relative error,
                      coverage, basin (regime) agreement
  X      vs paper  -- same, on the four published panels

Outputs (``--out``, default results/stats/):

  per_cell.csv      long table: fig, range, energy, source, metric, value,
                    ref, ref_value, err, rel_err, within_tol
  summary.json      every aggregate below, machine readable
  summary.md        the same as markdown tables (paste-ready)
  err_fig{5,6}.png  relative-error heatmaps, one row per comparison

Usage:
    uv run python packages/omd/demos/brelje_2018a/stats/collect_stats.py
    uv run python ... --agent opus=hangar_data/studies/brelje-2018a-fig5 \\
                      --agent opus=hangar_data/studies/brelje-2018a-fig5-seed1
    uv run python ... --figure 5 --no-plots
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import numpy as np

STATS_DIR = Path(__file__).resolve().parent
DEMO_DIR = STATS_DIR.parent
RESULTS = DEMO_DIR / "results"

LB_PER_KG = 2.2046226218
FT2_PER_M2 = 10.7639104

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

# Canonical metric names. "objective" is resolved per figure: Fig 5
# minimises fuel + MTOW/100 (kg), Fig 6 minimises trip DOC per nmi.
METRICS = [
    "objective",
    "MTOW_lb",
    "fuel_mileage_lb_per_nmi",
    "W_battery_kg",
    "S_ref_m2",
    "cruise_hybridization",
    "electric_percent",      # the paper's definition: battery share of
                             # motor electrical energy (see README)
    "doc_per_nmi",
]

# Metrics the paper publishes (one panel each).
PAPER_METRICS = ["fuel_mileage_lb_per_nmi", "doc_per_nmi", "electric_percent", "MTOW_lb"]

# Default pass tolerances. Relative for model-vs-model; for model-vs-paper
# the digitisation half-width is added on top (see _tolerance).
REL_TOL = {
    "objective": 0.01,
    "MTOW_lb": 0.01,
    "fuel_mileage_lb_per_nmi": 0.02,
    "W_battery_kg": 0.02,
    "S_ref_m2": 0.02,
    "cruise_hybridization": 0.02,
    "electric_percent": 0.02,
    "doc_per_nmi": 0.02,
}
# Absolute floors so near-zero values (all-electric fuel mileage, 0.1 %
# hybridization) do not turn rounding into a 100 % "error".
ABS_FLOOR = {
    "objective": 0.5,               # kg (fig5); DOC handled by its own floor
    "MTOW_lb": 20.0,
    "fuel_mileage_lb_per_nmi": 0.02,
    "W_battery_kg": 5.0,
    "S_ref_m2": 0.2,
    "cruise_hybridization": 0.01,
    "electric_percent": 1.0,        # percentage points
    "doc_per_nmi": 0.005,
}
OBJECTIVE_FLOOR = {"5": 0.5, "6": 0.002}

# Regimes for basin agreement, on the paper's electric percent.
REGIMES = [("fuel", 0.0, 10.0), ("hybrid", 10.0, 95.0), ("electric", 95.0, 100.01)]


def _regime(pct: float) -> str | None:
    if pct is None or not math.isfinite(pct):
        return None
    for name, lo, hi in REGIMES:
        if lo <= pct < hi:
            return name
    return None


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

Cell = tuple[float, float]  # (design_range_nm, spec_energy_whkg)

# --named-only: ignore campaign cells graded from the best run in the
# agent's DB rather than the run the agent named (agent_campaign.py).
NAMED_ONLY = False


@dataclass
class Source:
    name: str
    kind: str                           # paper | truth | lane_b | agent
    fig: str
    cells: dict[Cell, dict] = field(default_factory=dict)   # metric -> value
    ok: dict[Cell, bool] = field(default_factory=dict)      # converged/feasible
    halfwidth: dict[Cell, dict] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    seed: str = ""

    @property
    def label(self) -> str:
        return f"{self.name}[{self.seed}]" if self.seed else self.name


def _f(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "null"):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "converged", "completed", "ok")


def _key(r: float, e: float) -> Cell:
    return (round(float(r), 3), round(float(e), 3))


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_paper(fig: str) -> Source | None:
    path = DEMO_DIR / "paper_ref" / f"fig{fig}_paper_digitized.csv"
    if not path.exists():
        return None
    src = Source("paper", "paper", fig, meta={"path": str(path)})
    for r in _read_csv(path):
        k = _key(r["design_range_nm"], r["spec_energy_whkg"])
        src.cells[k] = {m: _f(r.get(m)) for m in PAPER_METRICS}
        src.halfwidth[k] = {m: _f(r.get(f"{m}_halfwidth")) or 0.0 for m in PAPER_METRICS}
        src.ok[k] = True
    return src


def _sweep_row_metrics(r: dict, fig: str) -> dict:
    """Metrics from a sweep-style row (upstream truth or pipeline/sweep.py)."""
    rng = _f(r.get("design_range_nm"))
    mtow_lb = _f(r.get("MTOW_lb"))
    if mtow_lb is None and _f(r.get("MTOW_kg")) is not None:
        mtow_lb = _f(r["MTOW_kg"]) * LB_PER_KG
    fuel_lb = _f(r.get("fuel_burn_lb"))
    if fuel_lb is None and _f(r.get("fuel_burn_kg")) is not None:
        fuel_lb = _f(r["fuel_burn_kg"]) * LB_PER_KG
    mileage = _f(r.get("fuel_mileage_lb_per_nmi"))
    if mileage is None and fuel_lb is not None and rng:
        mileage = fuel_lb / rng
    efrac = _f(r.get("electric_energy_frac"))
    doc = _f(r.get("doc_per_nmi"))
    if fig == "5":
        obj = _f(r.get("mixed_objective_kg"))
        if obj is None:
            obj = _f(r.get("objective_value"))
    else:
        obj = doc if doc is not None else _f(r.get("objective_value"))
    return {
        "objective": obj,
        "MTOW_lb": mtow_lb,
        "fuel_mileage_lb_per_nmi": mileage,
        "W_battery_kg": _f(r.get("W_battery_kg")),
        "S_ref_m2": _f(r.get("S_ref_m2")),
        "cruise_hybridization": _f(r.get("cruise_hybridization")),
        # Only the upstream truth lane records the energy fraction; the
        # omd sweep CSV's electric_percent is 100 x cruise hybridization,
        # which is NOT what the paper plots, so it is not mapped here.
        "electric_percent": 100.0 * efrac if efrac is not None else None,
        "doc_per_nmi": doc,
    }


def load_truth(fig: str, grid: str = "paper") -> Source | None:
    """Truth cells from the requested grid file, topped up with any cell
    only the other truth files have (e.g. the anchors pilot while the
    paper grid is still running)."""
    order = [grid] + [g for g in ("paper", "demo", "anchors") if g != grid]
    paths = [RESULTS / "lane_a_upstream" / f"fig{fig}_{g}.csv" for g in order]
    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    src = Source("truth", "truth", fig, meta={"path": [str(p) for p in paths]})
    starts = defaultdict(list)
    for path in paths:
        for r in _read_csv(path):
            k = _key(r["design_range_nm"], r["spec_energy_whkg"])
            if k in src.cells:
                continue
            src.cells[k] = _sweep_row_metrics(r, fig)
            src.ok[k] = _truthy(r.get("feasible")) and src.cells[k]["objective"] is not None
            starts[k] = r.get("starts_tried", "")
    # start agreement: how often did every feasible start land on the
    # same optimum? (a truth-quality statistic in its own right)
    agree = 0
    total = 0
    for s in starts.values():
        vals = [float(m) for m in re.findall(r"=(?:OK|FEAS)\(([-0-9.eE+]+)\)", s)]
        if len(vals) >= 2:
            total += 1
            if max(vals) - min(vals) <= 1e-3 * max(1.0, abs(min(vals))):
                agree += 1
    src.meta["starts_agree"] = agree
    src.meta["cells_multi_start"] = total
    return src


def load_lane_b(fig: str) -> Source | None:
    path = RESULTS / f"fig{fig}_grid.csv"
    if not path.exists():
        return None
    src = Source("lane_b", "lane_b", fig, meta={"path": str(path)})
    for r in _read_csv(path):
        k = _key(r["design_range_nm"], r["spec_energy_whkg"])
        src.cells[k] = _sweep_row_metrics(r, fig)
        src.ok[k] = _truthy(r.get("converged")) and src.cells[k]["objective"] is not None
    return src


# Column aliases for agent-authored outputs (an agent names its study
# outputs itself). First hit wins; unit handled per alias.
_AGENT_AXES = {
    "range": ["design_range_nm", "range_nm", "design_range", "mission_range_NM",
              "mission_range_nm", "range"],
    "energy": ["spec_energy_whkg", "spec_e", "battery_specific_energy",
               "specific_energy", "spec_energy", "energy"],
}
_AGENT_ALIASES: dict[str, list[tuple[str, float]]] = {
    # metric -> [(column, multiplier to canonical units)]
    "mixed_objective": [("mixed_objective", 1.0), ("mixed_objective_kg", 1.0)],
    "doc_per_nmi": [("doc_per_nmi", 1.0), ("doc_per_nmi_usd", 1.0), ("DOC_per_nmi", 1.0)],
    "MTOW_lb": [("MTOW_lb", 1.0), ("MTOW_kg", LB_PER_KG), ("MTOW", LB_PER_KG)],
    "fuel_lb": [("fuel_burn_lb", 1.0), ("fuel_lb", 1.0), ("fuel_burn_kg", LB_PER_KG),
                ("fuel_kg", LB_PER_KG), ("fuel_burn", LB_PER_KG),
                ("fuel_used_final", LB_PER_KG)],
    "W_battery_kg": [("W_battery_kg", 1.0), ("W_battery_lb", 1 / LB_PER_KG),
                     ("W_battery", 1.0), ("battery_weight_kg", 1.0)],
    "S_ref_m2": [("S_ref_m2", 1.0), ("Sref_m2", 1.0), ("Sref_ft2", 1 / FT2_PER_M2),
                 ("S_ref_ft2", 1 / FT2_PER_M2), ("S_ref", 1.0)],
    "cruise_hybridization": [("cruise_hybridization", 1.0), ("cruise_h", 1.0),
                             ("hybridization", 1.0)],
    "electric_energy_frac": [("electric_energy_frac", 1.0)],
    "objective_value": [("objective_value", 1.0), ("objective", 1.0)],
}


def _pick(row: dict, metric: str) -> float | None:
    for col, mult in _AGENT_ALIASES[metric]:
        if col in row:
            v = _f(row[col])
            if v is not None:
                return v * mult
    return None


def _pick_axis(row: dict, axis: str) -> float | None:
    for col in _AGENT_AXES[axis]:
        if col in row and _f(row[col]) is not None:
            return _f(row[col])
    return None


def _agent_metrics(row: dict, fig: str) -> tuple[Cell | None, dict]:
    rng, en = _pick_axis(row, "range"), _pick_axis(row, "energy")
    if rng is None or en is None:
        # fall back to the fig5_study id_template, e.g. r500-e450
        m = re.search(r"r(\d+(?:\.\d+)?)-e(\d+(?:\.\d+)?)", str(row.get("case_id", "")))
        if not m:
            return None, {}
        rng, en = float(m.group(1)), float(m.group(2))
    fuel_lb = _pick(row, "fuel_lb")
    doc = _pick(row, "doc_per_nmi")
    obj = _pick(row, "mixed_objective") if fig == "5" else doc
    if obj is None:
        obj = _pick(row, "objective_value")
    efrac = _pick(row, "electric_energy_frac")
    return _key(rng, en), {
        "objective": obj,
        "MTOW_lb": _pick(row, "MTOW_lb"),
        "fuel_mileage_lb_per_nmi": fuel_lb / rng if fuel_lb is not None else None,
        "W_battery_kg": _pick(row, "W_battery_kg"),
        "S_ref_m2": _pick(row, "S_ref_m2"),
        "cruise_hybridization": _pick(row, "cruise_hybridization"),
        "electric_percent": 100.0 * efrac if efrac is not None else None,
        "doc_per_nmi": doc,
    }


def load_agent(name: str, seed: str, path: Path, fig: str) -> Source:
    """An agent run: study dir, cases.csv / sweep CSV, or dir of JSONs."""
    src = Source(name, "agent", fig, seed=seed, meta={"path": str(path)})
    rows: list[tuple[dict, bool]] = []
    if path.is_dir() and (path / "cases.csv").exists():
        path = path / "cases.csv"
    if path.is_file() and path.suffix == ".csv":
        for r in _read_csv(path):
            status = r.get("status", r.get("converged", ""))
            rows.append((r, _truthy(status)))
        # study-level execution stats
        statuses = defaultdict(int)
        wall = 0.0
        for r, _ in rows:
            statuses[str(r.get("status", r.get("converged", ""))).lower()] += 1
            wall += _f(r.get("wall_time_s")) or 0.0
        src.meta.update(statuses=dict(statuses), wall_time_s=wall, n_rows=len(rows))
        state = path.parent / "state.json"
        if state.exists():
            try:
                st = json.loads(state.read_text())
                src.meta["study_id"] = st.get("study_id")
                src.meta["study_version"] = st.get("version")
            except (json.JSONDecodeError, OSError):
                pass
    elif path.is_dir():
        for p in sorted(path.glob("*.json")):
            try:
                r = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            r.setdefault("case_id", p.stem)
            if NAMED_ONLY and r.get("grading") == "best_in_db":
                continue
            rows.append((r, _truthy(r.get("converged", True))))
        src.meta["n_rows"] = len(rows)
    else:
        raise SystemExit(f"agent source {path} is not a study dir, CSV, or JSON dir")
    for r, ok in rows:
        k, metrics = _agent_metrics(r, fig)
        if k is None:
            continue
        # a study can hold a manual reference case at an existing grid
        # cell; keep the better-objective successful row
        prev = src.cells.get(k)
        if prev is not None and src.ok.get(k) and not ok:
            continue
        if (prev is not None and src.ok.get(k) and ok and metrics["objective"] is not None
                and prev["objective"] is not None and prev["objective"] <= metrics["objective"]):
            continue
        src.cells[k] = metrics
        src.ok[k] = ok and metrics["objective"] is not None
    return src


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _tolerance(metric: str, fig: str, ref_val: float, halfwidth: float) -> float:
    floor = OBJECTIVE_FLOOR[fig] if metric == "objective" else ABS_FLOOR[metric]
    return max(REL_TOL[metric] * abs(ref_val), floor) + halfwidth


def compare(cand: Source, ref: Source, metrics: list[str]) -> tuple[dict, list[dict]]:
    fig = cand.fig
    per_cell: list[dict] = []
    ref_cells = [k for k in ref.cells if ref.ok.get(k)]
    cand_cells = set(cand.cells)
    common = [k for k in ref_cells if k in cand_cells and cand.ok.get(k)]
    out = {
        "candidate": cand.label, "reference": ref.label, "fig": fig,
        "n_reference": len(ref_cells),
        "n_candidate": len(cand.cells),
        "n_candidate_ok": sum(1 for k in cand.cells if cand.ok.get(k)),
        # coverage is measured on the reference cells the candidate
        # attempted, so an 11x12 candidate is not penalised against the
        # 21x12 truth for columns it never tried
        "n_attempted": sum(1 for k in ref_cells if k in cand_cells),
        "n_common_ok": len(common),
        "metrics": {},
    }
    out["coverage"] = (len(common) / out["n_attempted"]) if out["n_attempted"] else None

    for m in metrics:
        errs, rels, oks = [], [], []
        for k in common:
            a = cand.cells[k].get(m)
            b = ref.cells[k].get(m)
            if a is None or b is None:
                continue
            hw = (ref.halfwidth.get(k, {}) or {}).get(m, 0.0) or 0.0
            err = a - b
            tol = _tolerance(m, fig, b, hw)
            rel = err / abs(b) if abs(b) > 1e-12 else None
            within = abs(err) <= tol
            errs.append(err)
            if rel is not None:
                rels.append(rel)
            oks.append(within)
            per_cell.append({
                "fig": fig, "design_range_nm": k[0], "spec_energy_whkg": k[1],
                "source": cand.label, "metric": m, "value": a,
                "ref": ref.label, "ref_value": b, "ref_halfwidth": hw,
                "err": err, "rel_err": rel, "tol": tol, "within_tol": within,
            })
        if not errs:
            continue
        abs_rel = [abs(r) for r in rels]
        out["metrics"][m] = {
            "n": len(errs),
            "pass_rate": sum(oks) / len(oks),
            "median_abs_rel": median(abs_rel) if abs_rel else None,
            "p90_abs_rel": float(np.percentile(abs_rel, 90)) if abs_rel else None,
            "max_abs_rel": max(abs_rel) if abs_rel else None,
            "mean_rel": float(np.mean(rels)) if rels else None,       # signed bias
            "median_abs_err": median(abs(e) for e in errs),
            "max_abs_err": max(abs(e) for e in errs),
        }

    # Optimality gap on the objective, only meaningful vs a model lane:
    # >0 means the candidate stopped at a worse optimum than the reference.
    if ref.kind != "paper":
        gaps = []
        for k in common:
            a, b = cand.cells[k].get("objective"), ref.cells[k].get("objective")
            if a is None or b is None:
                continue
            gaps.append((a - b) / max(abs(b), OBJECTIVE_FLOOR[fig]))
        if gaps:
            worse = [g for g in gaps if g > 1e-3]
            better = [g for g in gaps if g < -1e-3]
            out["optimality_gap"] = {
                "n": len(gaps),
                "median": median(gaps),
                "max": max(gaps),
                "frac_worse_than_ref": len(worse) / len(gaps),
                "frac_better_than_ref": len(better) / len(gaps),
                "frac_matched": 1 - (len(worse) + len(better)) / len(gaps),
            }

    # Basin agreement: same design regime (fuel / hybrid / electric).
    # Uses the paper's electric percent where both sides have it, else
    # cruise hybridization on both sides (model-vs-model only).
    agree = total = 0
    basis = set()
    for k in common:
        a, b = cand.cells[k], ref.cells[k]
        if a.get("electric_percent") is not None and b.get("electric_percent") is not None:
            ra, rb = _regime(a["electric_percent"]), _regime(b["electric_percent"])
            basis.add("electric_percent")
        elif a.get("cruise_hybridization") is not None and b.get("cruise_hybridization") is not None:
            ra = _regime(100 * a["cruise_hybridization"])
            rb = _regime(100 * b["cruise_hybridization"])
            basis.add("cruise_hybridization")
        else:
            continue
        if ra and rb:
            total += 1
            agree += ra == rb
    if total:
        out["regime_agreement"] = {"n": total, "rate": agree / total,
                                   "basis": sorted(basis)}
    return out, per_cell


def aggregate_seeds(results: list[dict]) -> dict:
    """Mean / min / max across seeds of one arm, per headline statistic."""
    def col(get):
        vals = [get(r) for r in results]
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {"mean": float(np.mean(vals)), "min": float(min(vals)),
                "max": float(max(vals)), "n_seeds": len(vals)}
    return {
        "coverage": col(lambda r: r.get("coverage")),
        "objective_pass_rate": col(lambda r: r["metrics"].get("objective", {}).get("pass_rate")),
        "objective_median_abs_rel": col(lambda r: r["metrics"].get("objective", {}).get("median_abs_rel")),
        "frac_matched_optimum": col(lambda r: (r.get("optimality_gap") or {}).get("frac_matched")),
        "regime_agreement": col(lambda r: (r.get("regime_agreement") or {}).get("rate")),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _pct(x) -> str:
    return "--" if x is None else f"{100 * x:.2f}%"


def _num(x, nd=4) -> str:
    return "--" if x is None else f"{x:.{nd}g}"


def write_markdown(summary: dict, path: Path) -> None:
    L = ["# Brelje 2018a -- reproduction statistics", ""]
    L.append(f"Generated by `stats/collect_stats.py`. Sources: "
             + ", ".join(f"`{s}`" for s in summary["sources"]) + ".")
    L.append("")
    L.append("Tolerances: relative "
             + ", ".join(f"{m} {100 * t:g}%" for m, t in REL_TOL.items())
             + "; against the paper the digitisation half-width is added.")
    L.append("")
    for fig, blocks in summary["figures"].items():
        L.append(f"## Figure {fig} ({'min fuel + MTOW/100' if fig == '5' else 'min trip DOC'})")
        L.append("")
        tq = blocks.get("truth_quality")
        if tq:
            L.append(f"Truth lane: {tq['n_ok']}/{tq['n_cells']} cells feasible; "
                     f"{tq['starts_agree']}/{tq['cells_multi_start']} multi-start cells "
                     "had every feasible start land on the same optimum.")
            L.append("")
        L.append("| candidate | reference | coverage | obj pass | obj med |rel| | "
                 "obj max |rel| | matched opt | worse opt | regime agree |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for c in blocks["comparisons"]:
            o = c["metrics"].get("objective", {})
            g = c.get("optimality_gap") or {}
            ra = c.get("regime_agreement") or {}
            L.append(
                f"| {c['candidate']} | {c['reference']} | "
                f"{c['n_common_ok']}/{c['n_attempted']} | {_pct(o.get('pass_rate'))} | "
                f"{_pct(o.get('median_abs_rel'))} | {_pct(o.get('max_abs_rel'))} | "
                f"{_pct(g.get('frac_matched'))} | {_pct(g.get('frac_worse_than_ref'))} | "
                f"{_pct(ra.get('rate'))} |")
        L.append("")
        L.append("Per-metric pass rate / median |rel err| / max |rel err|:")
        L.append("")
        metrics = [m for m in METRICS if any(m in c["metrics"] for c in blocks["comparisons"])]
        L.append("| candidate vs reference | " + " | ".join(metrics) + " |")
        L.append("|---|" + "---|" * len(metrics))
        for c in blocks["comparisons"]:
            cells = []
            for m in metrics:
                s = c["metrics"].get(m)
                cells.append("--" if not s else
                             f"{_pct(s['pass_rate'])} / {_pct(s['median_abs_rel'])} / "
                             f"{_pct(s['max_abs_rel'])}")
            L.append(f"| {c['candidate']} vs {c['reference']} | " + " | ".join(cells) + " |")
        L.append("")
        if blocks.get("arms"):
            L.append("Agent arms across seeds (mean [min, max]):")
            L.append("")
            L.append("| arm | reference | seeds | coverage | obj pass | matched opt | regime agree |")
            L.append("|---|---|---|---|---|---|---|")
            for arm in blocks["arms"]:
                def mm(d):
                    return "--" if not d else f"{_pct(d['mean'])} [{_pct(d['min'])}, {_pct(d['max'])}]"
                a = arm["aggregate"]
                n = (a.get("coverage") or {}).get("n_seeds", 0)
                L.append(f"| {arm['arm']} | {arm['reference']} | {n} | {mm(a['coverage'])} | "
                         f"{mm(a['objective_pass_rate'])} | {mm(a['frac_matched_optimum'])} | "
                         f"{mm(a['regime_agreement'])} |")
            L.append("")
    path.write_text("\n".join(L) + "\n")


def plot_errors(fig: str, comps: list[dict], per_cell: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = [c for c in comps if c["metrics"]]
    if not rows:
        return
    metrics = ["objective"] + PAPER_METRICS
    by = defaultdict(dict)
    for r in per_cell:
        if r["fig"] == fig and r["rel_err"] is not None:
            by[(r["source"], r["ref"], r["metric"])][(r["design_range_nm"], r["spec_energy_whkg"])] = r["rel_err"]
    fig_h, axes = plt.subplots(len(rows), len(metrics), figsize=(3.0 * len(metrics), 2.6 * len(rows)),
                               squeeze=False, constrained_layout=True)
    for i, c in enumerate(rows):
        for j, m in enumerate(metrics):
            ax = axes[i][j]
            d = by.get((c["candidate"], c["reference"], m))
            if not d:
                ax.axis("off")
                continue
            xs = sorted({k[0] for k in d})
            ys = sorted({k[1] for k in d})
            Z = np.full((len(ys), len(xs)), np.nan)
            for (x, y), v in d.items():
                Z[ys.index(y), xs.index(x)] = 100 * v
            lim = max(1.0, float(np.nanpercentile(np.abs(Z), 95)))
            im = ax.pcolormesh(_edges(xs), _edges(ys), Z, cmap="RdBu_r", vmin=-lim, vmax=lim)
            fig_h.colorbar(im, ax=ax, label="rel err (%)")
            ax.set_title(f"{c['candidate']} vs {c['reference']}\n{m}", fontsize=8)
            ax.tick_params(labelsize=7)
    fig_h.suptitle(f"Brelje 2018a Fig {fig}: relative error per cell")
    fig_h.savefig(path, dpi=110)
    plt.close(fig_h)


def _edges(v: list[float]) -> np.ndarray:
    v = np.asarray(v, float)
    if len(v) == 1:
        return np.array([v[0] - 0.5, v[0] + 0.5])
    mid = (v[1:] + v[:-1]) / 2
    return np.concatenate([[v[0] - (mid[0] - v[0])], mid, [v[-1] + (v[-1] - mid[-1])]])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parse_agents(specs: list[str]) -> list[tuple[str, str, Path]]:
    out = []
    counts = defaultdict(int)
    for s in specs:
        if "=" not in s:
            raise SystemExit(f"--agent expects NAME=PATH, got {s!r}")
        name, p = s.split("=", 1)
        seed = str(counts[name])
        counts[name] += 1
        out.append((name, seed, Path(p)))
    # single-seed arms get no [seed] suffix
    return [(n, s if counts[n] > 1 else "", p) for n, s, p in out]


def run(figs: list[str], agents: list[tuple[str, str, Path]], agent_fig: dict[str, str],
        out_dir: Path, plots: bool, truth_grid: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"sources": [], "figures": {}}
    all_cells: list[dict] = []
    for fig in figs:
        paper, truth, lane_b = load_paper(fig), load_truth(fig, truth_grid), load_lane_b(fig)
        agent_srcs = []
        for name, seed, p in agents:
            # an agent path applies to one figure: --agent-fig NAME=5|6,
            # else guessed from the path ("fig6"/"cost" -> 6), else 5
            want = agent_fig.get(name) or ("6" if re.search(r"fig6|cost", str(p)) else "5")
            if want == fig:
                agent_srcs.append(load_agent(name, seed, p, fig))
        comps: list[dict] = []
        blocks: dict = {"comparisons": comps}
        if truth:
            blocks["truth_quality"] = {
                "n_cells": len(truth.cells), "n_ok": sum(truth.ok.values()),
                "starts_agree": truth.meta["starts_agree"],
                "cells_multi_start": truth.meta["cells_multi_start"],
            }
        pairs = []
        if truth and paper:
            pairs.append((truth, paper, PAPER_METRICS))
        for cand in ([lane_b] if lane_b else []) + agent_srcs:
            if truth:
                pairs.append((cand, truth, METRICS))
            if paper:
                pairs.append((cand, paper, PAPER_METRICS))
        for cand, ref, ms in pairs:
            res, cells = compare(cand, ref, ms)
            res["candidate_meta"] = cand.meta
            comps.append(res)
            all_cells.extend(cells)
        arms = defaultdict(list)
        for c, (cand, ref, _) in zip(comps, pairs):
            if cand.kind == "agent":
                arms[(cand.name, ref.label)].append(c)
        blocks["arms"] = [{"arm": a, "reference": r, "aggregate": aggregate_seeds(v)}
                          for (a, r), v in arms.items()]
        summary["figures"][fig] = blocks
        for s in [paper, truth, lane_b, *agent_srcs]:
            if s and s.label not in summary["sources"]:
                summary["sources"].append(s.label)
        if plots:
            plot_errors(fig, comps, all_cells, out_dir / f"err_fig{fig}.png")

    with open(out_dir / "per_cell.csv", "w", newline="") as f:
        cols = ["fig", "design_range_nm", "spec_energy_whkg", "source", "metric", "value",
                "ref", "ref_value", "ref_halfwidth", "err", "rel_err", "tol", "within_tol"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_cells)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    write_markdown(summary, out_dir / "summary.md")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--figure", choices=["5", "6", "all"], default="all")
    ap.add_argument("--agent", action="append", default=[], metavar="NAME=PATH",
                    help="agent-driven run (study dir, CSV, or JSON dir); repeat "
                         "NAME for seeds")
    ap.add_argument("--agent-fig", action="append", default=[], metavar="NAME=5|6",
                    help="which figure an agent arm reproduces (default: guessed "
                         "from the path, fig6/cost -> 6, else 5)")
    ap.add_argument("--truth-grid", default="paper", choices=["paper", "demo", "anchors"])
    ap.add_argument("--out", type=Path, default=RESULTS / "stats")
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--named-only", action="store_true",
                    help="drop agent cells not graded on the run the agent named")
    args = ap.parse_args()
    global NAMED_ONLY
    NAMED_ONLY = args.named_only
    figs = ["5", "6"] if args.figure == "all" else [args.figure]
    agent_fig = dict(s.split("=", 1) for s in args.agent_fig)
    summary = run(figs, _parse_agents(args.agent), agent_fig, args.out,
                  not args.no_plots, args.truth_grid)
    print((args.out / "summary.md").read_text())
    n = sum(len(b["comparisons"]) for b in summary["figures"].values())
    print(f"{n} comparisons -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
