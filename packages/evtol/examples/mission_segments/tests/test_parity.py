"""Parity tests: Lane A (direct evtolpy) vs Lane B (hangar-evtol MCP tools).

The three core upstream lanes -- mission-segment energy, power, and weight --
are reproduced by both the direct API (Lane A) and the MCP tool layer (Lane B),
built from the same shared CONFIG. Because both run identical pure-Python algebra,
parity is expected to floating-point round-off; any drift is a wrapper bug.

Also pins a few headline numbers as physics-invariant golden values, so an
upstream-pin bump that silently changes the physics is caught.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EXAMPLE_ROOT))

from shared import MASS_ATTRS, SEGMENT_KEYS, TOL  # noqa: E402


def _close(a, b, label, **tol):
    np.testing.assert_allclose(
        a, b, err_msg=f"Parity mismatch on '{label}': lane_a={a}, lane_b={b}", **tol
    )


# ---------------------------------------------------------------------------
# Lane runners
# ---------------------------------------------------------------------------

def _lane_a_energy():
    from lane_a.segment_energy import run
    return run()


def _lane_a_power():
    from lane_a.segment_power import run
    return run()


def _lane_a_mass():
    from lane_a.mass_breakdown import run
    return run()


def _lane_a_mtow():
    from lane_a.mtow_iteration import run
    return run()


async def _lane_b_mission():
    from lane_b.run_all import run_mission
    return await run_mission()


async def _lane_b_sizing():
    from lane_b.run_all import run_sizing_lane
    return await run_sizing_lane()


# ---------------------------------------------------------------------------
# Energy / power / mass parity
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.parity
class TestMissionParity:
    """Lane A vs Lane B for the three core mission tables."""

    async def test_segment_energy(self):
        a = _lane_a_energy()
        b = (await _lane_b_mission())["energy_kw_hr"]
        for key in SEGMENT_KEYS:
            _close(a[key], b[key], f"energy.{key}", **TOL)

    async def test_segment_power(self):
        a = _lane_a_power()
        b = (await _lane_b_mission())["avg_electric_power_kw"]
        for key in SEGMENT_KEYS:
            _close(a[key], b[key], f"power.{key}", **TOL)

    async def test_mass_breakdown(self):
        a = _lane_a_mass()
        b = (await _lane_b_mission())["mass_breakdown_kg"]
        for attr in MASS_ATTRS:
            _close(a[attr], b[attr], f"mass.{attr}", **TOL)
        # empty mass lives under totals on the Lane B side
        b_totals = (await _lane_b_mission())["totals"]
        _close(a["empty_mass_kg"], b_totals["empty_mass_kg"], "empty_mass_kg", **TOL)


@pytest.mark.slow
@pytest.mark.parity
class TestSizingParity:
    """Lane A vs Lane B for MTOW convergence."""

    async def test_sized_mtow(self):
        a = _lane_a_mtow()
        b = await _lane_b_sizing()
        _close(a["sized_mtow_kg"], b["sized_mtow_kg"], "sized_mtow_kg", **TOL)
        assert a["iterations"] == b["iterations"]

    async def test_history_matches(self):
        a = _lane_a_mtow()["history"]
        b = await _lane_b_sizing()
        assert len(a) == len(b["history"])
        for i, (ra, rb) in enumerate(zip(a, b["history"])):
            _close(ra["mtow_guess_kg"], rb["mtow_guess_kg"], f"hist[{i}].mtow_guess", **TOL)
            _close(ra["delta_kg"], rb["delta_kg"], f"hist[{i}].delta", **TOL)


# ---------------------------------------------------------------------------
# Golden physics (catch silent upstream-pin physics changes)
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.golden_physics
class TestGoldenPhysics:
    """Headline numbers pinned at the evtolpy reference."""

    async def test_golden_mission(self):
        r = await _lane_b_mission()
        _close(r["energy_kw_hr"]["cruise"], 124.289885, "cruise_energy", rtol=1e-6)
        _close(
            r["totals"]["total_mission_energy_kw_hr"], 166.77776,
            "total_mission_energy", rtol=1e-6,
        )

    async def test_golden_sizing(self):
        r = await _lane_b_sizing()
        _close(r["sized_mtow_kg"], 4076.0876, "sized_mtow", rtol=1e-5)
        assert r["iterations"] == 37
