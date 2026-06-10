"""Lane C parity tests: Lane A (direct scripts) vs the omd MCP tool surface.

Lane C in the examples is the agent path: an agent authors and runs a
plan entirely through the omd MCP tools, with no filesystem access.
These tests script that path in process -- plan_init ->
plan_add_component -> plan_set_solver -> assemble_plan -> validate_plan
-> run_plan -> get_results -- and compare results against the Lane A
reference scripts, so tool-surface parity is covered in CI without a
live agent.

The live-agent version of this check (a blind agent driving a real MCP
session via the Agent SDK) is the eval harness in
packages/omd/examples/agent_eval/.

Run with -s to see comparison tables:

    uv run pytest packages/omd/examples/tests/test_parity_lane_c.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hangar.omd.tools.authoring import (
    plan_add_component,
    plan_add_dv,
    plan_init,
    plan_set_objective,
    plan_set_operating_point,
    plan_set_solver,
)
from hangar.omd.tools.execution import assemble_plan, run_plan, validate_plan
from hangar.omd.tools.results_tools import get_results

from .test_parity import _print_comparison

EXAMPLES_DIR = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def isolate_data_root(tmp_path_factory, monkeypatch):
    """Point the omd data root (tool workspace, plots, n2) at a temp dir.

    The shared conftest already isolates the DB / plan store / recordings.
    """
    monkeypatch.setenv(
        "OMD_DATA_ROOT", str(tmp_path_factory.mktemp("omd_data"))
    )
    yield


def _summary(env: dict) -> dict:
    """Unwrap a run_plan envelope, failing loudly on an error envelope."""
    assert "error" not in env, env.get("error")
    assert env["results"]["status"] in ("completed", "converged")
    return env["results"]["summary"]


async def _assemble_and_validate(plan_dir: str) -> str:
    assembled = await assemble_plan(plan_dir)
    assert not assembled["errors"], assembled["errors"]
    plan_yaml = assembled["output_path"]
    check = await validate_plan(plan_yaml)
    assert check["valid"] is True, check.get("errors")
    return plan_yaml


def _mission_config(mission: dict, slots: dict | None = None) -> dict:
    """Build an ocp/BasicMission component config from a shared MISSION dict."""
    config = {
        "aircraft_template": "caravan",
        "architecture": "turboprop",
        "num_nodes": mission["num_nodes"],
        "mission_params": {
            k: v for k, v in mission.items() if k != "num_nodes"
        },
    }
    if slots:
        config["slots"] = slots
    return config


async def _set_newton_solver(plan_dir: str) -> None:
    """Match the Newton/Direct solver setup the Lane A scripts use."""
    await plan_set_solver(
        plan_dir,
        nonlinear="NewtonSolver",
        linear="DirectSolver",
        nonlinear_options={"maxiter": 20, "atol": 1.0e-10, "rtol": 1.0e-10},
    )


class TestParaboloidLaneC:

    async def test_analysis_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "paraboloid"))
        from paraboloid.lane_a.analysis import run as lane_a_run

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-para-analysis", plan_id="lane-c-para-analysis",
            name="Paraboloid analysis (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-para-analysis", comp_id="paraboloid",
            comp_type="paraboloid/Paraboloid", config={},
        )
        await plan_set_operating_point(
            "lane-c-para-analysis", fields={"x": lane_a["x"], "y": lane_a["y"]}
        )
        plan_yaml = await _assemble_and_validate("lane-c-para-analysis")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison("Paraboloid Analysis (Lane C)", lane_a, summary)

        assert summary["f_xy"] == pytest.approx(lane_a["f_xy"], rel=1e-12)

    async def test_optimization_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "paraboloid"))
        from paraboloid.lane_a.optimization import run as lane_a_run

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-para-opt", plan_id="lane-c-para-opt",
            name="Paraboloid optimization (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-para-opt", comp_id="paraboloid",
            comp_type="paraboloid/Paraboloid", config={},
        )
        await plan_set_operating_point(
            "lane-c-para-opt", fields={"x": 0.0, "y": 0.0}
        )
        await plan_add_dv("lane-c-para-opt", name="x", lower=-50.0, upper=50.0)
        await plan_add_dv("lane-c-para-opt", name="y", lower=-50.0, upper=50.0)
        await plan_set_objective("lane-c-para-opt", name="f_xy")
        plan_yaml = await _assemble_and_validate("lane-c-para-opt")

        env = await run_plan(plan_yaml, mode="optimize")
        summary = _summary(env)
        f_xy = summary.get("f_xy", summary.get("paraboloid.f_xy"))

        _print_comparison("Paraboloid Optimization (Lane C)", lane_a, summary)

        assert f_xy == pytest.approx(lane_a["f_xy"], rel=1e-4)

        # The optimum must also be retrievable through the results tool.
        result = await get_results(env["run_id"], summary=True)
        assert result.get("final") or result.get("run_id") == env["run_id"]


class TestOCPCaravanBasicLaneC:

    @pytest.mark.slow
    async def test_basic_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_caravan_basic"))
        from ocp_caravan_basic.lane_a.basic_mission import run as lane_a_run
        from ocp_caravan_basic.shared import MISSION

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-caravan-basic", plan_id="lane-c-caravan-basic",
            name="Caravan basic mission (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-caravan-basic", comp_id="caravan-mission",
            comp_type="ocp/BasicMission", config=_mission_config(MISSION),
        )
        await _set_newton_solver("lane-c-caravan-basic")
        plan_yaml = await _assemble_and_validate("lane-c-caravan-basic")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "OCP Caravan Basic Mission (Lane C)", lane_a, summary,
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPOASCoupledLaneC:

    @pytest.mark.slow
    async def test_coupled_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_oas_coupled"))
        from ocp_oas_coupled.lane_a.coupled_mission import run as lane_a_run
        from ocp_oas_coupled.shared import MISSION, VLM_CONFIG

        lane_a = lane_a_run()

        slots = {"drag": {"provider": "oas/vlm", "config": dict(VLM_CONFIG)}}
        await plan_init(
            "lane-c-ocp-oas-coupled", plan_id="lane-c-ocp-oas-coupled",
            name="Caravan mission with VLM drag slot (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-ocp-oas-coupled", comp_id="mission",
            comp_type="ocp/BasicMission",
            config=_mission_config(MISSION, slots=slots),
        )
        await _set_newton_solver("lane-c-ocp-oas-coupled")
        plan_yaml = await _assemble_and_validate("lane-c-ocp-oas-coupled")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "OCP+OAS Coupled Mission (Lane C, VLM drag slot)", lane_a, summary,
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )
