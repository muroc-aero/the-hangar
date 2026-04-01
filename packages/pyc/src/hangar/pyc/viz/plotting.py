"""pyCycle-specific plot generators.

Each plot function accepts ``(run_id, results, case_name, *, save_dir)``
and returns a ``PlotResult``.  The ``generate_pyc_plot`` dispatcher routes
by ``plot_type`` string, mirroring the SDK's ``generate_plot`` for OAS.
"""

from __future__ import annotations

from pathlib import Path

from hangar.sdk.viz.plotting import (
    PlotResult,
    _fig_to_response,
    _make_fig,
    _require_mpl,
)

PYC_PLOT_TYPES = frozenset({
    "station_properties",
    "ts_diagram",
    "performance_summary",
    "component_bars",
    "design_vs_offdesign",
})

# Canonical station order for turbojet flow path
_STATION_ORDER = [
    "fc.Fl_O",
    "inlet.Fl_O",
    "comp.Fl_O",
    "burner.Fl_O",
    "turb.Fl_O",
    "nozz.Fl_O",
]

_STATION_LABELS = {
    "fc.Fl_O": "Freestream",
    "inlet.Fl_O": "Inlet",
    "comp.Fl_O": "Compressor",
    "burner.Fl_O": "Burner",
    "turb.Fl_O": "Turbine",
    "nozz.Fl_O": "Nozzle",
}


def _short_label(station: str) -> str:
    return _STATION_LABELS.get(station, station.split(".")[0].capitalize())


def _ordered_stations(flow_stations: dict) -> list[str]:
    """Return station names in canonical flow-path order."""
    ordered = [s for s in _STATION_ORDER if s in flow_stations]
    # Append any stations not in the canonical list
    for s in flow_stations:
        if s not in ordered:
            ordered.append(s)
    return ordered


def _extract_station_series(
    flow_stations: dict, var: str, station_order: list[str],
) -> tuple[list[str], list[float]]:
    """Pull a single variable from each station, skipping None values."""
    labels = []
    values = []
    for s in station_order:
        val = flow_stations.get(s, {}).get(var)
        if val is not None:
            labels.append(_short_label(s))
            values.append(float(val))
    return labels, values


# ---------------------------------------------------------------------------
# Plot: station_properties (2x2 grid)
# ---------------------------------------------------------------------------

