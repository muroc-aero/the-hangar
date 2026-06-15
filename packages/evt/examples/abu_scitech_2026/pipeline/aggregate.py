"""Aggregate the 18 Lane A cases into the case-study grid CSV (the artifact).

Writes ``results/case_study_grid.csv`` with one row per case:

    vehicle, alt_ft, range_mi, total_mission_energy_kw_hr,
    peak_avg_electric_power_kw, sized_mtow_kg, iterations, converged

Lane A is the paper's own method (direct evtolpy on the vendored configs), so
this CSV is the reproduced equivalent of the paper's weight/energy/power
summary tables. Run from the repo root:

    uv run python packages/evt/examples/abu_scitech_2026/pipeline/aggregate.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))

from lane_a.case_study import run_all  # noqa: E402

_FIELDS = [
    "vehicle", "alt_ft", "range_mi",
    "total_mission_energy_kw_hr", "peak_avg_electric_power_kw",
    "sized_mtow_kg", "iterations", "converged",
]


def write_grid(out_path: Path | None = None) -> Path:
    """Run all 18 cases and write the grid CSV; returns the path."""
    rows = run_all()
    out_path = out_path or (_EXAMPLE_ROOT / "results" / "case_study_grid.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in _FIELDS})
    return out_path


if __name__ == "__main__":
    path = write_grid()
    print(f"wrote {path}")
    print(path.read_text())
