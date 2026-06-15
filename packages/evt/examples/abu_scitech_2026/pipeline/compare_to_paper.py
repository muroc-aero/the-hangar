"""Fidelity check: reproduced (Lane A) vs the paper's published summary tables.

Compares the reproduced grid CSV against the values transcribed from the
upstream workbook (``shared.PAPER``):

  * mission energy (without resizing) -- expected to match the paper closely,
    since the energy model is unchanged at the pinned ref.
  * sized MTOW (final) -- the resizing loop has drifted upstream since the
    paper, so a few-percent offset and two non-convergent Joby S4 60-mile
    cases are expected and reported, not hidden.

Prints a Markdown table (paste-ready for the README). Run after
``pipeline/aggregate.py``:

    uv run python packages/evt/examples/abu_scitech_2026/pipeline/compare_to_paper.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))
from shared import PAPER, all_cases, case_id  # noqa: E402

_GRID = _EXAMPLE_ROOT / "results" / "case_study_grid.csv"


def _load_grid() -> dict[str, dict]:
    with open(_GRID, newline="", encoding="utf-8") as f:
        return {
            f"{r['vehicle']}-{r['alt_ft']}-{r['range_mi']}": r
            for r in csv.DictReader(f)
        }


def _pct(repro: float, paper: float) -> str:
    return f"{100.0 * (repro - paper) / paper:+.2f}%"


def build_table() -> str:
    grid = _load_grid()
    lines = [
        "| case | E paper | E repro | E delta | MTOW paper | MTOW repro | MTOW delta |",
        "|------|--------:|--------:|--------:|-----------:|-----------:|-----------:|",
    ]
    for vehicle, alt, rng in all_cases():
        cid = case_id(vehicle, alt, rng)
        row = grid[cid]
        paper_e, paper_m = PAPER[cid]
        repro_e = float(row["total_mission_energy_kw_hr"])
        e_cell = f"{repro_e:.2f}"
        e_delta = _pct(repro_e, paper_e)
        if row["sized_mtow_kg"]:
            repro_m = float(row["sized_mtow_kg"])
            m_cell = f"{repro_m:.1f}"
            m_delta = _pct(repro_m, paper_m)
        else:
            m_cell = "diverged"
            m_delta = "N/A"
        lines.append(
            f"| {cid} | {paper_e:.2f} | {e_cell} | {e_delta} "
            f"| {paper_m:.1f} | {m_cell} | {m_delta} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_table())
