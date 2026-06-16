"""Wrapper-parity figure: direct evtolpy (Lane A) vs the cli/mcp tool layer (Lane B).

Both lanes run the *same* evtolpy code on the *same* 18 vendored configs -- Lane
A calls ``Aircraft`` / ``_iterate_mtow`` directly, Lane B drives the hangar-evt
section setters + ``run_mission_analysis`` / ``run_sizing`` (the path evt-cli and
the MCP server take). They agree to floating-point round-off, so this figure is
the visual proof that the wrapper changes nothing: Lane A is drawn as a line,
Lane B as open markers sitting on top of it.

Contrast with ``compare_to_paper.py`` (Lane A vs the *paper*), where the pinned
upstream ref genuinely differs from the published artifact. That is an upstream
version effect; this is a wrapper-fidelity check, and they are orthogonal.

    uv run python packages/evt/examples/abu_scitech_2026/pipeline/compare_lanes_plot.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))
from shared import ALTITUDES_FT, RANGES_MI, VEHICLE_LABELS, VEHICLES  # noqa: E402

from lane_a.case_study import run_all as run_lane_a  # noqa: E402
from lane_b.run_all import run_all as run_lane_b  # noqa: E402

_OUT = _EXAMPLE_ROOT / "figures" / "reproduced"

_METRICS = [
    ("sized_mtow_kg", "Sized MTOW (kg)"),
    ("total_mission_energy_kw_hr", "Total mission energy (kW*hr)"),
]


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["case_id"]: r for r in rows}


def _series(grid: dict[str, dict], metric, alt_ft, vehicle):
    """(ranges, values) for one vehicle/altitude, skipping diverged (None) cells."""
    pts = {}
    for rng in RANGES_MI:
        row = grid.get(f"{vehicle}-{alt_ft}-{rng}")
        if row is not None and row.get(metric) is not None:
            pts[rng] = float(row[metric])
    xs = [rm for rm in RANGES_MI if rm in pts]
    return xs, [pts[x] for x in xs]


def _max_abs_rel_delta(a_grid, b_grid) -> float:
    """Largest |Lane B - Lane A| / |Lane A| over all metrics/cases (converged)."""
    worst = 0.0
    for cid, a_row in a_grid.items():
        b_row = b_grid.get(cid, {})
        for metric, _ in _METRICS:
            av, bv = a_row.get(metric), b_row.get(metric)
            if av is None or bv is None or av == 0:
                continue
            worst = max(worst, abs(float(bv) - float(av)) / abs(float(av)))
    return worst


def render(a_rows: list[dict], b_rows: list[dict]) -> Path:
    a_grid, b_grid = _by_id(a_rows), _by_id(b_rows)
    color = {v: f"C{i}" for i, v in enumerate(VEHICLES)}

    fig, axes = plt.subplots(
        len(_METRICS), len(ALTITUDES_FT), figsize=(11, 8.5), sharex=True)
    for row_i, (metric, ylabel) in enumerate(_METRICS):
        for col_i, alt in enumerate(ALTITUDES_FT):
            ax = axes[row_i][col_i]
            for vehicle in VEHICLES:
                ax_xs, ay = _series(a_grid, metric, alt, vehicle)
                bx_xs, by = _series(b_grid, metric, alt, vehicle)
                ax.plot(ax_xs, ay, "-", color=color[vehicle], lw=1.6,
                        label=VEHICLE_LABELS[vehicle])
                ax.plot(bx_xs, by, "x", color=color[vehicle], ms=9, mew=2)
            if row_i == 0:
                ax.set_title(f"{alt} ft")
            if row_i == len(_METRICS) - 1:
                ax.set_xlabel("Mission range (mi)")
            if col_i == 0:
                ax.set_ylabel(ylabel)
            ax.set_xticks(RANGES_MI)
            ax.grid(True, alpha=0.3)
    axes[0][-1].legend(loc="best", fontsize=9)

    worst = _max_abs_rel_delta(a_grid, b_grid)
    fig.suptitle(
        "ABU SciTech 2026 -- wrapper parity: direct evtolpy (line) vs "
        f"hangar-evt cli/mcp (x)\nmax |delta| across 18 cases = {worst:.2e} "
        "(round-off); same code, different interface")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / "lane_parity.png"
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    a_rows = run_lane_a()
    b_rows = asyncio.run(run_lane_b())
    path = render(a_rows, b_rows)
    print(f"wrote {path}")
