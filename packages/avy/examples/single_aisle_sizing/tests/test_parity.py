"""Parity tests: verify Lane A (raw Aviary) and Lane B (MCP) produce matching results.

Both lanes run the identical sizing optimization (same deck, same default
energy_state phase_info, SLSQP, max_iter=50), so converged outputs must
agree to round-off. Lane A is additionally pinned to GOLDEN anchors so an
upstream physics regression on a pin bump is caught independently of
lane-to-lane agreement.

Needs the aviary package -- run inside .venv-avy:
    .venv-avy/bin/python -m pytest packages/avy/examples/single_aisle_sizing/tests/ -v --rootdir=.
"""

import json
import sys
from pathlib import Path

import pytest

# Make the example package importable
DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from shared import (  # noqa: E402
    AR_OVERRIDE,
    GOLDEN,
    GOLDEN_OVERRIDE,
    GOLDEN_SHORT,
    METRICS,
    SHORT_CRUISE_SEGMENTS,
    SHORT_RANGE_NM,
    TOL_GOLDEN,
    TOL_PARITY,
    TOL_RANGE,
)

LANE_B_DIR = DEMO_DIR / "lane_b"


# ── Helpers ──────────────────────────────────────────────────────────────


async def run_lane_b(script_name: str) -> dict:
    """Run a Lane B JSON script in-process and return the last step's metrics."""
    from hangar.sdk.cli.runner import run_tool

    script_path = LANE_B_DIR / f"{script_name}.json"
    steps = json.loads(script_path.read_text())
    last_result = None
    for step in steps:
        resp = await run_tool(step["tool"], step.get("args", {}))
        assert resp.get("ok"), f"Lane B step {step['tool']} failed: {resp.get('error')}"
        last_result = resp.get("result", {})

    assert last_result is not None
    validation = last_result.get("validation", {})
    assert validation.get("passed"), f"Lane B validation failed: {validation}"
    return last_result["results"]["performance"]


def run_lane_a(script_name: str) -> dict:
    """Import and run a Lane A script, return its metric dict."""
    import importlib

    mod = importlib.import_module(f"lane_a.{script_name}")
    return mod.run()


def _tol(metric: str) -> dict:
    return TOL_RANGE if metric == "range_nmi" else TOL_PARITY


def _print_diff(a: dict, b: dict) -> None:
    print(f"\n{'Metric':<24} {'Lane A':>14} {'Lane B':>14} {'Diff%':>10}")
    for metric in METRICS:
        diff = 100 * abs(b[metric] - a[metric]) / max(abs(a[metric]), 1e-12)
        print(f"{metric:<24} {a[metric]:>14.4f} {b[metric]:>14.4f} {diff:>9.5f}%")


def _assert_parity(a: dict, b: dict) -> None:
    _print_diff(a, b)
    for metric in METRICS:
        assert b[metric] == pytest.approx(a[metric], **_tol(metric)), metric


def _lane_b_args(script_name: str) -> dict:
    """tool -> args map from a Lane B script, for contract checks vs shared.py."""
    steps = json.loads((LANE_B_DIR / f"{script_name}.json").read_text())
    return {step["tool"]: step.get("args", {}) for step in steps}


# ── Sizing parity ────────────────────────────────────────────────────────


class TestSingleAisleSizing:
    """Compare the single-aisle sizing across lanes and against golden anchors."""

    @pytest.mark.slow
    @pytest.mark.golden_physics
    def test_lane_a_golden(self):
        """Lane A pinned to upstream v1.0.1 values (regression anchor)."""
        a = run_lane_a("sizing")
        for metric in METRICS:
            assert a[metric] == pytest.approx(GOLDEN[metric], **TOL_GOLDEN), metric

    @pytest.mark.slow
    @pytest.mark.parity
    @pytest.mark.asyncio
    async def test_lane_b(self):
        """Lane B runs and produces physically sane results."""
        b = await run_lane_b("sizing")
        assert b["gross_mass_lbm"] > 0
        assert b["total_fuel_mass_lbm"] > 0
        assert b["zero_fuel_mass_lbm"] < b["gross_mass_lbm"]

    @pytest.mark.slow
    @pytest.mark.parity
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        """The wrapper reproduces the raw upstream run metric-for-metric."""
        a = run_lane_a("sizing")
        b = await run_lane_b("sizing")
        _assert_parity(a, b)


# ── Deck-override parity ─────────────────────────────────────────────────


class TestOverrideSizing:
    """AR-override sizing: exercises the define_aircraft deck-override path."""

    def test_lane_b_script_matches_contract(self):
        """The Lane B JSON must carry the exact override from shared.py."""
        args = _lane_b_args("override_sizing")
        assert args["define_aircraft"]["overrides"] == AR_OVERRIDE

    @pytest.mark.slow
    @pytest.mark.golden_physics
    def test_lane_a_golden(self):
        a = run_lane_a("override_sizing")
        for metric in METRICS:
            assert a[metric] == pytest.approx(GOLDEN_OVERRIDE[metric], **TOL_GOLDEN), metric

    @pytest.mark.slow
    @pytest.mark.parity
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        a = run_lane_a("override_sizing")
        b = await run_lane_b("override_sizing")
        _assert_parity(a, b)


# ── Mission-override parity ──────────────────────────────────────────────


class TestShortMission:
    """1200 nmi / coarse-cruise sizing: exercises the configure_mission path."""

    def test_lane_b_script_matches_contract(self):
        """The Lane B JSON must carry the exact mission mods from shared.py."""
        args = _lane_b_args("short_mission")
        mission = args["configure_mission"]
        assert mission["target_range_nm"] == SHORT_RANGE_NM
        assert mission["phase_options"]["cruise"]["num_segments"] == SHORT_CRUISE_SEGMENTS

    @pytest.mark.slow
    @pytest.mark.golden_physics
    def test_lane_a_golden(self):
        a = run_lane_a("short_mission")
        for metric in METRICS:
            assert a[metric] == pytest.approx(GOLDEN_SHORT[metric], **TOL_GOLDEN), metric

    @pytest.mark.slow
    @pytest.mark.parity
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        a = run_lane_a("short_mission")
        b = await run_lane_b("short_mission")
        _assert_parity(a, b)
