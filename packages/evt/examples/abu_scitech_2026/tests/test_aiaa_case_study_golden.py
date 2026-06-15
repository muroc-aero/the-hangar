"""Golden: Lane A headline numbers pinned at the evtolpy reference.

Lane A is the paper's own method (direct evtolpy on the vendored configs), so
these are the reproduced equivalents of the paper's weight/energy/power summary
tables. Pinned so an upstream-pin bump that silently shifts the physics is
caught. A small subset runs by default; the full 18-case grid is marked slow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))

from shared import GOLDEN, all_cases, case_id  # noqa: E402

# 4 decimals pinned in GOLDEN; this tolerance catches a real physics shift
# while tolerating last-digit platform float noise.
_GOLD_TOL = dict(rtol=1e-4, atol=1e-4)

SUBSET = [
    ("archer-midnight", 1500, 30),
    ("supernal", 3000, 60),
    ("joby-s4", 1500, 60),  # diverging case: sized MTOW is None
]


def _check(vehicle, alt, rng):
    from lane_a.case_study import run_case

    row = run_case(vehicle, alt, rng)
    cid = case_id(vehicle, alt, rng)
    gold_e, gold_p, gold_m = GOLDEN[cid]

    np.testing.assert_allclose(
        row["total_mission_energy_kw_hr"], gold_e,
        err_msg=f"energy golden on {cid}", **_GOLD_TOL)
    np.testing.assert_allclose(
        row["peak_avg_electric_power_kw"], gold_p,
        err_msg=f"peak power golden on {cid}", **_GOLD_TOL)
    if gold_m is None:
        assert row["sized_mtow_kg"] is None, f"{cid} expected divergence"
        assert row["converged"] is False
    else:
        np.testing.assert_allclose(
            row["sized_mtow_kg"], gold_m,
            err_msg=f"sized MTOW golden on {cid}", **_GOLD_TOL)


@pytest.mark.golden_physics
@pytest.mark.parametrize("vehicle,alt,rng", SUBSET)
def test_golden_subset(vehicle, alt, rng):
    _check(vehicle, alt, rng)


@pytest.mark.slow
@pytest.mark.golden_physics
@pytest.mark.parametrize("vehicle,alt,rng", all_cases())
def test_golden_full_grid(vehicle, alt, rng):
    _check(vehicle, alt, rng)
