"""Parity: Lane A (direct evtolpy) vs Lane B (evt tools) vs Lane C (study).

All three lanes read the same vendored case configs and run identical algebra,
so headline metrics agree to floating-point round-off; any drift is a wrapper
bug. A representative subset is checked (one per vehicle at 1500 ft, including
the diverging Joby S4 60-mile case) so the suite stays fast; the full 18-case
grid is pinned by the golden test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))

from shared import TOL  # noqa: E402

# (vehicle, alt_ft, range_mi): a converging case per vehicle plus the diverging
# Joby S4 60-mile case, so both branches of the sizing path are exercised.
SUBSET = [
    ("archer-midnight", 1500, 30),
    ("supernal", 1500, 45),
    ("joby-s4", 1500, 30),
    ("joby-s4", 1500, 60),  # diverges: sized_mtow is None in both lanes
]


def _lane_a(vehicle, alt, rng):
    from lane_a.case_study import run_case
    return run_case(vehicle, alt, rng)


async def _lane_b(vehicle, alt, rng):
    from lane_b.run_all import run_case
    return await run_case(vehicle, alt, rng)


@pytest.mark.parity
@pytest.mark.parametrize("vehicle,alt,rng", SUBSET)
async def test_lane_b_matches_lane_a(vehicle, alt, rng):
    a = _lane_a(vehicle, alt, rng)
    b = await _lane_b(vehicle, alt, rng)

    label = f"{vehicle}-{alt}-{rng}"
    np.testing.assert_allclose(
        b["total_mission_energy_kw_hr"], a["total_mission_energy_kw_hr"],
        err_msg=f"energy parity on {label}", **TOL)
    np.testing.assert_allclose(
        b["peak_avg_electric_power_kw"], a["peak_avg_electric_power_kw"],
        err_msg=f"peak power parity on {label}", **TOL)

    assert b["converged"] == a["converged"], f"converged flag differs on {label}"
    if a["converged"]:
        np.testing.assert_allclose(
            b["sized_mtow_kg"], a["sized_mtow_kg"],
            err_msg=f"sized MTOW parity on {label}", **TOL)
    else:
        # The diverging case: both lanes record no sized MTOW.
        assert a["sized_mtow_kg"] is None
        assert b["sized_mtow_kg"] is None


@pytest.mark.parity
def test_lane_c_matches_lane_a():
    """Lane C (declarative study via the evt runner) vs Lane A for its cells."""
    from lane_c.compare_to_lane_a import run_lane_c
    from lane_a.case_study import run_case

    rows = run_lane_c()
    assert [r["range_mi"] for r in rows] == [30, 45, 60]
    for row in rows:
        assert row["status"] == "completed", f"{row['case_id']}: {row['error']}"
        a = run_case("archer-midnight", 1500, row["range_mi"])
        np.testing.assert_allclose(
            row["outputs"]["total_mission_energy_kw_hr"],
            a["total_mission_energy_kw_hr"],
            err_msg=f"energy C vs A on {row['case_id']}", **TOL)
        np.testing.assert_allclose(
            row["outputs"]["sized_mtow_kg"], a["sized_mtow_kg"],
            err_msg=f"MTOW C vs A on {row['case_id']}", **TOL)
