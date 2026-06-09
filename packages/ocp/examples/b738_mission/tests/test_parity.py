"""Parity tests for the Boeing 737-800 three-lane demonstration.

  * Lane A is the upstream OpenConcept ``run_738_analysis`` -- the reference.
  * Lane B drives the same b738 aircraft through the OCP MCP tools (load
    template, set twin_turbofan architecture, configure_mission with the
    with_reserve profile, run).

Unlike kingair_mission, these tests do **not** assert bit-for-bit parity. The
upstream B738 ramps every phase speed with ``np.linspace`` and flies the reserve
diversion at jet speeds, whereas ``configure_mission`` exposes only constant
per-phase speeds and defaults the reserve speeds to GA values. So:

  * block fuel (descent.fuel_used_final) agrees only to within a few percent
    (TOL_BLOCK_FUEL),
  * OEW/MTOW come from the shared aircraft data dict and match closely,
  * the reserve total is intentionally NOT compared -- the reserve-phase speed
    mismatch makes a strict assertion meaningless. See ../README.md.

Run with:
    uv run python -m pytest packages/ocp/examples/b738_mission/tests/ -v --rootdir=.
"""

import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from shared import TOL_BLOCK_FUEL, TOL_OEW, TOL_MTOW

LANE_B_DIR = DEMO_DIR / "lane_b"


async def run_lane_b(script_name: str) -> dict:
    """Run a Lane B JSON script in-process and return the last step's results."""
    from hangar.sdk.cli.runner import run_tool

    script_path = LANE_B_DIR / f"{script_name}.json"
    steps = json.loads(script_path.read_text())
    last_result = None
    for step in steps:
        resp = await run_tool(step["tool"], step.get("args", {}))
        assert resp.get("ok"), f"Lane B step {step['tool']} failed: {resp.get('error')}"
        last_result = resp.get("result", {})

    if last_result and "results" in last_result:
        return last_result["results"]
    return last_result


def run_lane_a(script_name: str) -> dict:
    """Import and run a Lane A script, return its result dict."""
    mod = importlib.import_module(f"lane_a.{script_name}")
    return mod.run()


class TestReserveMission:
    """Compare the B738 reserve mission across lanes."""

    @pytest.mark.slow
    def test_lane_a(self):
        r = run_lane_a("reserve_mission")
        assert r["fuel_burn_kg"] > 0
        assert r["total_fuel_with_reserve_kg"] >= r["fuel_burn_kg"], (
            "total fuel (incl. reserve) must be at least the block fuel"
        )
        assert r["MTOW_kg"] > 0

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_lane_b(self):
        r = await run_lane_b("reserve_mission")
        assert r["fuel_burn_kg"] > 0
        assert r.get("total_fuel_with_reserve_kg", 0) > 0
        assert r["MTOW_kg"] > 0

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_b_approximates_a(self):
        """Lane B (OCP builder) approximates Lane A (upstream OpenConcept).

        Block fuel is compared with a loose tolerance; OEW/MTOW closely. The
        reserve total is deliberately not asserted -- see the module docstring.
        """
        a = run_lane_a("reserve_mission")
        b = await run_lane_b("reserve_mission")

        np.testing.assert_allclose(b["fuel_burn_kg"], a["fuel_burn_kg"], **TOL_BLOCK_FUEL)
        np.testing.assert_allclose(b["MTOW_kg"], a["MTOW_kg"], **TOL_MTOW)
        if a.get("OEW_kg") is not None and b.get("OEW_kg") is not None:
            np.testing.assert_allclose(b["OEW_kg"], a["OEW_kg"], **TOL_OEW)
