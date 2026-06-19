"""OCP-specific plot types for mission analyses.

Reads data from OpenMDAO recorder files and produces matplotlib
figures. Plot functions follow the omd convention: accept
(recorder_path, **kwargs) and return a Figure.
"""

from __future__ import annotations

import logging
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

_KG_TO_LB = 2.20462

# Phase ordering and styling (matches ocp/viz/plotting.py)
_PHASE_ORDER = [
    "v0v1", "v1vr", "rotate",
    "climb", "cruise", "descent",
    "reserve_climb", "reserve_cruise", "reserve_descent",
    "loiter",
]

_PHASE_LABELS = {
    "v0v1": "V0-V1",
    "v1vr": "V1-Vr",
    "v1v0": "Rejected TO",
    "rotate": "Rotate",
    "climb": "Climb",
    "cruise": "Cruise",
    "descent": "Descent",
    "reserve_climb": "Rsv Climb",
    "reserve_cruise": "Rsv Cruise",
    "reserve_descent": "Rsv Descent",
    "loiter": "Loiter",
}


def _phase_label(phase: str) -> str:
    return _PHASE_LABELS.get(phase, phase.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Trajectory extraction from recorder
# ---------------------------------------------------------------------------


def _find_phase_var(outputs: dict, phase: str, suffix: str) -> np.ndarray | None:
    """Find a variable for a given phase in recorder outputs.

    Recorder uses absolute paths like ``analysis.climb.ode_integ_phase.fltcond|h``
    rather than promoted paths like ``climb.fltcond|h``. This searches for any
    output path that contains the phase name and ends with the suffix.
    """
    # Try exact promoted name first
    promoted = f"{phase}.{suffix}"
    if promoted in outputs:
        info = outputs[promoted]
        val = info.get("val", info.get("value"))
        if val is not None:
            return np.atleast_1d(val).flatten()

    # Search by suffix pattern in absolute paths
    phase_dot = f".{phase}."
    for name, info in outputs.items():
        if phase_dot in name and name.endswith(suffix):
            val = info.get("val", info.get("value"))
            if val is not None:
                return np.atleast_1d(val).flatten()

    return None


def _extract_trajectory_from_case(case, phases: list[str]) -> dict:
    """Extract per-phase trajectory data from a recorder case.

    Returns a dict of {phase_name: {var_name: array}} where var_name
    is one of the canonical names (altitude_ft, airspeed_kn, etc.).
    """
    outputs = case.list_outputs(out_stream=None, return_format="dict")

    # Mission boundary conditions such as fltcond|Ueas (equivalent airspeed) and
    # fltcond|vs (vertical speed) are prescribed as INPUTS, not outputs, so
    # list_outputs() alone misses them -- leaving the V/S panel blank and forcing
    # the airspeed trace to fall back to fltcond|Utrue (true airspeed). Merge the
    # inputs in as a fallback, letting outputs win on any key collision so the
    # integrated trajectory (altitude, range, fuel) is unaffected.
    try:
        inputs = case.list_inputs(out_stream=None, return_format="dict")
    except Exception:
        inputs = {}
    for name, info in inputs.items():
        outputs.setdefault(name, info)

    trajectory = {}
    for phase in phases:
        phase_data: dict = {}

        # Map OCP output suffixes to canonical names
        var_map = [
            ("fltcond|h", "altitude_m"),
            ("fltcond|Ueas", "airspeed_ms"),
            ("fltcond|vs", "vs_ms"),
            ("fltcond|Utrue", "airspeed_true_ms"),
            ("throttle", "throttle"),
            ("fuel_used", "fuel_used_kg"),
            ("range", "range_m"),
            ("battery_SOC", "battery_SOC"),
        ]

        for suffix, canon_name in var_map:
            val = _find_phase_var(outputs, phase, suffix)
            if val is not None:
                phase_data[canon_name] = val

        # Convert units for plotting
        if "altitude_m" in phase_data:
            phase_data["altitude_ft"] = phase_data["altitude_m"] * 3.28084
        if "airspeed_ms" in phase_data:
            phase_data["airspeed_kn"] = phase_data["airspeed_ms"] * 1.94384
        elif "airspeed_true_ms" in phase_data:
            phase_data["airspeed_kn"] = phase_data["airspeed_true_ms"] * 1.94384
            phase_data["_airspeed_is_tas"] = True
        if "vs_ms" in phase_data:
            phase_data["vertical_speed_ftmin"] = phase_data["vs_ms"] * 196.85
        if "range_m" in phase_data:
            phase_data["range_NM"] = phase_data["range_m"] / 1852.0

        if phase_data:
            trajectory[phase] = phase_data

    return trajectory


def _extract_mission_scalars(case, outputs: dict) -> dict:
    """Extract key scalar results from the recorder final case."""
    scalars: dict = {}

    def _get(suffix: str, phase: str | None = None) -> float | None:
        """Find a scalar value by suffix, optionally scoped to a phase."""
        # Try promoted name first
        if phase:
            promoted = f"{phase}.{suffix}"
        else:
            promoted = suffix
        if promoted in outputs:
            info = outputs[promoted]
            val = info.get("val", info.get("value"))
            if val is not None:
                return float(np.atleast_1d(val).flat[0])

        # Search absolute paths
        for name, info in outputs.items():
            match = False
            if phase:
                match = f".{phase}." in name and name.endswith(suffix)
            else:
                match = name.endswith(suffix)
            if match:
                val = info.get("val", info.get("value"))
                if val is not None:
                    return float(np.atleast_1d(val).flat[0])
        return None

    # Fuel burn (last phase fuel_used_final)
    for phase in reversed(_PHASE_ORDER):
        val = _get("fuel_used_final", phase)
        if val is not None:
            scalars["fuel_burn_kg"] = val
            break

    oew = _get("OEW", "climb")
    if oew is not None:
        scalars["OEW_kg"] = oew

    # MTOW from aircraft data
    for name, info in outputs.items():
        if name.endswith("ac|weights|MTOW") or "ac|weights|MTOW" in name:
            val = info.get("val", info.get("value"))
            if val is not None:
                scalars["MTOW_kg"] = float(np.atleast_1d(val).flat[0])
                break

    # TOFL
    tofl = _get("range_final", "rotate")
    if tofl is not None:
        scalars["TOFL_m"] = tofl

    # OEW from OpenConcept's weight model is stored in lb in the recorder
    # (no unit metadata in problem-level recordings). Detect by comparing
    # to MTOW -- if OEW > MTOW, it's almost certainly in lb.
    if "OEW_kg" in scalars and "MTOW_kg" in scalars:
        if scalars["OEW_kg"] > scalars["MTOW_kg"] * 1.1:
            scalars["OEW_kg"] = scalars["OEW_kg"] * 0.453592

    return scalars


def _ordered_phases(trajectory: dict) -> list[str]:
    """Return phase names present in trajectory, in canonical order."""
    ordered = [p for p in _PHASE_ORDER if p in trajectory]
    for p in trajectory:
        if p not in ordered:
            ordered.append(p)
    return ordered


# ---------------------------------------------------------------------------
# Plot: mission_profile
# ---------------------------------------------------------------------------


def plot_mission_profile(recorder_path: str | Path, **kwargs) -> plt.Figure:
    """2x3 grid: altitude, V/S, airspeed, throttle, fuel used, battery SOC."""
    run_id = kwargs.get("run_id", "")
    phases = kwargs.get("phases", list(_PHASE_ORDER))

    reader, case = get_reader_and_final_case(Path(recorder_path))
    trajectory = _extract_trajectory_from_case(case, phases)

    if not trajectory:
        raise ValueError("No trajectory data found in recorder")

    has_battery = any(
        "battery_SOC" in pd for pd in trajectory.values()
    )

    fig, axes = plt.subplots(2, 3, figsize=(10.0, 6.0))
    fig.suptitle(
        f"Mission Profile\n(run_id: {run_id})",
        fontsize=9, y=0.99,
    )

    # Check if airspeed is TAS (no EAS available)
    _is_tas = any(
        pd.get("_airspeed_is_tas") for pd in trajectory.values()
    )
    airspeed_label = "True Airspeed (kn)" if _is_tas else "EAS (kn)"

    panels = [
        ("altitude_ft", "Altitude (ft)"),
        ("vertical_speed_ftmin", "Vertical Speed (ft/min)"),
        ("airspeed_kn", airspeed_label),
        ("throttle", "Throttle"),
        ("fuel_used_kg", "Fuel Used (kg)"),
    ]
    if has_battery:
        panels.append(("battery_SOC", "Battery SOC"))

    for idx, (var, ylabel) in enumerate(panels):
        ax = axes.flat[idx]
        for phase in _ordered_phases(trajectory):
            pd = trajectory[phase]
            rng = pd.get("range_NM")
            vals = pd.get(var)
            if rng is None or vals is None:
                continue
            ax.plot(rng, vals, "-o", color="tab:blue", markersize=2.0, linewidth=1.5)
        ax.set_ylabel(ylabel, fontsize=8)
        ax.set_xlabel("Range (NM)", fontsize=7)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3)

    if not has_battery:
        axes.flat[5].set_visible(False)

    # Phase boundary annotations on altitude panel
    for phase in _ordered_phases(trajectory):
        pd = trajectory[phase]
        rng = pd.get("range_NM")
        if rng is not None and len(rng) > 0:
            bx = rng[0]
            for ax in axes.flat[:len(panels)]:
                ax.axvline(bx, color="#94a3b8", linestyle=":", linewidth=0.6, alpha=0.4)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig


