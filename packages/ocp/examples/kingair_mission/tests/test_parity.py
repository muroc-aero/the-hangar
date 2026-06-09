"""Parity tests for the King Air C90GT three-lane demonstration.

Verification ladder for the twin-turboprop parity work (#36, #38, #39):

  * Lane A is the upstream OpenConcept ``run_kingair_analysis`` -- the reference.
  * Lane B drives the same analysis through the OCP MCP tools (load template,
    set architecture, configure_mission with calibration params, run).
  * test_b_matches_a asserts Lane B reproduces Lane A within tolerance.

If any of the three fixes regress, Lane B diverges from Lane A and these fail:
  * #36 missing -> structural_fudge / takeoff_throttle ignored (OEW + TOFL off)
  * #38 missing -> OEW undercounts one PT6A; TOFL ignores engine-out
  * #39 missing -> prop rpm defaults to 2000 instead of 1900 (TOFL off)

Run with:
    uv run python -m pytest packages/ocp/examples/kingair_mission/tests/ -v --rootdir=.
"""

import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from shared import TOL_FUEL, TOL_OEW, TOL_SCALARS, TOL_TOFL

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


class TestFullMission:
    """Compare the full King Air mission across lanes."""

    @pytest.mark.slow
    def test_lane_a(self):
        r = run_lane_a("full_mission")
        assert r["fuel_burn_kg"] > 0
        assert r["OEW_kg"] > 0
        assert r["OEW_kg"] < r["MTOW_kg"], "OEW should be below MTOW"
        assert 0 < r["TOFL_ft"] < 10000, "TOFL should be a sane balanced-field length"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_lane_b(self):
        r = await run_lane_b("full_mission")
        assert r["fuel_burn_kg"] > 0
        assert r["OEW_kg"] > 0
        assert r.get("TOFL_ft", 0) > 0

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_b_matches_a(self):
        """Lane B (OCP builder) must reproduce Lane A (upstream OpenConcept).

        This is the comparison check that ``compare.py`` prints by eye, asserted
        across all four reported metrics. With both lanes converged to Newton
        1e-10, OEW/fuel/MTOW match exactly and TOFL to ~6 digits.
        """
        a = run_lane_a("full_mission")
        b = await run_lane_b("full_mission")
        np.testing.assert_allclose(b["OEW_kg"], a["OEW_kg"], **TOL_OEW)
        np.testing.assert_allclose(b["fuel_burn_kg"], a["fuel_burn_kg"], **TOL_FUEL)
        np.testing.assert_allclose(b["MTOW_kg"], a["MTOW_kg"], **TOL_SCALARS)
        np.testing.assert_allclose(b["TOFL_ft"], a["TOFL_ft"], **TOL_TOFL)