def plot_station_properties(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """2x2 grid showing Pt, Tt, Mach, and mass flow through the engine."""
    _, plt = _require_mpl()

    flow_stations = results.get("flow_stations", {})
    if not flow_stations:
        raise ValueError("No flow_stations data in results")

    station_order = _ordered_stations(flow_stations)

    panels = [
        ("tot:P", "Total Pressure (psia)", "#2563eb"),
        ("tot:T", "Total Temperature (degR)", "#dc2626"),
        ("stat:MN", "Mach Number", "#059669"),
        ("stat:W", "Mass Flow (lbm/s)", "#7c3aed"),
    ]

    title = "Station Properties"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, axes = plt.subplots(2, 2, figsize=(8.0, 5.0))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    for ax, (var, ylabel, color) in zip(axes.flat, panels):
        labels, values = _extract_station_series(flow_stations, var, station_order)
        x = range(len(labels))
        ax.plot(x, values, "o-", color=color, markersize=6, linewidth=1.5)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
        ax.set_ylabel(ylabel, fontsize=8)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(True, alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "station_properties", save_dir)


# ---------------------------------------------------------------------------
# Plot: ts_diagram
# ---------------------------------------------------------------------------

def plot_ts_diagram(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """T-s diagram of the Brayton cycle."""
    _, plt = _require_mpl()
    import numpy as np

    flow_stations = results.get("flow_stations", {})
    if not flow_stations:
        raise ValueError("No flow_stations data in results")

    station_order = _ordered_stations(flow_stations)

    s_vals = []
    t_vals = []
    labels = []
    for s in station_order:
        data = flow_stations.get(s, {})
        entropy = data.get("tot:S")
        temp = data.get("tot:T")
        if entropy is not None and temp is not None:
            s_vals.append(float(entropy))
            t_vals.append(float(temp))
            labels.append(_short_label(s))

    if len(s_vals) < 2:
        raise ValueError("Need at least 2 stations with T and S data for T-s diagram")

    title = "T-s Diagram (Brayton Cycle)"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, ax = _make_fig(run_id, title)

    # Color gradient: blue (cold) to red (hot)
    t_arr = np.array(t_vals)
    t_norm = (t_arr - t_arr.min()) / max(t_arr.max() - t_arr.min(), 1.0)

    # Draw connecting lines
    ax.plot(s_vals, t_vals, "-", color="#94a3b8", linewidth=1.5, zorder=1)

    # Close the cycle path (nozzle exit back to freestream)
    ax.plot(
        [s_vals[-1], s_vals[0]], [t_vals[-1], t_vals[0]],
        "--", color="#94a3b8", linewidth=1.0, alpha=0.5, zorder=1,
    )

    # Plot stations with color gradient
    for i, (s, t, label) in enumerate(zip(s_vals, t_vals, labels)):
        r = t_norm[i]
        color = (0.1 + 0.7 * r, 0.15 * (1 - r), 0.8 * (1 - r))
        ax.plot(s, t, "o", color=color, markersize=8, zorder=3,
                markeredgecolor="white", markeredgewidth=0.8)
        ax.annotate(
            label, (s, t), textcoords="offset points",
            xytext=(6, 6), fontsize=7, color="#334155",
        )

    # Annotate key processes
    if len(labels) >= 4:
        # Compression: inlet -> compressor exit
        mid_comp_idx = min(2, len(s_vals) - 1)
        ax.annotate(
            "Compression", xy=((s_vals[1] + s_vals[mid_comp_idx]) / 2,
                               (t_vals[1] + t_vals[mid_comp_idx]) / 2),
            fontsize=7, fontstyle="italic", color="#2563eb", alpha=0.8,
        )
        # Heat addition: compressor exit -> burner exit
        burn_idx = min(3, len(s_vals) - 1)
        ax.annotate(
            "Heat Addition", xy=((s_vals[mid_comp_idx] + s_vals[burn_idx]) / 2,
                                 (t_vals[mid_comp_idx] + t_vals[burn_idx]) / 2),
            fontsize=7, fontstyle="italic", color="#dc2626", alpha=0.8,
        )
        # Expansion: burner exit -> nozzle
        exp_idx = min(4, len(s_vals) - 1)
        ax.annotate(
            "Expansion", xy=((s_vals[burn_idx] + s_vals[exp_idx]) / 2,
                             (t_vals[burn_idx] + t_vals[exp_idx]) / 2),
            fontsize=7, fontstyle="italic", color="#059669", alpha=0.8,
        )

    ax.set_xlabel("Entropy, S (Btu/(lbm-degR))", fontsize=8)
    ax.set_ylabel("Total Temperature, Tt (degR)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "ts_diagram", save_dir)


# ---------------------------------------------------------------------------
# Plot: performance_summary (table card)
# ---------------------------------------------------------------------------

def plot_performance_summary(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Styled table summarizing engine performance and component data."""
    _, plt = _require_mpl()

    perf = results.get("performance", {})
    components = results.get("components", {})

    # Build table rows: (section, label, value, units)
    rows: list[tuple[str, str, str, str]] = []

    # Performance section
    _add_row = rows.append
    _add_row(("Performance", "Net Thrust (Fn)", _fmt(perf.get("Fn")), "lbf"))
    _add_row(("", "Gross Thrust (Fg)", _fmt(perf.get("Fg")), "lbf"))
    _add_row(("", "TSFC", _fmt(perf.get("TSFC"), 4), "lbm/hr/lbf"))
    _add_row(("", "OPR", _fmt(perf.get("OPR"), 2), ""))
    _add_row(("", "Fuel Flow", _fmt(perf.get("Wfuel"), 4), "lbm/s"))
    _add_row(("", "Ram Drag", _fmt(perf.get("ram_drag")), "lbf"))
    _add_row(("", "Mass Flow", _fmt(perf.get("mass_flow"), 2), "lbm/s"))

    # Compressor
    for name in ("comp", "hpc", "lpc", "fan"):
        if name in components:
            c = components[name]
            _add_row((_comp_title(name), "Pressure Ratio", _fmt(c.get("PR"), 3), ""))
            _add_row(("", "Efficiency", _fmt(c.get("eff"), 4), ""))
            _add_row(("", "Power", _fmt(c.get("pwr")), "hp"))
            break

    # Turbine
    for name in ("turb", "hpt", "lpt"):
        if name in components:
            t = components[name]
            _add_row((_comp_title(name), "Pressure Ratio", _fmt(t.get("PR"), 3), ""))
            _add_row(("", "Efficiency", _fmt(t.get("eff"), 4), ""))
            _add_row(("", "Power", _fmt(t.get("pwr")), "hp"))
            break

    # Burner
    for name in ("burner",):
        if name in components:
            b = components[name]
            _add_row(("Burner", "FAR", _fmt(b.get("FAR"), 5), ""))
            _add_row(("", "dP/P", _fmt(b.get("dPqP"), 4), ""))
            break

    # Nozzle
    for name in ("nozz",):
        if name in components:
            n = components[name]
            _add_row(("Nozzle", "Gross Thrust", _fmt(n.get("Fg")), "lbf"))
            _add_row(("", "Cv", _fmt(n.get("Cv"), 4), ""))
            _add_row(("", "Throat Area", _fmt(n.get("throat_area"), 1), "in^2"))
            break

    # Shaft
    for name in ("shaft", "hp_shaft", "lp_shaft"):
        if name in components:
            s = components[name]
            _add_row(("Shaft", "Speed", _fmt(s.get("Nmech")), "rpm"))
            _add_row(("", "Net Power", _fmt(s.get("pwr_net"), 3), "hp"))
            break

    title = "Engine Performance Summary"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, ax = plt.subplots(figsize=(6.0, 0.3 * len(rows) + 1.2))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)
    ax.set_axis_off()

    # Build cell text and colors
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
    return f"{float(val):.{decimals}f}"


def _comp_title(name: str) -> str:
    titles = {
        "comp": "Compressor",
        "hpc": "HPC",
        "lpc": "LPC",
        "fan": "Fan",
        "turb": "Turbine",
        "hpt": "HPT",
        "lpt": "LPT",
    }
    return titles.get(name, name.capitalize())


# ---------------------------------------------------------------------------
# Plot: component_bars
# ---------------------------------------------------------------------------

def plot_component_bars(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Grouped horizontal bar chart of component performance metrics."""
    _, plt = _require_mpl()
    import numpy as np

    components = results.get("components", {})
    if not components:
        raise ValueError("No components data in results")

    title = "Component Performance"
    if case_name:
        title = f"{title} -- {case_name}"

    # Collect PR and efficiency for turbomachinery
    comp_names = []
    pr_vals = []
    eff_vals = []
    pwr_vals = []
    for name, data in components.items():
        pr = data.get("PR")
        eff = data.get("eff")
        if pr is not None or eff is not None:
            comp_names.append(_comp_title(name))
            pr_vals.append(float(pr) if pr is not None else 0.0)
            eff_vals.append(float(eff) if eff is not None else 0.0)
            pwr = data.get("pwr")
            pwr_vals.append(abs(float(pwr)) if pwr is not None else 0.0)

    if not comp_names:
        raise ValueError("No turbomachinery components with PR/eff data")

    fig, axes = plt.subplots(1, 3, figsize=(9.0, 3.0 + 0.4 * len(comp_names)))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    y_pos = np.arange(len(comp_names))

    # Pressure ratio
    axes[0].barh(y_pos, pr_vals, color="#2563eb", height=0.6)
    axes[0].set_yticks(y_pos)
    axes[0].set_yticklabels(comp_names, fontsize=8)
    axes[0].set_xlabel("Pressure Ratio", fontsize=8)
    axes[0].tick_params(axis="x", labelsize=7)
    axes[0].grid(True, axis="x", alpha=0.3)
    for i, v in enumerate(pr_vals):
        if v > 0:
            axes[0].text(v + 0.1, i, f"{v:.2f}", va="center", fontsize=7)

    # Efficiency
    axes[1].barh(y_pos, eff_vals, color="#059669", height=0.6)
    axes[1].set_yticks(y_pos)
    axes[1].set_yticklabels([], fontsize=8)
    axes[1].set_xlabel("Isentropic Efficiency", fontsize=8)
    axes[1].set_xlim(0, 1.05)
    axes[1].tick_params(axis="x", labelsize=7)
    axes[1].grid(True, axis="x", alpha=0.3)
    for i, v in enumerate(eff_vals):
        if v > 0:
            axes[1].text(v + 0.01, i, f"{v:.3f}", va="center", fontsize=7)

    # Power
    axes[2].barh(y_pos, pwr_vals, color="#dc2626", height=0.6)
    axes[2].set_yticks(y_pos)
    axes[2].set_yticklabels([], fontsize=8)
    axes[2].set_xlabel("|Power| (hp)", fontsize=8)
    axes[2].tick_params(axis="x", labelsize=7)
    axes[2].grid(True, axis="x", alpha=0.3)
    for i, v in enumerate(pwr_vals):
        if v > 0:
            axes[2].text(v * 1.02, i, f"{v:.0f}", va="center", fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.90])
    return _fig_to_response(fig, run_id, "component_bars", save_dir)


# ---------------------------------------------------------------------------
# Plot: design_vs_offdesign
# ---------------------------------------------------------------------------

def plot_design_vs_offdesign(
    run_id: str,
    results: dict,
    case_name: str = "",
    *,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """2x2 subplot grid comparing design and off-design performance.

    Each metric gets its own axes so the scale is readable regardless of
    the magnitude differences between thrust (thousands) and TSFC (~1).
    """
    _, plt = _require_mpl()
    import numpy as np

    perf = results.get("performance", {})
    design_perf = results.get("design_point", {})

    if not design_perf:
        raise ValueError(
            "design_vs_offdesign requires an off-design artifact with "
            "design_point reference data"
        )

    title = "Design vs Off-Design"
    if case_name:
        title = f"{title} -- {case_name}"

    metrics = [
        ("Fn", "Net Thrust", "lbf"),
        ("TSFC", "TSFC", "lbm/hr/lbf"),
        ("OPR", "OPR", ""),
        ("mass_flow", "Mass Flow", "lbm/s"),
    ]

    # Collect data for metrics that exist in both design and off-design
    panels: list[tuple[str, str, float, float, float]] = []
    for key, label, units in metrics:
        dv = design_perf.get(key)
        ov = perf.get(key)
        if dv is not None and ov is not None:
            dv_f, ov_f = float(dv), float(ov)
            delta = (ov_f - dv_f) / abs(dv_f) * 100.0 if abs(dv_f) > 1e-12 else 0.0
            ylabel = f"{label} ({units})" if units else label
            panels.append((ylabel, label, dv_f, ov_f, delta))

    if not panels:
        raise ValueError("No overlapping metrics between design and off-design")

    n = len(panels)
    cols = min(n, 2)
    rows = (n + 1) // 2

    fig, axes = plt.subplots(rows, cols, figsize=(8.0, 3.0 * rows))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    # Flatten axes for uniform iteration
    if n == 1:
        axes_flat = [axes]
    else:
        axes_flat = list(np.array(axes).flat)

    bar_labels = ["Design", "Off-Design"]
    colors = ["#2563eb", "#f59e0b"]

    for i, (ylabel, short_label, dv, ov, delta) in enumerate(panels):
        ax = axes_flat[i]
        x = np.array([0, 1])
        bars = ax.bar(x, [dv, ov], width=0.55, color=colors, alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(bar_labels, fontsize=8)
        ax.set_ylabel(ylabel, fontsize=8)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(True, axis="y", alpha=0.3)

        # Value labels on bars
        for bar, val in zip(bars, [dv, ov]):
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{val:.4g}", ha="center", va="bottom", fontsize=7,
            )

        # Delta annotation between the bars
        sign = "+" if delta >= 0 else ""
        delta_color = "#059669" if abs(delta) < 5 else "#dc2626"
        mid_y = max(dv, ov) * 1.08
        ax.text(
            0.5, mid_y, f"{sign}{delta:.1f}%",
            ha="center", fontsize=9, fontweight="bold", color=delta_color,
        )

    # Hide unused axes if odd number of panels
    for j in range(n, len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "design_vs_offdesign", save_dir)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCHERS = {
    "station_properties": plot_station_properties,
    "ts_diagram": plot_ts_diagram,
    "performance_summary": plot_performance_summary,
    "component_bars": plot_component_bars,
    "design_vs_offdesign": plot_design_vs_offdesign,
}


def generate_pyc_plot(
    plot_type: str,
    run_id: str,
    results: dict,
    case_name: str = "",
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Generate a pyCycle plot by type. Returns a PlotResult."""
    if plot_type not in PYC_PLOT_TYPES:
        raise ValueError(
            f"Unknown pyc plot_type {plot_type!r}. "
            f"Supported: {sorted(PYC_PLOT_TYPES)}"
        )
    fn = _DISPATCHERS[plot_type]
    return fn(run_id, results, case_name, save_dir=save_dir)