# ---------------------------------------------------------------------------
# Plot: weight_breakdown
# ---------------------------------------------------------------------------


def plot_weight_breakdown(recorder_path: str | Path, **kwargs) -> plt.Figure:
    """Horizontal bar chart decomposing MTOW into OEW, fuel, and remainder."""
    run_id = kwargs.get("run_id", "")
    phases = kwargs.get("phases", list(_PHASE_ORDER))

    reader, case = get_reader_and_final_case(Path(recorder_path))
    outputs = case.list_outputs(out_stream=None, return_format="dict")
    scalars = _extract_mission_scalars(case, outputs)

    mtow = scalars.get("MTOW_kg")
    oew = scalars.get("OEW_kg")
    fuel = scalars.get("fuel_burn_kg", 0.0)

    if mtow is None or oew is None:
        raise ValueError("MTOW and OEW required for weight breakdown")

    mtow, oew = float(mtow), float(oew)
    remainder = mtow - oew - fuel

    labels = ["OEW", "Fuel", "Payload/Other"]
    values = [oew, fuel, max(0.0, remainder)]
    colors = ["#3b82f6", "#ef4444", "#22c55e"]

    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    fig.suptitle(
        f"Weight Breakdown\n(run_id: {run_id})",
        fontsize=9, y=0.99,
    )

    y_pos = np.arange(len(labels))
    bars = ax.barh(y_pos, values, color=colors, height=0.5)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + mtow * 0.01, bar.get_y() + bar.get_height() / 2,
            f"{val:.0f} kg", va="center", fontsize=8,
        )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Mass (kg)", fontsize=8)
    ax.set_xlim(0, mtow * 1.15)
    ax.axvline(mtow, color="black", linestyle="--", linewidth=0.8, label=f"MTOW = {mtow:.0f} kg")
    ax.legend(fontsize=7, loc="lower right")
    ax.tick_params(labelsize=7)
    ax.grid(True, axis="x", alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig


# ---------------------------------------------------------------------------
# Plot: performance_summary
# ---------------------------------------------------------------------------


def plot_performance_summary(recorder_path: str | Path, **kwargs) -> plt.Figure:
    """Text card showing key mission performance metrics."""
    run_id = kwargs.get("run_id", "")
    phases = kwargs.get("phases", list(_PHASE_ORDER))

    reader, case = get_reader_and_final_case(Path(recorder_path))
    outputs = case.list_outputs(out_stream=None, return_format="dict")
    scalars = _extract_mission_scalars(case, outputs)

    def _fmt(key: str, unit: str, decimals: int = 1) -> str:
        val = scalars.get(key)
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f} {unit}"

    lines = [
        f"MTOW:       {_fmt('MTOW_kg', 'kg', 0)}",
        f"OEW:        {_fmt('OEW_kg', 'kg', 0)}",
        f"Fuel Burn:  {_fmt('fuel_burn_kg', 'kg', 1)}",
    ]
    if "TOFL_m" in scalars:
        lines.append(f"TOFL:       {_fmt('TOFL_m', 'm', 0)}")

    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    fig.suptitle(
        f"Performance Summary\n(run_id: {run_id})",
        fontsize=9, y=0.99,
    )

    ax.axis("off")
    text = "\n".join(lines)
    ax.text(
        0.05, 0.95, text,
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment="top",
        fontfamily="monospace",
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "#f8fafc", "edgecolor": "#cbd5e1"},
    )

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return fig


