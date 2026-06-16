#!/usr/bin/env python
"""Compare the omd abu-scitech-2026 study against the Lane-A golden grid.

Reads a completed ``demo-abu-scitech-2026`` study's per-case outputs and checks
them against the ground-truth table the standalone evt lanes produce:
``packages/evt/examples/abu_scitech_2026/results/case_study_grid.csv``.

The two Joby S4 60-mile cases diverge in evtolpy's upstream MTOW loop (a
documented upstream resizing-loop issue, not a wrapper bug); they are expected
to fail and are reported as such rather than counted as mismatches.

Usage:
    python packages/omd/demos/abu_scitech_2026/compare_to_golden.py [study_id]
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from hangar.sdk.study.store import StudyStore

# Sized MTOW carries the upstream resizing-loop drift, so it gets a looser
# tolerance than energy/power (which reproduce the paper closely).
TOL = {
    "total_mission_energy_kw_hr": 1e-6,
    "peak_power_kw": 1e-6,
    "sized_mtow_kg": 0.15,  # relative; documented drift up to ~12%
}
# evtolpy diverges on these upstream; expected to be absent/failed.
EXPECTED_DIVERGENCES = {"joby-s4-1500-60", "joby-s4-3000-60"}

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "evt/examples/abu_scitech_2026/results/case_study_grid.csv"
)
# Study output name -> golden CSV column name.
COLS = {
    "total_mission_energy_kw_hr": "total_mission_energy_kw_hr",
    "peak_power_kw": "peak_avg_electric_power_kw",
    "sized_mtow_kg": "sized_mtow_kg",
}


def _load_golden() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    with open(GOLDEN, newline="") as fh:
        for row in csv.DictReader(fh):
            stem = f"{row['vehicle']}-{row['alt_ft']}-{row['range_mi']}"
            # Divergent rows have empty metric cells; skip them here (they are
            # handled via EXPECTED_DIVERGENCES).
            if any(row[v] == "" for v in COLS.values()):
                continue
            out[stem] = {k: float(row[v]) for k, v in COLS.items()}
    return out


def main(study_id: str = "demo-abu-scitech-2026") -> int:
    golden = _load_golden()
    state = StudyStore(study_id).load_state()
    cases = {c["case_id"]: c for c in state["cases"].values() if c.get("in_spec", True)}

    mismatches: list[str] = []
    checked = 0
    max_rel = 0.0

    for stem, ref in sorted(golden.items()):
        case = cases.get(stem)
        if stem in EXPECTED_DIVERGENCES:
            status = case["status"] if case else "missing"
            print(f"  {stem:28s}  expected divergence -> status={status}")
            continue
        if case is None or case["status"] != "completed":
            mismatches.append(f"{stem}: not completed (status={case and case['status']})")
            continue

        outputs = case.get("outputs") or {}
        checked += 1
        for key, tol in TOL.items():
            got = float(outputs[key])
            want = ref[key]
            rel = abs(got - want) / max(abs(want), 1e-12)
            max_rel = max(max_rel, rel)
            if rel > tol:
                mismatches.append(
                    f"{stem}.{key}: got {got:.6g}, want {want:.6g} (rel {rel:.3%} > {tol:.3%})"
                )

    print(f"\nChecked {checked} converged case(s); max relative delta {max_rel:.3%}")
    if mismatches:
        print("\nMISMATCHES:")
        for m in mismatches:
            print("  -", m)
        return 1
    print("PASS: omd reproduces the evt Lane-A golden grid.")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
