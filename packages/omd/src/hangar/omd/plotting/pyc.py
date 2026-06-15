"""pyCycle-specific plot types for engine analysis.

Reads data from OpenMDAO recorder files and produces matplotlib
figures. Plot functions follow the omd convention: accept
(recorder_path, **kwargs) and return a Figure.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from hangar.omd.plotting._common import (
    PanelSpec,
    Table,
    find_outputs,
    get_reader_and_final_case,
    render_grid,
    to_float_array,
)

logger = logging.getLogger(__name__)

_FIG_WIDTH = 6.0
_FIG_HEIGHT = 3.6


def _make_fig(title: str, run_id: str = "", **fig_kwargs) -> tuple:
    """Create a figure with suptitle matching omd conventions."""
    fig_kwargs.setdefault("figsize", (_FIG_WIDTH, _FIG_HEIGHT))
    fig, ax = plt.subplots(**fig_kwargs)
    suptitle = title
    if run_id:
        suptitle += f"\n({run_id})"
    fig.suptitle(suptitle, fontsize=9, y=0.98)
    return fig, ax


def _extract_station_name(path: str) -> str:
    """Extract a short station label from a full OpenMDAO path.

    e.g. 'DESIGN.inlet.Fl_O:tot:T' -> 'inlet'
         'cycle.DESIGN.burner.Fl_O:tot:P' -> 'burner'
    """
    # Pattern: look for the component name before .Fl_O
    m = re.search(r"\.([^.]+)\.Fl_O", path)
    if m:
        return m.group(1)
    # Fallback: second-to-last segment
    parts = path.rsplit(".", 2)
    return parts[-2] if len(parts) >= 2 else path


def _extract_component_name(path: str) -> str:
    """Extract component name from a performance/map path.

    e.g. 'DESIGN.comp.eff' -> 'comp'
         'cycle.DESIGN.hpc.PR' -> 'hpc'
    """
    parts = path.split(".")
    if len(parts) >= 2:
        return parts[-2]
    return path


# ---------------------------------------------------------------------------
# Station properties
# ---------------------------------------------------------------------------


def plot_station_properties(
    recorder_path: Path,
    **kwargs,
) -> plt.Figure:
    """Grouped bar chart of total pressure and temperature at each station.

    Discovers pyCycle flow stations by searching for ``*Fl_O:tot:P`` and
    ``*Fl_O:tot:T`` patterns in the recorder output.
    """
    reader, case = get_reader_and_final_case(recorder_path)
    if case is None:
        fig, ax = _make_fig("Station Properties (no data)", **kwargs)
        return fig

    run_id = kwargs.get("run_id", "")

    # Find total pressure and temperature at all stations
    pt_matches = find_outputs(case, "*Fl_O:tot:P")
    tt_matches = find_outputs(case, "*Fl_O:tot:T")

    if not pt_matches and not tt_matches:
        fig, ax = _make_fig("Station Properties (no pyCycle data)", run_id=run_id)
        ax.text(0.5, 0.5, "No pyCycle flow station data found",
                ha="center", va="center", transform=ax.transAxes)
        return fig

    # Build station -> value maps
    pt_by_station = {}
    for path, val in pt_matches:
        station = _extract_station_name(path)
        pt_by_station[station] = float(np.atleast_1d(val).flat[0])

    tt_by_station = {}
    for path, val in tt_matches:
        station = _extract_station_name(path)
        tt_by_station[station] = float(np.atleast_1d(val).flat[0])

    # Merge and order stations by pressure (engine flow order)
    all_stations = list(dict.fromkeys(
        list(pt_by_station.keys()) + list(tt_by_station.keys())
    ))
    # Sort by total pressure descending (highest pressure in middle of engine)
    all_stations.sort(key=lambda s: pt_by_station.get(s, 0))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(_FIG_WIDTH, _FIG_HEIGHT * 1.4),
                                    sharex=True)
    suptitle = "Station Properties"
    if run_id:
        suptitle += f"\n({run_id})"
    fig.suptitle(suptitle, fontsize=9, y=0.98)

    x = np.arange(len(all_stations))
    width = 0.6

    # Total pressure
    pt_vals = [pt_by_station.get(s, 0) for s in all_stations]
    ax1.bar(x, pt_vals, width, color="steelblue", alpha=0.8)
    ax1.set_ylabel("Total Pressure (psi)")
    ax1.grid(axis="y", alpha=0.3)

    # Total temperature
    tt_vals = [tt_by_station.get(s, 0) for s in all_stations]
    ax2.bar(x, tt_vals, width, color="firebrick", alpha=0.8)
    ax2.set_ylabel("Total Temperature (degR)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(all_stations, rotation=45, ha="right", fontsize=7)
    ax2.grid(axis="y", alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig


# ---------------------------------------------------------------------------
# Component efficiency and pressure ratio
# ---------------------------------------------------------------------------


def plot_component_efficiency(
    recorder_path: Path,
    **kwargs,
) -> plt.Figure:
    """Bar chart of compressor/turbine efficiency and pressure ratio.

    Searches for ``*eff*``, ``*PR`` patterns among pyCycle components.
    """
    reader, case = get_reader_and_final_case(recorder_path)
    if case is None:
        fig, ax = _make_fig("Component Performance (no data)", **kwargs)
        return fig

    run_id = kwargs.get("run_id", "")

    # Find efficiencies and pressure ratios
    eff_matches = find_outputs(case, "*DESIGN*.eff")
    pr_matches = find_outputs(case, "*DESIGN*.PR")

    if not eff_matches and not pr_matches:
        fig, ax = _make_fig("Component Performance (no data)", run_id=run_id)
        ax.text(0.5, 0.5, "No pyCycle component data found",
                ha="center", va="center", transform=ax.transAxes)
        return fig

    fig, axes = plt.subplots(1, 2, figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    suptitle = "Component Performance"
    if run_id:
        suptitle += f"\n({run_id})"
    fig.suptitle(suptitle, fontsize=9, y=0.98)

    # Efficiency bars
    ax_eff = axes[0]
    if eff_matches:
        labels = [_extract_component_name(p) for p, _ in eff_matches]
        vals = [float(np.atleast_1d(v).flat[0]) for _, v in eff_matches]
        x = np.arange(len(labels))
        ax_eff.bar(x, vals, 0.6, color="teal", alpha=0.8)
        ax_eff.set_xticks(x)
        ax_eff.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax_eff.set_ylim(0, 1.05)
    ax_eff.set_ylabel("Efficiency")
    ax_eff.set_title("Polytropic Efficiency", fontsize=8)
    ax_eff.grid(axis="y", alpha=0.3)

    # Pressure ratio bars
    ax_pr = axes[1]
    if pr_matches:
        labels = [_extract_component_name(p) for p, _ in pr_matches]
        vals = [float(np.atleast_1d(v).flat[0]) for _, v in pr_matches]
        x = np.arange(len(labels))
        ax_pr.bar(x, vals, 0.6, color="darkorange", alpha=0.8)
        ax_pr.set_xticks(x)
        ax_pr.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax_pr.set_ylabel("Pressure Ratio")
    ax_pr.set_title("Pressure Ratio", fontsize=8)
    ax_pr.grid(axis="y", alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.90])
    return fig


# ---------------------------------------------------------------------------
# Registry export
# ---------------------------------------------------------------------------

PYC_PLOTS: dict[str, callable] = {
    "station_properties": plot_station_properties,
    "component_efficiency": plot_component_efficiency,
}


# ---------------------------------------------------------------------------
# Study-level plots (2-axis trade grids over a study's cases.csv)
# ---------------------------------------------------------------------------
#
# A study-plot provider is a dict mapping a plot name to a callable
#   (study_table, x_axis, y_axis, **kwargs) -> Figure
# distinct from the per-run providers above (which take a recorder path). The
# pyc provider renders an engine cycle trade space (TSFC, thrust, OPR, fuel
# flow) over two design axes. It imports no upstream solver, so it registers
# and renders even where pycycle is absent.


def _col(table: Table, name: str):
    """Column as a float ndarray, or None if absent."""
    if name not in table:
        return None
    return to_float_array(table[name])


def _has_finite(arr) -> bool:
    return arr is not None and bool(np.isfinite(arr).any())


def derive_pyc_study_columns(table: Table) -> dict:
    """Carry the raw case columns through as float arrays.

    A passthrough today (the pyc trade-grid panels read recorded outputs
    directly); kept for symmetry with the OAS/OCP providers and as the hook
    for future derived metrics (e.g. specific thrust).
    """
    return {k: to_float_array(v) for k, v in table.items()}


# Panels: (column, label, vmin, vmax, overlay_contours). Superset; panels whose
# source column is absent or all-NaN are skipped. Column names must match the
# study's declared outputs.
_PYC_STUDY_PANELS = [
    ("TSFC", "TSFC (lbm/lbf/hr)", None, None, True),
    ("Fn", "Net thrust Fn (lbf)", None, None, False),
    ("OPR", "Overall pressure ratio", None, None, False),
    ("Wfuel", "Fuel flow Wfuel (lbm/s)", 0.0, None, False),
]


def plot_pyc_trade_grid(
    study_table: Table, x_axis: str, y_axis: str, *,
    style: str = "paper", suptitle: str | None = None, **kwargs,
) -> plt.Figure:
    """Render a pyCycle engine trade grid from a study's case table.

    Args:
        study_table: columnar case table, non-converged cells already NaN'd
            by the caller.
        x_axis, y_axis: the two numeric grid-axis columns.
        style: "paper" (pcolormesh) or "contour".
        suptitle: optional figure title.

    Returns the Figure. Panels whose source column is missing are skipped.
    """
    table = derive_pyc_study_columns(study_table)
    panels = [
        PanelSpec(col, label, vmin, vmax, overlay)
        for (col, label, vmin, vmax, overlay) in _PYC_STUDY_PANELS
        if _has_finite(table.get(col))
    ]
    if not panels:
        raise ValueError(
            "no pyc study panels available; expected columns like TSFC, Fn, "
            "OPR in the case table")
    return render_grid(
        table, x_axis, y_axis, panels, style=style,
        x_label=x_axis, y_label=y_axis, suptitle=suptitle,
    )


PYC_STUDY_PLOTS: dict = {
    "trade_grid": plot_pyc_trade_grid,
}