# ---------------------------------------------------------------------------
# Plot provider registry
# ---------------------------------------------------------------------------

OCP_MISSION_PLOTS: dict = {
    "mission_profile": plot_mission_profile,
    "weight_breakdown": plot_weight_breakdown,
    "performance_summary": plot_performance_summary,
}


# ---------------------------------------------------------------------------
# Study-level plots (2-axis trade grids over a study's cases.csv)
# ---------------------------------------------------------------------------
#
# A study-plot provider is a dict mapping a plot name to a callable
#   (study_df, x_axis, y_axis, **kwargs) -> Figure
# distinct from the per-run providers above (which take a recorder path).
# The OCP provider renders the Brelje 2018a Fig 5/6 style four-panel trade
# space and owns the mission-specific derived columns the raw cases.csv
# lacks (lb-unit weights, fuel mileage, electric fraction, offline DOC).


def _col(table: Table, name: str):
    """Column as a float ndarray, or None if absent."""
    if name not in table:
        return None
    return to_float_array(table[name])


def _has_finite(arr) -> bool:
    return arr is not None and bool(np.isfinite(arr).any())


def derive_study_columns(
    table: Table, range_col: str = "design_range_nm",
    energy_col: str = "spec_energy_whkg",
) -> dict:
    """Add the OCP-mission derived columns used by the Fig 5/6 panels.

    Returns a new columnar table (column -> ndarray) with, when their inputs
    are present: ``MTOW_lb``, ``fuel_burn_lb``, ``fuel_mileage_lb_per_nmi``,
    ``electric_percent``, and an offline ``doc_per_nmi`` estimate when the
    study recorded none (the min-fuel grid has no cost model). Formulas
    mirror the demo's bespoke sweep and the Brelje Section IV.D cost
    coefficients used in the OCP factory.
    """
    out = {k: to_float_array(v) for k, v in table.items()}
    mtow_kg = _col(table, "MTOW_kg")
    fuel_kg = _col(table, "fuel_burn_kg")
    batt_kg = _col(table, "W_battery_kg")
    rng = _col(table, range_col)
    energy = _col(table, energy_col)

    if mtow_kg is not None:
        out["MTOW_lb"] = mtow_kg * _KG_TO_LB
    if fuel_kg is not None:
        out["fuel_burn_lb"] = fuel_kg * _KG_TO_LB
        if rng is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                out["fuel_mileage_lb_per_nmi"] = (fuel_kg * _KG_TO_LB) / rng
    cruise_hyb = _col(table, "cruise_hybridization")
    if cruise_hyb is not None:
        out["electric_percent"] = 100.0 * cruise_hyb

    # Offline DOC estimate: only when the study recorded no doc_per_nmi
    # (min-fuel objective) and the cost-model inputs are all available.
    eng = _col(table, "engine_rating_hp")
    mot = _col(table, "motor_rating_hp")
    gen = _col(table, "generator_rating_hp")
    inputs = [mtow_kg, fuel_kg, batt_kg, energy, eng, mot, gen, rng]
    if not _has_finite(_col(table, "doc_per_nmi")) and all(
        s is not None for s in inputs
    ):
        payload_kg = 1000.0 / _KG_TO_LB
        oew_kg = np.clip(mtow_kg - fuel_kg - batt_kg - payload_kg, 0.0, None)
        batt_energy_MJ = 0.9 * batt_kg * energy * 0.0036
        fuel_usd = fuel_kg * (2.50 / 3.08)
        elec_usd = batt_energy_MJ * (36.0 / 3600.0)
        airframe_NR_cost = (
            277.0 * oew_kg * 1.1 + 775.0 * eng * 1.1
            + 100.0 * mot * 1.1 + 100.0 * gen * 1.1
        )
        depreciation_usd = airframe_NR_cost / (5.0 * 365.0 * 15.0)
        battery_trip_usd = 50.0 * batt_kg / 1500.0
        trip_doc_usd = fuel_usd + elec_usd + depreciation_usd + battery_trip_usd
        with np.errstate(divide="ignore", invalid="ignore"):
            out["doc_per_nmi"] = trip_doc_usd / rng
    return out


