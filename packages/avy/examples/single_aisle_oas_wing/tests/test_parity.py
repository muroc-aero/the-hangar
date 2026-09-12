"""Parity tests for the OAS-in-Aviary wing-mass example.

Lane A (raw upstream builder + set_val block) vs Lane B (hangar tool
surface, coupled and precompute modes). All three solve the identical
problem -- same component, same input values, same mission, SLSQP -- so
converged outputs must agree to round-off, and the two Lane B modes are
exactly equivalent by construction (feed-forward topology; see
docs/aviary-oas-integration-plan.md WP1).

Each converged run costs ~50 s (one nested wingbox sub-opt + the sizing),
so lane results are cached module-wide. Needs aviary + openaerostruct:

    .venv-avy/bin/python -m pytest packages/avy/examples/single_aisle_oas_wing/tests/ -v --rootdir=.
"""

import json
import sys
from pathlib import Path

import pytest

DEMO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEMO_DIR))

from shared import (  # noqa: E402
    GOLDEN,
    MAX_ITER,
    METRICS,
    MIN_WING_MASS_CONTRAST_REL,
    MISSION_TEMPLATE,
    OPTIMIZER,
    TEMPLATE,
    TOL_GOLDEN,
    TOL_PARITY,
    TOL_RANGE,
)

LANE_B_DIR = DEMO_DIR / "lane_b"

pytestmark = pytest.mark.slow

_cache: dict[str, dict] = {}


# ── Helpers ──────────────────────────────────────────────────────────────


def run_lane_a() -> dict:
    if "lane_a" not in _cache:
        import importlib

        mod = importlib.import_module("lane_a.coupled_sizing")
        _cache["lane_a"] = mod.run()
    return _cache["lane_a"]


async def run_lane_b(script_name: str) -> dict:
    """Run a Lane B JSON script in-process; return headline metrics."""
    if script_name in _cache:
        return _cache[script_name]
    from hangar.sdk.cli.runner import run_tool

    steps = json.loads((LANE_B_DIR / f"{script_name}.json").read_text())
    last_result = None
    for step in steps:
        resp = await run_tool(step["tool"], step.get("args", {}))
        assert resp.get("ok"), f"Lane B step {step['tool']} failed: {resp.get('error')}"
        last_result = resp.get("result", {})

    validation = last_result.get("validation", {})
    assert validation.get("passed"), f"Lane B validation failed: {validation}"
    metrics = dict(last_result["results"]["performance"])
    metrics["wing_mass_lbm"] = last_result["results"]["design"]["wing_mass_lbm"]
    _cache[script_name] = metrics
    return metrics


def _tol(metric: str) -> dict:
    return TOL_RANGE if metric == "range_nmi" else TOL_PARITY


def _assert_parity(a: dict, b: dict) -> None:
    print(f"\n{'Metric':<24} {'Lane A':>14} {'Lane B':>14} {'Diff%':>10}")
    for metric in METRICS:
        diff = 100 * abs(b[metric] - a[metric]) / max(abs(a[metric]), 1e-12)
        print(f"{metric:<24} {a[metric]:>14.4f} {b[metric]:>14.4f} {diff:>9.5f}%")
    for metric in METRICS:
        assert b[metric] == pytest.approx(a[metric], **_tol(metric)), metric


# ── Golden anchor (pins Lane A against upstream regressions) ─────────────


def test_lane_a_matches_golden():
    a = run_lane_a()
    for metric in METRICS:
        assert a[metric] == pytest.approx(GOLDEN[metric], **TOL_GOLDEN), metric


# ── Lane parity ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lane_b_coupled_parity():
    _assert_parity(run_lane_a(), await run_lane_b("coupled_sizing"))


@pytest.mark.asyncio
async def test_lane_b_precompute_equivalence():
    """Precompute mode must equal the coupled oracle (feed-forward topology)."""
    _assert_parity(run_lane_a(), await run_lane_b("precompute_sizing"))


# ── The integration does something ───────────────────────────────────────


@pytest.mark.asyncio
async def test_oas_wing_mass_differs_from_flops():
    """A FLOPS-only sizing on the same mission must give a different wing mass."""
    from hangar.sdk.cli.runner import run_tool

    for step in (
        ("load_aircraft_template", {"template": TEMPLATE, "name": "baseline"}),
        (
            "configure_mission",
            {"aircraft_name": "baseline", "mission_template": MISSION_TEMPLATE},
        ),
        (
            "run_sizing",
            {"aircraft_name": "baseline", "optimizer": OPTIMIZER, "max_iter": MAX_ITER},
        ),
    ):
        resp = await run_tool(step[0], step[1])
        assert resp.get("ok"), f"baseline step {step[0]} failed: {resp.get('error')}"

    baseline_wing = resp["result"]["results"]["design"]["wing_mass_lbm"]
    oas_wing = (await run_lane_b("coupled_sizing"))["wing_mass_lbm"]
    rel = abs(oas_wing - baseline_wing) / baseline_wing
    print(f"\nFLOPS wing mass {baseline_wing:.1f} lbm, OAS {oas_wing:.1f} lbm "
          f"({100 * rel:.1f}% apart)")
    assert rel > MIN_WING_MASS_CONTRAST_REL


# ── Lane B contract checks (fast; pin scripts to shared constants) ───────


def _lane_b_args(script_name: str) -> dict:
    steps = json.loads((LANE_B_DIR / f"{script_name}.json").read_text())
    return {step["tool"]: step.get("args", {}) for step in steps}


@pytest.mark.parametrize("script", ["coupled_sizing", "precompute_sizing"])
def test_lane_b_scripts_match_shared(script):
    args = _lane_b_args(script)
    assert args["load_aircraft_template"]["template"] == TEMPLATE
    assert args["add_external_subsystem"]["subsystem"] == "oas_wing_mass"
    assert args["configure_mission"]["mission_template"] == MISSION_TEMPLATE
    assert args["run_sizing"]["optimizer"] == OPTIMIZER
    assert args["run_sizing"]["max_iter"] == MAX_ITER
    expected_mode = "coupled" if script == "coupled_sizing" else "precompute"
    assert args["run_sizing"]["subsystem_mode"] == expected_mode
