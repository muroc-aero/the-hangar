"""Aviary-specific plot generators.

Each plot function accepts ``(run_id, results, case_name, *, save_dir)``
and returns a ``PlotResult``. The ``generate_avy_plot`` dispatcher routes
by ``plot_type`` string, mirroring the pyc/oas plot modules. All plots read
from the saved artifact results dict (including the downsampled mission
timeseries), never from a live problem.
"""

from __future__ import annotations

from pathlib import Path

from hangar.sdk.viz.plotting import (
    PlotResult,
    _fig_to_response,
    _require_mpl,
)

AVY_PLOT_TYPES = frozenset({
    "mission_profile",
    "mass_breakdown",
    "performance_summary",
    "payload_range",
})

_PHASE_COLORS = {
    "climb": "#2563eb",
    "cruise": "#059669",
    "descent": "#7c3aed",
}


def _series(timeseries: dict, key: str) -> list:
    return timeseries.get(key) or []


# ---------------------------------------------------------------------------
# Plot: mission_profile (2x2 grid vs range)
# ---------------------------------------------------------------------------

def plot_mission_profile(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """2x2 grid: altitude, Mach, mass, and throttle vs mission range."""
    _, plt = _require_mpl()

    ts = results.get("timeseries", {})
    x = _series(ts, "distance_nmi")
    phases = _series(ts, "phase")
    if not x:
        raise ValueError("No timeseries data in results")

    panels = [
        ("altitude_ft", "Altitude (ft)"),
        ("mach", "Mach"),
        ("mass_lbm", "Mass (lbm)"),
        ("throttle", "Throttle"),
    ]

    title = "Mission Profile"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, axes = plt.subplots(2, 2, figsize=(8.0, 5.0))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    for ax, (key, ylabel) in zip(axes.flat, panels):
        y = _series(ts, key)
        if len(y) != len(x):
            ax.set_axis_off()
            continue
        # One line segment per phase so phase boundaries are visible
        seen = []
        for phase in dict.fromkeys(phases):
            pairs = [
                (xi, yi)
                for xi, p, yi in zip(x, phases, y)
                if p == phase and xi is not None and yi is not None
            ]
            xs = [xi for xi, _ in pairs]
            ys = [yi for _, yi in pairs]
            if not xs:
                continue
            color = _PHASE_COLORS.get(phase)
            label = phase if phase not in seen else None
            ax.plot(xs, ys, "-", color=color, linewidth=1.5, label=label)
            seen.append(phase)
        ax.set_xlabel("Range (nmi)", fontsize=8)
        ax.set_ylabel(ylabel, fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, alpha=0.3)

    handles, labels = axes.flat[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=len(labels), fontsize=7)

    fig.tight_layout(rect=[0, 0.05, 1, 0.93])
    return _fig_to_response(fig, run_id, "mission_profile", save_dir)


# ---------------------------------------------------------------------------
# Plot: mass_breakdown
# ---------------------------------------------------------------------------

def plot_mass_breakdown(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Bar chart of the sizing mass buildup."""
    _, plt = _require_mpl()

    perf = results.get("performance", {})
    bars = [
        ("Gross", perf.get("gross_mass_lbm"), "#15487A"),
        ("Zero fuel", perf.get("zero_fuel_mass_lbm"), "#2563eb"),
        ("Operating", perf.get("operating_mass_lbm"), "#059669"),
        ("Total fuel", perf.get("total_fuel_mass_lbm"), "#1F9D55"),
        ("Fuel burned", perf.get("fuel_burned_lbm"), "#7c3aed"),
    ]
    bars = [(label, val, color) for label, val, color in bars if val is not None]
    if not bars:
        raise ValueError("No mass data in results")

    title = "Sizing Mass Breakdown"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    labels = [b[0] for b in bars]
    values = [b[1] for b in bars]
    colors = [b[2] for b in bars]
    ax.bar(labels, values, color=colors, width=0.6)
    for i, v in enumerate(values):
        ax.text(i, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=7)
    ax.set_ylabel("Mass (lbm)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "mass_breakdown", save_dir)


# ---------------------------------------------------------------------------
# Plot: payload_range
# ---------------------------------------------------------------------------

def plot_payload_range(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Classic payload-range diagram from a run_payload_range artifact."""
    _, plt = _require_mpl()

    points = (results.get("payload_range") or {}).get("points") or []
    points = [
        p for p in points
        if p.get("payload_lbm") is not None and p.get("range_nmi") is not None
    ]
    if len(points) < 2:
        raise ValueError(
            "No payload-range points in results (payload_range plots need a "
            "run_payload_range artifact)"
        )
    points = sorted(points, key=lambda p: p["range_nmi"])

    title = "Payload-Range Diagram"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    xs = [p["range_nmi"] for p in points]
    ys = [p["payload_lbm"] for p in points]
    ax.plot(xs, ys, "o-", color="#15487A", linewidth=1.5, markersize=6)
    for p in points:
        ax.annotate(
            p["label"].replace("_", " "),
            (p["range_nmi"], p["payload_lbm"]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=7,
        )
    ax.set_xlabel("Range (nmi)", fontsize=8)
    ax.set_ylabel("Payload (lbm)", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "payload_range", save_dir)


# ---------------------------------------------------------------------------
# Plot: performance_summary
# ---------------------------------------------------------------------------

def plot_performance_summary(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Styled table summarizing the sizing run."""
    _, plt = _require_mpl()

    perf = results.get("performance", {})
    design = results.get("design", {})
    opt = results.get("optimizer", {})

    rows: list[tuple[str, str, str, str]] = []
    _add_row = rows.append
    _add_row(("Mission", "Gross Mass", _fmt(perf.get("gross_mass_lbm"), 0), "lbm"))
    _add_row(("", "Total Fuel", _fmt(perf.get("total_fuel_mass_lbm"), 0), "lbm"))
    _add_row(("", "Fuel Burned", _fmt(perf.get("fuel_burned_lbm"), 0), "lbm"))
    _add_row(("", "Zero Fuel Mass", _fmt(perf.get("zero_fuel_mass_lbm"), 0), "lbm"))
    _add_row(("", "Operating Mass", _fmt(perf.get("operating_mass_lbm"), 0), "lbm"))
    _add_row(("", "Range", _fmt(perf.get("range_nmi"), 1), "nmi"))
    _add_row(("", "Mission Time", _fmt(perf.get("final_time_min"), 1), "min"))
    _add_row(("Design", "Design Gross Mass", _fmt(design.get("design_gross_mass_lbm"), 0), "lbm"))
    _add_row(("", "Wing Area", _fmt(design.get("wing_area_ft2"), 1), "ft^2"))
    _add_row(("", "Wing Span", _fmt(design.get("wing_span_ft"), 1), "ft"))
    success = opt.get("success")
    _add_row(("Optimizer", "Converged", "yes" if success else ("no" if success is not None else "N/A"), ""))

    title = "Sizing Performance Summary"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, ax = plt.subplots(figsize=(6.0, 0.3 * len(rows) + 1.2))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)
    ax.set_axis_off()

    cell_text = []
    cell_colors = []
    section_color = "#e2e8f0"
    normal_color = "#ffffff"
    for section, label, value, units in rows:
        display = f"{value} {units}".strip() if units else value
        if section:
            cell_text.append([section, label, display])
            cell_colors.append([section_color, section_color, section_color])
        else:
            cell_text.append(["", label, display])
            cell_colors.append([normal_color, normal_color, normal_color])

    table = ax.table(
        cellText=cell_text,
        colLabels=["Section", "Parameter", "Value"],
        cellColours=cell_colors,
        colColours=[section_color] * 3,
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.2)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "performance_summary", save_dir)


def _fmt(val, decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{float(val):,.{decimals}f}"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCHERS = {
    "mission_profile": plot_mission_profile,
    "mass_breakdown": plot_mass_breakdown,
    "performance_summary": plot_performance_summary,
    "payload_range": plot_payload_range,
}


def generate_avy_plot(
    plot_type: str,
    run_id: str,
    results: dict,
    case_name: str = "",
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Generate an Aviary plot by type. Returns a PlotResult."""
    if plot_type not in AVY_PLOT_TYPES:
        raise ValueError(
            f"Unknown avy plot_type {plot_type!r}. "
            f"Supported: {sorted(AVY_PLOT_TYPES)}"
        )
    fn = _DISPATCHERS[plot_type]
    return fn(run_id, results, case_name, save_dir=save_dir)