# Paper-style panels: (column, label, vmin, vmax, overlay_contours). vmax
# None auto-ranges from the data; the fuel-mileage panel keeps the paper's
# contour overlay.
_OCP_STUDY_PANELS = [
    ("fuel_mileage_lb_per_nmi", "Fuel mileage (lb/nmi)", 0.0, None, True),
    ("doc_per_nmi", "Trip DOC (USD) per nmi", None, None, False),
    ("electric_percent", "Degree of hybridization (electric %)", 0.0, 100.0, False),
    ("MTOW_lb", "Maximum Takeoff Weight (lb)", None, None, False),
]


def plot_ocp_trade_grid(
    study_table: Table, x_axis: str, y_axis: str, *,
    style: str = "paper", suptitle: str | None = None, **kwargs,
) -> plt.Figure:
    """Render the Brelje Fig 5/6 style four-panel trade grid from a study.

    Args:
        study_table: columnar case table, non-converged cells already NaN'd
            by the caller.
        x_axis, y_axis: the two numeric grid-axis columns (range, energy).
        style: "paper" (pcolormesh) or "contour".
        suptitle: optional figure title.

    Returns the Figure. Panels whose source column is missing are skipped, so
    a study without the cost model still renders the other three panels.
    """
    table = derive_study_columns(study_table, range_col=x_axis, energy_col=y_axis)
    panels = [
        PanelSpec(col, label, vmin, vmax, overlay)
        for (col, label, vmin, vmax, overlay) in _OCP_STUDY_PANELS
        if _has_finite(table.get(col))
    ]
    if not panels:
        raise ValueError(
            "no OCP study panels available; expected columns like MTOW_kg, "
            "fuel_burn_kg, cruise_hybridization in the case table")
    return render_grid(
        table, x_axis, y_axis, panels, style=style,
        x_label="Design range (nmi)", y_label="Specific energy (Wh/kg)",
        suptitle=suptitle,
    )


OCP_STUDY_PLOTS: dict = {
    "trade_grid": plot_ocp_trade_grid,
}
