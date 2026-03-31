"""Parity tests: verify Lane A (raw OpenConcept) and Lane B (MCP) produce matching results.

Run with:
    uv run python -m pytest packages/ocp/examples/caravan_mission/tests/ -v --rootdir=.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the demonstrations package importable
DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from shared import TOL_FUEL, TOL_OEW, TOL_SCALARS, TOL_TOFL

LANE_B_DIR = DEMO_DIR / "lane_b"


# ── Helpers ──────────────────────────────────────────────────────────────


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
    import importlib
    mod = importlib.import_module(f"lane_a.{script_name}")
    return mod.run()


# ── Basic Mission ────────────────────────────────────────────────────────


class TestBasicMission:
    """Compare basic (3-phase) Caravan mission across lanes."""

    @pytest.mark.slow
    def test_lane_a(self):
        r = run_lane_a("basic_mission")
        assert r["fuel_burn_kg"] > 0, "Fuel burn should be positive"
        assert r["OEW_kg"] > 0, "OEW should be positive"
        assert r["OEW_kg"] < r["MTOW_kg"], "OEW should be less than MTOW"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_lane_b(self):
        r = await run_lane_b("basic_mission")
        assert r["fuel_burn_kg"] > 0
        assert r["OEW_kg"] > 0

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        a = run_lane_a("basic_mission")
        b = await run_lane_b("basic_mission")
        np.testing.assert_allclose(a["fuel_burn_kg"], b["fuel_burn_kg"], **TOL_FUEL)


# ── Full Mission ─────────────────────────────────────────────────────────


class TestFullMission:
    """Compare full (with takeoff) Caravan mission across lanes."""

    @pytest.mark.slow
    def test_lane_a(self):
        r = run_lane_a("full_mission")
        assert r["fuel_burn_kg"] > 0
        assert r["TOFL_ft"] > 0
        assert r["TOFL_ft"] < 10000  # reasonable TOFL

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_lane_b(self):
        r = await run_lane_b("full_mission")
        assert r["fuel_burn_kg"] > 0
        assert r.get("TOFL_ft") is not None or r.get("TOFL_ft", 0) > 0

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        a = run_lane_a("full_mission")
        b = await run_lane_b("full_mission")
        np.testing.assert_allclose(a["fuel_burn_kg"], b["fuel_burn_kg"], **TOL_FUEL)


# ── Hybrid Mission ───────────────────────────────────────────────────────


class TestHybridMission:
    """Compare hybrid twin mission across lanes."""

    @pytest.mark.slow
    def test_lane_a(self):
        r = run_lane_a("hybrid_mission")
        assert r["fuel_burn_kg"] > 0
        assert r["battery_SOC_final"] >= -0.01, "Battery should not be significantly over-discharged"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_lane_b(self):
        r = await run_lane_b("hybrid_mission")
        assert r["fuel_burn_kg"] > 0

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        a = run_lane_a("hybrid_mission")
        b = await run_lane_b("hybrid_mission")
        # Hybrid has ~1% difference because the upstream example sets post-setup
        # overrides (structural_fudge, propeller diameter) that the MCP wrapper
        # doesn't replicate. The dynamic model factory builds from aircraft data
        # only, so slight OEW differences propagate to fuel burn.
        np.testing.assert_allclose(a["fuel_burn_kg"], b["fuel_burn_kg"], rtol=0.02)
