"""evt (evtolpy) plot providers for omd runs.

These read the final problem case from an omd run's SqliteRecorder and render
the per-segment energy/power tables, the component mass breakdown, and the MTOW
convergence history that the ``EvtolSizingComp`` exposes as outputs. Signatures
match the omd plot-provider contract: ``(recorder_path, **kwargs) -> Figure``.

The segment/mass labels and ordering come from ``hangar.evt.results`` so they
stay in lockstep with the evt result extraction.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from hangar.omd.plotting._common import find_first_output, get_reader_and_final_case

logger = logging.getLogger(__name__)

_FIG_WIDTH = 9.0
_FIG_HEIGHT = 4.5


def _segment_labels() -> list[str]:
    from hangar.evt.results import SEGMENT_LABELS
    return list(SEGMENT_LABELS)


def _mass_labels() -> list[str]:
    from hangar.evt.results import MASS_COMPONENTS
    return [label for _, label in MASS_COMPONENTS]


def _read_vector(case, *patterns: str) -> np.ndarray | None:
    _, val = find_first_output(case, *patterns)
    if val is None:
        return None
    return np.atleast_1d(np.asarray(val, dtype=float))


def _bar_fig(labels, values, *, ylabel: str, title: str, run_id: str,
             color: str, horizontal: bool = False) -> plt.Figure:
    if horizontal:
        fig, ax = plt.subplots(figsize=(8.0, 0.4 * len(labels) + 1.5))
        y = np.arange(len(labels))
        ax.barh(y, values, color=color)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=7)
        ax.invert_yaxis()
        ax.set_xlabel(ylabel)
    else:
        fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
        x = np.arange(len(labels))
        ax.bar(x, values, color=color)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_ylabel(ylabel)
    ax.grid(True, axis="x" if horizontal else "y", alpha=0.3)
    fig.suptitle(f"{title}\n({run_id})" if run_id else title, fontsize=9, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    return fig


def _segment_plot(recorder_path: Path, output_pattern: str, *,
                  ylabel: str, title: str, color: str, **kwargs) -> plt.Figure:
    run_id = kwargs.get("run_id", "")
    _, case = get_reader_and_final_case(recorder_path)
    values = _read_vector(case, output_pattern, f"*{output_pattern}")
    if values is None:
        raise ValueError(f"{output_pattern!r} not found in recorder {recorder_path}")
    labels = _segment_labels()
    n = min(len(labels), len(values))
    return _bar_fig(labels[:n], values[:n], ylabel=ylabel, title=title,
                    run_id=run_id, color=color)


def plot_segment_energy(recorder_path: Path, **kwargs) -> plt.Figure:
    """Per-segment mission energy (kWh)."""
    return _segment_plot(
        recorder_path, "segment_energy_kw_hr",
        ylabel="Energy [kWh]", title="Mission Segment Energy",
        color="#15487A", **kwargs,
    )


def plot_segment_power(recorder_path: Path, **kwargs) -> plt.Figure:
    """Per-segment average electric power (kW)."""
    return _segment_plot(
        recorder_path, "segment_power_kw",
        ylabel="Avg electric power [kW]", title="Mission Segment Power",
        color="#1F9D55", **kwargs,
    )


def plot_mass_breakdown(recorder_path: Path, **kwargs) -> plt.Figure:
    """Component empty-mass breakdown (kg)."""
    run_id = kwargs.get("run_id", "")
    _, case = get_reader_and_final_case(recorder_path)
    values = _read_vector(case, "mass_breakdown_kg", "*mass_breakdown_kg")
    if values is None:
        raise ValueError(f"'mass_breakdown_kg' not found in recorder {recorder_path}")
    labels = _mass_labels()
    n = min(len(labels), len(values))
    return _bar_fig(labels[:n], values[:n], ylabel="Mass [kg]",
                    title="Component Mass Breakdown", run_id=run_id,
                    color="#15487A", horizontal=True)


def plot_mtow_convergence(recorder_path: Path, **kwargs) -> plt.Figure:
    """MTOW fixed-point convergence history (sizing mode only).

    The history is a padded vector output; ``n_iterations`` gives the real
    length. If the run was a mission-mode analysis these outputs are absent and
    we render an explanatory placeholder rather than failing the plot batch.
    """
    run_id = kwargs.get("run_id", "")
    _, case = get_reader_and_final_case(recorder_path)
    history = _read_vector(case, "mtow_history_kg", "*mtow_history_kg")
    n_iter_arr = _read_vector(case, "n_iterations", "*n_iterations")

    fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT * 0.8))
    if history is None or n_iter_arr is None or int(n_iter_arr[0]) == 0:
        ax.text(0.5, 0.5, "No MTOW convergence history recorded\n"
                "(mission-mode run, or record_history disabled).",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=10, color="gray")
        ax.axis("off")
    else:
        n = int(n_iter_arr[0])
        series = history[:n]
        ax.plot(np.arange(n), series, "-o", markersize=4, linewidth=1.5,
                color="#15487A")
        ax.set_xlabel("Sizing iteration")
        ax.set_ylabel("MTOW [kg]")
        ax.set_title(f"Converged: {series[-1]:.1f} kg in {n} iterations",
                     fontsize=8)
        ax.grid(True, alpha=0.3)
    fig.suptitle(f"MTOW Convergence\n({run_id})" if run_id else "MTOW Convergence",
                 fontsize=9, y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    return fig


# N2 sentinel: generate_plots() handles it specially (copies the live N2 HTML).
_N2_SENTINEL = None

EVT_PLOTS: dict[str, callable] = {
    "segment_energy": plot_segment_energy,
    "segment_power": plot_segment_power,
    "mass_breakdown": plot_mass_breakdown,
    "mtow_convergence": plot_mtow_convergence,
    "n2": _N2_SENTINEL,
}
