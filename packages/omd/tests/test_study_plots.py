"""Tests for study-level 2-axis trade-grid plots.

Covers the pandas-free grid mechanism (``_common``), the OCP panel policy +
derived columns (``plotting.ocp``), and the ``plot_study`` orchestrator
(axis gating, non-converged masking, provider dispatch, generic fallback).
These build study state on disk directly so they need no OpenMDAO run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml

import matplotlib
matplotlib.use("Agg")

from hangar.omd.plotting._common import (
    PanelSpec,
    pivot_grid,
    render_grid,
    to_float_array,
)
from hangar.omd.plotting.oas import derive_oas_study_columns, plot_oas_trade_grid
from hangar.omd.plotting.ocp import derive_study_columns, plot_ocp_trade_grid
from hangar.omd.plotting.pyc import plot_pyc_trade_grid
from hangar.omd.study_plots import _build_table, plot_study, study_plot_types

_KG_TO_LB = 2.20462


# ---------------------------------------------------------------------------
# Generic mechanism
# ---------------------------------------------------------------------------


def test_to_float_array_coerces_mixed_values():
    arr = to_float_array(["1.5", 2, None, "", "nope", 3.0])
    assert arr[0] == 1.5
    assert arr[1] == 2.0
    assert np.isnan(arr[2]) and np.isnan(arr[3]) and np.isnan(arr[4])
    assert arr[5] == 3.0


def test_pivot_grid_shape_and_holes():
    table = {
        "x": [300, 400, 300, 400],
        "y": [500, 500, 600, 600],
        "v": [1.0, 2.0, 3.0, None],  # one missing cell -> NaN hole
    }
    x, y, grid = pivot_grid(table, "x", "y", "v")
    assert list(x) == [300.0, 400.0]
    assert list(y) == [500.0, 600.0]
    assert grid.shape == (2, 2)
    assert grid[0, 0] == 1.0 and grid[0, 1] == 2.0 and grid[1, 0] == 3.0
    assert np.isnan(grid[1, 1])


def test_pivot_grid_last_wins_on_duplicate():
    table = {"x": [300, 300], "y": [500, 500], "v": [1.0, 9.0]}
    _, _, grid = pivot_grid(table, "x", "y", "v")
    assert grid[0, 0] == 9.0


def test_render_grid_returns_figure_with_panel_axes():
    table = {"x": [1, 2, 1, 2], "y": [1, 1, 2, 2], "a": [1, 2, 3, 4],
             "b": [4, 3, 2, 1]}
    fig = render_grid(table, "x", "y", [PanelSpec("a"), PanelSpec("b")],
                      style="paper")
    # 2 panels with colorbars -> at least 2 data axes present
    assert len(fig.axes) >= 2


def test_render_grid_rejects_empty_panels_and_bad_style():
    table = {"x": [1], "y": [1], "a": [1]}
    with pytest.raises(ValueError):
        render_grid(table, "x", "y", [])
    with pytest.raises(ValueError):
        render_grid(table, "x", "y", [PanelSpec("a")], style="nope")


# ---------------------------------------------------------------------------
# OCP panel policy + derived columns
# ---------------------------------------------------------------------------


def _ocp_table():
    return {
        "design_range_nm": [300.0, 500.0],
        "spec_energy_whkg": [400.0, 400.0],
        "MTOW_kg": [4000.0, 5000.0],
        "fuel_burn_kg": [200.0, 300.0],
        "W_battery_kg": [100.0, 500.0],
        "cruise_hybridization": [0.1, 0.7],
        "engine_rating_hp": [800.0, 900.0],
        "motor_rating_hp": [500.0, 600.0],
        "generator_rating_hp": [700.0, 800.0],
    }


def test_derive_study_columns_formulas():
    out = derive_study_columns(_ocp_table())
    assert out["MTOW_lb"][0] == pytest.approx(4000.0 * _KG_TO_LB)
    assert out["fuel_mileage_lb_per_nmi"][0] == pytest.approx(
        200.0 * _KG_TO_LB / 300.0)
    assert out["electric_percent"][1] == pytest.approx(70.0)
    # offline DOC estimate fires (no recorded doc_per_nmi) and is positive
    assert "doc_per_nmi" in out
    assert out["doc_per_nmi"][0] > 0


def test_derive_keeps_recorded_doc():
    table = _ocp_table()
    table["doc_per_nmi"] = [0.42, 0.55]
    out = derive_study_columns(table)
    assert out["doc_per_nmi"][0] == pytest.approx(0.42)


def test_plot_ocp_trade_grid_skips_missing_panels():
    table = _ocp_table()
    # drop the cost-model inputs so DOC cannot be derived -> 3 panels, not 4
    for k in ("engine_rating_hp", "motor_rating_hp", "generator_rating_hp"):
        del table[k]
    fig = plot_ocp_trade_grid(table, "design_range_nm", "spec_energy_whkg")
    titles = [ax.get_title() for ax in fig.axes if ax.get_title()]
    assert not any("DOC" in t for t in titles)
    assert any("Fuel mileage" in t for t in titles)


# ---------------------------------------------------------------------------
# plot_study orchestrator (synthetic study state on disk)
# ---------------------------------------------------------------------------


def _write_study(tmp_path, monkeypatch, *, axes, component_type, cases,
                 study_id="syn-study"):
    """Write a minimal study state + spec + one case plan; return study_id."""
    monkeypatch.setenv("HANGAR_STUDY_DIR", str(tmp_path / "studies"))
    sdir = tmp_path / "studies" / study_id
    (sdir / "cases" / "c0").mkdir(parents=True)

    matrix = {
        "id_template": "c{%s:g}" % axes[0],
        "axes": {a: {"values": [1.0, 2.0]} for a in axes},
        "bind": {a: [f"operating_points.{a}"] for a in axes},
    }
    spec = {
        "metadata": {"id": study_id, "name": "syn", "version": 1},
        "defaults": {"runner": "omd",
                     "spec": {"plan": "base/plan.yaml", "mode": "analysis"}},
        "cases": [{"matrix": matrix}],
    }
    (sdir / "study.yaml").write_text(yaml.safe_dump(spec))
    (sdir / "cases" / "c0" / "plan.yaml").write_text(
        yaml.safe_dump({"components": [{"id": "m", "type": component_type}]}))

    state = {"study_id": study_id, "version": 1, "owner": "",
             "created_at": "t", "updated_at": "t", "cases": cases}
    (sdir / "state.json").write_text(json.dumps(state))
    return study_id


def _ocp_cases():
    """2x2 grid: three converged + one failed (its outputs must be masked)."""
    cases = {}
    pts = [(300.0, 400.0, "converged"), (500.0, 400.0, "converged"),
           (300.0, 500.0, "converged"), (500.0, 500.0, "failed")]
    for i, (rng, energy, status) in enumerate(pts):
        outputs = {} if status == "failed" else {
            "MTOW_kg": 4000.0 + 100 * i, "fuel_burn_kg": 200.0 + 10 * i,
            "W_battery_kg": 100.0 + 50 * i, "cruise_hybridization": 0.1 + 0.1 * i,
            "engine_rating_hp": 800.0, "motor_rating_hp": 500.0,
            "generator_rating_hp": 700.0,
        }
        cases[f"k{i}"] = {
            "case_id": f"c{i}", "runner": "omd",
            "params": {"design_range_nm": rng, "spec_energy_whkg": energy},
            "status": status, "outputs": outputs, "in_spec": True,
        }
    return cases


def test_plot_study_ocp_provider(tmp_path, monkeypatch):
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["design_range_nm", "spec_energy_whkg"],
                       component_type="ocp/FullMission", cases=_ocp_cases())
    result = plot_study(sid)
    assert result["component_type"] == "ocp/FullMission"
    assert result["axes"] == ["design_range_nm", "spec_energy_whkg"]
    out = Path(result["saved"]["trade_grid"])
    assert out.exists() and out.stat().st_size > 0


def test_plot_study_masks_failed_case(tmp_path, monkeypatch):
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["design_range_nm", "spec_energy_whkg"],
                       component_type="ocp/FullMission", cases=_ocp_cases())
    from hangar.sdk.study import StudyStore

    state = StudyStore(sid).load_state()
    table = _build_table(state, ["design_range_nm", "spec_energy_whkg"])
    # the failed case contributes no MTOW_kg value -> a NaN hole in the grid
    mtow = to_float_array(table["MTOW_kg"])
    assert np.isnan(mtow).sum() == 1


def test_plot_study_requires_two_axes(tmp_path, monkeypatch):
    cases = {"k0": {"case_id": "c0", "runner": "omd",
                    "params": {"design_range_nm": 1.0},
                    "status": "converged",
                    "outputs": {"MTOW_kg": 4000.0}, "in_spec": True}}
    sid = _write_study(tmp_path, monkeypatch, axes=["design_range_nm"],
                       component_type="ocp/FullMission", cases=cases,
                       study_id="one-axis")
    with pytest.raises(ValueError, match="exactly 2 numeric axes"):
        plot_study(sid)


def test_study_plot_types_provider(tmp_path, monkeypatch):
    # OCP study -> provider plot name(s), listed without rendering.
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["design_range_nm", "spec_energy_whkg"],
                       component_type="ocp/FullMission", cases=_ocp_cases())
    assert study_plot_types(sid) == ["trade_grid"]


def test_study_plot_types_generic_and_gated(tmp_path, monkeypatch):
    # No provider + numeric outputs -> generic "grid"; <2 axes -> empty.
    cases = {f"k{i}": {
        "case_id": f"c{i}", "runner": "omd",
        "params": {"design_range_nm": x, "spec_energy_whkg": y},
        "status": "converged", "outputs": {"f_xy": float(i)}, "in_spec": True,
    } for i, (x, y) in enumerate([(1.0, 1.0), (2.0, 1.0), (1.0, 2.0), (2.0, 2.0)])}
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["design_range_nm", "spec_energy_whkg"],
                       component_type="paraboloid/Paraboloid", cases=cases,
                       study_id="generic-types")
    assert study_plot_types(sid) == ["grid"]

    one = {"k0": {"case_id": "c0", "runner": "omd",
                  "params": {"design_range_nm": 1.0}, "status": "converged",
                  "outputs": {"MTOW_kg": 4000.0}, "in_spec": True}}
    sid1 = _write_study(tmp_path, monkeypatch, axes=["design_range_nm"],
                        component_type="ocp/FullMission", cases=one,
                        study_id="one-axis-types")
    assert study_plot_types(sid1) == []  # never raises; just empty


def test_study_plot_types_missing_study_is_empty():
    assert study_plot_types("does-not-exist") == []


# ---------------------------------------------------------------------------
# OAS study-plot provider
# ---------------------------------------------------------------------------


def _oas_cases(outputs_keys=("CL", "CD", "CM", "structural_mass", "failure")):
    """2x2 grid: three converged + one failed (its outputs are masked)."""
    base = {"CL": 0.5, "CD": 0.02, "CM": -0.1,
            "structural_mass": 120.0, "failure": -0.3}
    cases = {}
    pts = [(8.0, 0.10, "converged"), (12.0, 0.10, "converged"),
           (8.0, 0.14, "converged"), (12.0, 0.14, "failed")]
    for i, (ar, thick, status) in enumerate(pts):
        outputs = {} if status == "failed" else {
            k: base[k] + 0.01 * i for k in outputs_keys}
        cases[f"k{i}"] = {
            "case_id": f"c{i}", "runner": "omd",
            "params": {"aspect_ratio": ar, "skin_thickness": thick},
            "status": status, "outputs": outputs, "in_spec": True,
        }
    return cases


def test_derive_oas_study_columns():
    out = derive_oas_study_columns({"CL": [0.5, 1.0], "CD": [0.02, 0.04]})
    assert out["L_over_D"][0] == pytest.approx(25.0)
    assert out["L_over_D"][1] == pytest.approx(25.0)


def test_plot_oas_trade_grid_skips_missing_panels():
    # aero-only table: no structural_mass / failure -> those panels skipped.
    table = {"aspect_ratio": [8.0, 12.0, 8.0, 12.0],
             "skin_thickness": [0.1, 0.1, 0.14, 0.14],
             "CL": [0.5, 0.6, 0.55, 0.65], "CD": [0.02, 0.025, 0.022, 0.027]}
    fig = plot_oas_trade_grid(table, "aspect_ratio", "skin_thickness")
    titles = [ax.get_title() for ax in fig.axes if ax.get_title()]
    assert any("L/D" in t for t in titles)
    assert not any("Structural mass" in t for t in titles)


def test_plot_study_oas_provider(tmp_path, monkeypatch):
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["aspect_ratio", "skin_thickness"],
                       component_type="oas/AerostructPoint", cases=_oas_cases(),
                       study_id="oas-study")
    result = plot_study(sid)
    assert result["component_type"] == "oas/AerostructPoint"
    out = Path(result["saved"]["trade_grid"])
    assert out.exists() and out.stat().st_size > 0


def test_study_plot_types_oas_provider(tmp_path, monkeypatch):
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["aspect_ratio", "skin_thickness"],
                       component_type="oas/AeroPoint",
                       cases=_oas_cases(outputs_keys=("CL", "CD", "CM")),
                       study_id="oas-types")
    assert study_plot_types(sid) == ["trade_grid"]


# ---------------------------------------------------------------------------
# pyCycle study-plot provider
# ---------------------------------------------------------------------------


def _pyc_cases():
    """2x2 design-point grid over comp_PR x T4_target; one failed cell."""
    base = {"TSFC": 0.8, "Fn": 11800.0, "OPR": 13.5, "Wfuel": 9400.0}
    cases = {}
    pts = [(12.0, 2300.0, "converged"), (16.0, 2300.0, "converged"),
           (12.0, 2500.0, "converged"), (16.0, 2500.0, "failed")]
    for i, (pr, t4, status) in enumerate(pts):
        outputs = {} if status == "failed" else {
            "TSFC": base["TSFC"] - 0.01 * i, "Fn": base["Fn"] + 50 * i,
            "OPR": base["OPR"] + 0.5 * i, "Wfuel": base["Wfuel"] + 20 * i}
        cases[f"k{i}"] = {
            "case_id": f"c{i}", "runner": "omd",
            "params": {"comp_PR": pr, "T4_target": t4},
            "status": status, "outputs": outputs, "in_spec": True,
        }
    return cases


def test_plot_pyc_trade_grid_renders():
    table = {"comp_PR": [12.0, 16.0, 12.0, 16.0],
             "T4_target": [2300.0, 2300.0, 2500.0, 2500.0],
             "TSFC": [0.8, 0.79, 0.81, 0.78], "Fn": [11800, 11850, 11900, 12000],
             "OPR": [13.5, 14.0, 13.8, 14.5]}
    fig = plot_pyc_trade_grid(table, "comp_PR", "T4_target")
    titles = [ax.get_title() for ax in fig.axes if ax.get_title()]
    assert any("TSFC" in t for t in titles)
    assert any("thrust" in t.lower() for t in titles)


def test_plot_study_pyc_provider(tmp_path, monkeypatch):
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["comp_PR", "T4_target"],
                       component_type="pyc/TurbojetDesign", cases=_pyc_cases(),
                       study_id="pyc-study")
    result = plot_study(sid)
    assert result["component_type"] == "pyc/TurbojetDesign"
    out = Path(result["saved"]["trade_grid"])
    assert out.exists() and out.stat().st_size > 0


def test_study_plot_types_pyc_provider(tmp_path, monkeypatch):
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["comp_PR", "T4_target"],
                       component_type="pyc/TurbojetDesign", cases=_pyc_cases(),
                       study_id="pyc-types")
    assert study_plot_types(sid) == ["trade_grid"]


def test_plot_study_generic_fallback(tmp_path, monkeypatch):
    cases = {}
    for i, (x, y) in enumerate([(1.0, 1.0), (2.0, 1.0), (1.0, 2.0), (2.0, 2.0)]):
        cases[f"k{i}"] = {
            "case_id": f"c{i}", "runner": "omd",
            "params": {"design_range_nm": x, "spec_energy_whkg": y},
            "status": "converged", "outputs": {"f_xy": float(i)},
            "in_spec": True,
        }
    sid = _write_study(tmp_path, monkeypatch,
                       axes=["design_range_nm", "spec_energy_whkg"],
                       component_type="paraboloid/Paraboloid", cases=cases,
                       study_id="generic-study")
    result = plot_study(sid)
    # paraboloid has no study-plot provider -> generic per-column grid
    assert "grid" in result["saved"]
    assert Path(result["saved"]["grid"]).exists()
