"""AIAA SciTech 2026 reproduction: omd evt/Sizing vs the Lane-A golden grid.

Drives the vendored case configs through the evt/Sizing factory (no study CLI)
and checks the sized MTOW, mission energy, and peak power against the
ground-truth grid the standalone evt lanes produce. Energy/power must match the
native model to floating point (read pre-sizing); sized MTOW is allowed the
documented upstream resizing-loop drift. The two Joby S4 60-mile cases must flag
non-convergence (``converged == 0``), not silently pass -- the native model maps
upstream's MTOW divergence to a flag rather than the black box's raised error.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

pytest.importorskip("evtol")

from hangar.omd.factories.evt import build_evt_sizing  # noqa: E402

_PKGS = Path(__file__).resolve().parents[2]
_CFG_DIR = _PKGS / "evt/examples/abu_scitech_2026/cfg"
_GOLDEN = _PKGS / "evt/examples/abu_scitech_2026/results/case_study_grid.csv"

EXPECTED_DIVERGENCES = {"joby-s4-1500-60", "joby-s4-3000-60"}
_MTOW_REL_TOL = 0.15  # documented upstream sizing drift


def _golden_rows() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(_GOLDEN, newline="") as fh:
        for row in csv.DictReader(fh):
            stem = f"{row['vehicle']}-{row['alt_ft']}-{row['range_mi']}"
            rows[stem] = row
    return rows


def _size(stem: str):
    prob, meta = build_evt_sizing(
        {"config_dir": str(_CFG_DIR), "config_name": stem}, {}
    )
    prob.setup(force_alloc_complex=bool(meta.get("force_alloc_complex")))
    for name, val in meta.get("initial_values", {}).items():
        prob.set_val(name, val)
    prob.run_model()
    return prob


def _converged_stems():
    return [s for s in sorted(_golden_rows()) if s not in EXPECTED_DIVERGENCES]


@pytest.mark.slow  # each case runs the native MTOW-closure solver to non-convergence
@pytest.mark.parametrize("stem", sorted(EXPECTED_DIVERGENCES))
def test_expected_divergences_flagged(stem):
    """Native maps upstream MTOW divergence to converged == 0 (outcome parity)."""
    prob = _size(stem)
    assert float(prob.get_val("converged")[0]) == 0.0


def _check_case(stem: str) -> None:
    ref = _golden_rows()[stem]
    prob = _size(stem)
    assert float(prob.get_val("total_mission_energy_kw_hr")[0]) == pytest.approx(
        float(ref["total_mission_energy_kw_hr"]), rel=1e-6
    )
    assert float(prob.get_val("peak_power_kw")[0]) == pytest.approx(
        float(ref["peak_avg_electric_power_kw"]), rel=1e-6
    )
    assert float(prob.get_val("sized_mtow_kg")[0]) == pytest.approx(
        float(ref["sized_mtow_kg"]), rel=_MTOW_REL_TOL
    )


@pytest.mark.slow  # 3 full sizing runs (~15s each; evtolpy has no memoization)
def test_pilot_subset_reproduces_golden():
    """Pilot: a few converged cases must match the golden grid exactly."""
    for stem in ("archer-midnight-1500-30", "joby-s4-3000-30", "supernal-1500-60"):
        _check_case(stem)


@pytest.mark.slow
@pytest.mark.parametrize("stem", _converged_stems())
def test_all_converged_cases_reproduce_golden(stem):
    _check_case(stem)
