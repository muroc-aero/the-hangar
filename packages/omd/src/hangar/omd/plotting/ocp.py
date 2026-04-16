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
    find_outputs,
    get_reader_and_final_case,
)

logger = logging.getLogger(__name__)

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
