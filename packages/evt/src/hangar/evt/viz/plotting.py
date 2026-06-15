"""evt-specific plot generators.

Each plot function accepts ``(run_id, results, case_name, *, save_dir)`` and
returns a ``PlotResult``. ``generate_evt_plot`` routes by ``plot_type``,
mirroring the pyc/oas viz modules. Figure size, suptitle (with run_id), and
axis-label style match oas-cli/pyc plots.
"""

from __future__ import annotations

from pathlib import Path

from hangar.sdk.viz.plotting import (
    PlotResult,
    _fig_to_response,
    _make_fig,
    _require_mpl,
)

from hangar.evt.results import SEGMENT_KEYS, SEGMENT_LABELS, MASS_COMPONENTS

EVT_PLOT_TYPES = frozenset({
    "segment_energy",
    "segment_power",
    "mass_breakdown",
    "mtow_convergence",
    "sweep",
})


def _segment_series(table: dict) -> tuple[list[str], list[float]]:
    """Return (labels, values) in canonical segment order, skipping missing."""
    labels, values = [], []
    for key, label in zip(SEGMENT_KEYS, SEGMENT_LABELS):
        if key in table:
            labels.append(label)
            values.append(float(table[key]))
    return labels, values


def _segment_bar(
    run_id: str, results: dict, *, table_key: str, ylabel: str, color: str,
    title: str, plot_name: str, case_name: str, save_dir,
) -> PlotResult:
    _, plt = _require_mpl()
    table = results.get(table_key, {})
    if not table:
        raise ValueError(f"No {table_key} data in results")

    labels, values = _segment_series(table)
    full_title = f"{title} -- {case_name}" if case_name else title

    fig, ax = plt.subplots(figsize=(9.0, 4.5))
    fig.suptitle(f"{full_title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    x = range(len(labels))
    # Reserve segments get a lighter shade.
    colors = [color if not lbl.startswith("Reserve") else "#cbd5e1" for lbl in labels]
    ax.bar(x, values, color=colors, width=0.7)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=7, rotation=40, ha="right")
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, plot_name, save_dir)


def plot_segment_energy(run_id, results, case_name="", *, save_dir=None) -> PlotResult:
    """Per-segment mission energy bar chart."""
    return _segment_bar(
        run_id, results, table_key="energy_kw_hr",
        ylabel="Energy (kW*hr)", color="#2563eb",
        title="Mission Segment Energy", plot_name="segment_energy",
        case_name=case_name, save_dir=save_dir,
    )


def plot_segment_power(run_id, results, case_name="", *, save_dir=None) -> PlotResult:
    """Per-segment average electric power bar chart."""
    return _segment_bar(
        run_id, results, table_key="avg_electric_power_kw",
        ylabel="Avg Electric Power (kW)", color="#059669",
        title="Mission Segment Power", plot_name="segment_power",
        case_name=case_name, save_dir=save_dir,
    )


def plot_mass_breakdown(run_id, results, case_name="", *, save_dir=None) -> PlotResult:
    """Component empty-mass breakdown horizontal bar chart."""
    _, plt = _require_mpl()
    masses = results.get("mass_breakdown_kg", {})
    if not masses:
        raise ValueError("No mass_breakdown_kg data in results")

    labels, values = [], []
    for attr, label in MASS_COMPONENTS:
        if attr in masses:
            labels.append(label)
            values.append(float(masses[attr]))

    title = "Empty Mass Breakdown"
    if case_name:
        title = f"{title} -- {case_name}"

    fig, ax = plt.subplots(figsize=(8.0, 0.4 * len(labels) + 1.5))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    y = range(len(labels))
    ax.barh(list(y), values, color="#7c3aed", height=0.65)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Mass (kg)", fontsize=9)
    ax.tick_params(axis="x", labelsize=8)
    ax.grid(True, axis="x", alpha=0.3)
    for i, v in enumerate(values):
        ax.text(v, i, f" {v:.0f}", va="center", fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "mass_breakdown", save_dir)


def plot_mtow_convergence(run_id, results, case_name="", *, save_dir=None) -> PlotResult:
    """MTOW guess vs iteration for a sizing run."""
    history = results.get("history", [])
    if not history:
        raise ValueError(
            "No MTOW history in results -- mtow_convergence requires a run_sizing artifact"
        )

    title = "MTOW Convergence"
    if case_name:
        title = f"{title} -- {case_name}"
    fig, ax = _make_fig(run_id, title)

    iters = [row["iteration"] for row in history]
    guesses = [row["mtow_guess_kg"] for row in history]
    ax.plot(iters, guesses, "o-", color="#dc2626", markersize=4, linewidth=1.5)

    sized = results.get("sized_mtow_kg")
    if sized is not None:
        ax.axhline(sized, color="#059669", linestyle="--", linewidth=1.0,
                   label=f"Sized MTOW = {sized:.0f} kg")
        ax.legend(fontsize=8)

    ax.set_xlabel("Iteration", fontsize=9)
    ax.set_ylabel("MTOW Guess (kg)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "mtow_convergence", save_dir)


def plot_sweep(run_id, results, case_name="", *, save_dir=None) -> PlotResult:
    """Metric vs swept parameter."""
    points = results.get("points", [])
    if not points:
        raise ValueError("No sweep points in results -- sweep requires a sweep artifact")

    xs = [p["value"] for p in points if p.get("metric") is not None]
    ys = [p["metric"] for p in points if p.get("metric") is not None]
    if not xs:
        raise ValueError("No successful sweep points to plot")

    param = results.get("param", "parameter")
    metric = results.get("metric", "metric")
    title = f"Sweep: {metric} vs {param}"
    if case_name:
        title = f"{title} -- {case_name}"
    fig, ax = _make_fig(run_id, title)

    ax.plot(xs, ys, "o-", color="#2563eb", markersize=5, linewidth=1.5)
    ax.set_xlabel(param, fontsize=9)
    ax.set_ylabel(metric, fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "sweep", save_dir)


_DISPATCHERS = {
    "segment_energy": plot_segment_energy,
    "segment_power": plot_segment_power,
    "mass_breakdown": plot_mass_breakdown,
    "mtow_convergence": plot_mtow_convergence,
    "sweep": plot_sweep,
}


def generate_evt_plot(
    plot_type: str,
    run_id: str,
    results: dict,
    case_name: str = "",
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Generate an evt plot by type. Returns a PlotResult."""
    if plot_type not in EVT_PLOT_TYPES:
        raise ValueError(
            f"Unknown evt plot_type {plot_type!r}. Supported: {sorted(EVT_PLOT_TYPES)}"
        )
    return _DISPATCHERS[plot_type](run_id, results, case_name, save_dir=save_dir)
