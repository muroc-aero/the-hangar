"""Render the case-study comparison figures from the grid CSV.

Produces two figures under ``figures/reproduced/``:

  * ``sized_mtow.png``     -- sized MTOW vs range, one line per vehicle, one
                              panel per altitude (diverged cells omitted).
  * ``mission_energy.png`` -- total mission energy vs range, same layout.

Run after ``pipeline/aggregate.py`` has written the grid CSV:

    uv run python packages/evt/examples/abu_scitech_2026/pipeline/plotting.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))
from shared import ALTITUDES_FT, RANGES_MI, VEHICLE_LABELS, VEHICLES  # noqa: E402

_GRID = _EXAMPLE_ROOT / "results" / "case_study_grid.csv"
_OUT = _EXAMPLE_ROOT / "figures" / "reproduced"


def _load_grid() -> list[dict]:
    with open(_GRID, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _series(rows, metric, alt_ft, vehicle):
    """(ranges, values) for one vehicle/altitude, skipping blank (diverged)."""
    pts = {}
    for r in rows:
        if int(r["alt_ft"]) == alt_ft and r["vehicle"] == vehicle and r[metric]:
            pts[int(r["range_mi"])] = float(r[metric])
    xs = [rm for rm in RANGES_MI if rm in pts]
    return xs, [pts[x] for x in xs]


def _plot_metric(rows, metric, ylabel, title, out_name) -> Path:
    fig, axes = plt.subplots(1, len(ALTITUDES_FT), figsize=(11, 4.5), sharey=True)
    for ax, alt in zip(axes, ALTITUDES_FT):
        for vehicle in VEHICLES:
            xs, ys = _series(rows, metric, alt, vehicle)
            ax.plot(xs, ys, marker="o", label=VEHICLE_LABELS[vehicle])
        ax.set_title(f"{alt} ft")
        ax.set_xlabel("Mission range (mi)")
        ax.set_xticks(RANGES_MI)
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel(ylabel)
    axes[-1].legend(loc="best", fontsize=9)
    fig.suptitle(title)
    fig.tight_layout()
    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / out_name
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path


def render_all() -> list[Path]:
    rows = _load_grid()
    return [
        _plot_metric(
            rows, "sized_mtow_kg", "Sized MTOW (kg)",
            "ABU SciTech 2026 -- sized MTOW (evt reproduction)", "sized_mtow.png"),
        _plot_metric(
            rows, "total_mission_energy_kw_hr", "Total mission energy (kW*hr)",
            "ABU SciTech 2026 -- mission energy (evt reproduction)",
            "mission_energy.png"),
    ]


if __name__ == "__main__":
    for path in render_all():
        print(f"wrote {path}")
