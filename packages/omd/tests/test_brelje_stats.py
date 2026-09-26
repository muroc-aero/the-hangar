"""Brelje 2018a reproduction-statistics harness (demos/brelje_2018a).

Covers the pieces that do not need an optimizer: the paper-figure
digitizer, the per-cell comparison math, and the agent-output loader.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "demos" / "brelje_2018a"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, DEMO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def digitize():
    pytest.importorskip("PIL")
    return _load("brelje_digitize", "paper_ref/digitize_paper_figs.py")


@pytest.fixture(scope="module")
def stats():
    return _load("brelje_collect_stats", "stats/collect_stats.py")


@pytest.mark.parametrize("fig", ["5", "6"])
def test_digitizer_reads_every_cell_on_the_colorbar(digitize, fig):
    rows = digitize.digitize_figure(fig)
    assert len(rows) == 21 * 12
    worst = max(v for r in rows for k, v in r.items() if k.endswith("_colour_err"))
    assert worst < 40, "a sampled pixel is not on its panel's colorbar"


def test_digitizer_anchor_values(digitize):
    """Spot values an upstream HybridTwin MDO reproduces (fig 5)."""
    cell = {(r["design_range_nm"], r["spec_energy_whkg"]): r
            for r in digitize.digitize_figure("5")}
    lo = cell[(500.0, 250.0)]
    assert lo["MTOW_lb"] == pytest.approx(8913.3, abs=30)       # truth 8913.3
    assert lo["electric_percent"] < 10                          # fuel-dominant
    hi = cell[(500.0, 750.0)]
    assert hi["electric_percent"] > 95                          # all-electric
    assert hi["fuel_mileage_lb_per_nmi"] < 0.1


def _src(stats, name, kind, fig, cells, ok=None):
    s = stats.Source(name, kind, fig)
    for k, m in cells.items():
        s.cells[k] = {mm: m.get(mm) for mm in stats.METRICS}
        s.ok[k] = True if ok is None else ok.get(k, True)
    return s


def test_compare_gap_coverage_and_pass_rate(stats):
    truth = _src(stats, "truth", "truth", "5", {
        (300.0, 250.0): {"objective": 200.0, "MTOW_lb": 9000.0, "electric_percent": 3.0},
        (300.0, 300.0): {"objective": 100.0, "MTOW_lb": 12566.0, "electric_percent": 60.0},
        (325.0, 250.0): {"objective": 210.0, "MTOW_lb": 9100.0, "electric_percent": 3.0},
    })
    cand = _src(stats, "agent", "agent", "5", {
        (300.0, 250.0): {"objective": 200.0, "MTOW_lb": 9000.0, "electric_percent": 3.0},
        (300.0, 300.0): {"objective": 110.0, "MTOW_lb": 9000.0, "electric_percent": 4.0},
    })
    res, cells = stats.compare(cand, truth, ["objective", "MTOW_lb"])
    # the 325 nmi column was never attempted, so coverage is 2/2
    assert res["n_attempted"] == 2 and res["coverage"] == 1.0
    assert res["metrics"]["objective"]["pass_rate"] == 0.5
    gap = res["optimality_gap"]
    assert gap["frac_worse_than_ref"] == 0.5 and gap["max"] == pytest.approx(0.1)
    assert res["regime_agreement"]["rate"] == 0.5
    assert len(cells) == 4


def test_paper_halfwidth_widens_tolerance(stats):
    paper = _src(stats, "paper", "paper", "5",
                 {(500.0, 250.0): {"fuel_mileage_lb_per_nmi": 1.55}})
    paper.halfwidth[(500.0, 250.0)] = {"fuel_mileage_lb_per_nmi": 0.05}
    truth = _src(stats, "truth", "truth", "5",
                 {(500.0, 250.0): {"fuel_mileage_lb_per_nmi": 1.529}})
    res, _ = stats.compare(truth, paper, ["fuel_mileage_lb_per_nmi"])
    assert res["metrics"]["fuel_mileage_lb_per_nmi"]["pass_rate"] == 1.0
    assert "optimality_gap" not in res


def test_agent_loader_reads_study_cases_csv(stats, tmp_path):
    study = tmp_path / "brelje-2018a-fig5"
    study.mkdir()
    with open(study / "cases.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "design_range_nm", "spec_energy_whkg", "status",
                    "runner", "run_ref", "mixed_objective", "MTOW_kg",
                    "fuel_burn_kg", "wall_time_s", "error"])
        w.writerow(["r500-e450", 500.0, 450.0, "converged", "omd", "run-1",
                    324.9, 5700.0, 267.9, 120.0, ""])
        w.writerow(["r550-e450", 550.0, 450.0, "failed", "omd", "", "", "", "", 90.0, "x"])
    src = stats.load_agent("arm", "", study, "5")
    k = (500.0, 450.0)
    assert src.ok[k] and not src.ok[(550.0, 450.0)]
    assert src.cells[k]["objective"] == pytest.approx(324.9)
    assert src.cells[k]["MTOW_lb"] == pytest.approx(5700.0 * stats.LB_PER_KG)
    assert src.cells[k]["fuel_mileage_lb_per_nmi"] == pytest.approx(
        267.9 * stats.LB_PER_KG / 500.0)
    assert src.meta["statuses"] == {"converged": 1, "failed": 1}


def test_agent_loader_reads_campaign_json(stats, tmp_path):
    d = tmp_path / "seed0" / "fig6"
    d.mkdir(parents=True)
    (d / "fig6-r500-e450.json").write_text(json.dumps({
        "case_id": "fig6-r500-e450", "design_range_nm": 500.0,
        "spec_energy_whkg": 450.0, "converged": True, "doc_per_nmi": 0.678,
        "MTOW_kg": 5696.0, "electric_energy_frac": 0.46}))
    src = stats.load_agent("arm", "0", d, "6")
    cell = src.cells[(500.0, 450.0)]
    assert cell["objective"] == pytest.approx(0.678)
    assert cell["electric_percent"] == pytest.approx(46.0)
