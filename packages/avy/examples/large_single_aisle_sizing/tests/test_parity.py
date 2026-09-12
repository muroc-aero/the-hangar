"""Parity tests: large single-aisle (737-class) sizing, Lane A vs Lane B.

Same structure as single_aisle_sizing -- a second airframe/deck through the
identical wrapper paths, with its own golden anchors.

Needs the aviary package -- run inside .venv-avy:
    .venv-avy/bin/python -m pytest packages/avy/examples/large_single_aisle_sizing/tests/ -v --rootdir=.
"""

import json
import sys
from pathlib import Path

import pytest

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from shared import (  # noqa: E402
    GOLDEN,
    METRICS,
    TARGET_RANGE_NM,
    TEMPLATE,
    TOL_GOLDEN,
    TOL_PARITY,
    TOL_RANGE,
)

LANE_B_DIR = DEMO_DIR / "lane_b"


async def run_lane_b(script_name: str) -> dict:
    """Run a Lane B JSON script in-process and return the last step's metrics."""
    from hangar.sdk.cli.runner import run_tool

    steps = json.loads((LANE_B_DIR / f"{script_name}.json").read_text())
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
    import importlib

    mod = importlib.import_module(f"lane_a.{script_name}")
    return mod.run()


def _tol(metric: str) -> dict:
    return TOL_RANGE if metric == "range_nmi" else TOL_PARITY


class TestLargeSingleAisleSizing:
    def test_lane_b_script_matches_contract(self):
        steps = json.loads((LANE_B_DIR / "sizing.json").read_text())
        args = {step["tool"]: step.get("args", {}) for step in steps}
        assert args["load_aircraft_template"]["template"] == TEMPLATE
        assert args["configure_mission"]["target_range_nm"] == TARGET_RANGE_NM

    @pytest.mark.slow
    @pytest.mark.golden_physics
    def test_lane_a_golden(self):
        a = run_lane_a("sizing")
        for metric in METRICS:
            assert a[metric] == pytest.approx(GOLDEN[metric], **TOL_GOLDEN), metric

    @pytest.mark.slow
    @pytest.mark.parity
    @pytest.mark.asyncio
    async def test_a_vs_b(self):
        a = run_lane_a("sizing")
        b = await run_lane_b("sizing")

        print(f"\n{'Metric':<24} {'Lane A':>14} {'Lane B':>14} {'Diff%':>10}")
        for metric in METRICS:
            diff = 100 * abs(b[metric] - a[metric]) / max(abs(a[metric]), 1e-12)
            print(f"{metric:<24} {a[metric]:>14.4f} {b[metric]:>14.4f} {diff:>9.5f}%")

        for metric in METRICS:
            assert b[metric] == pytest.approx(a[metric], **_tol(metric)), metric
