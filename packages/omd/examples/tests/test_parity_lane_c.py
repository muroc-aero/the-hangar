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
    plan_set_composition_policy,
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


def _mission_config(
    mission: dict,
    slots: dict | None = None,
    *,
    template: str = "caravan",
    architecture: str = "turboprop",
    solver_settings: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Build an ocp mission component config from a shared MISSION dict."""
    config = {
        "aircraft_template": template,
        "architecture": architecture,
        "num_nodes": mission["num_nodes"],
        "mission_params": {
            k: v for k, v in mission.items() if k != "num_nodes"
        },
    }
    if solver_settings:
        config["solver_settings"] = solver_settings
    if slots:
        config["slots"] = slots
    if extra:
        config.update(extra)
    return config


# The Newton settings the OCP Lane B plans embed in their component config.
_OCP_NEWTON = {
    "solver_type": "newton", "maxiter": 20, "atol": 1.0e-10, "rtol": 1.0e-10,
}


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

        _print_comparison("Paraboloid Analysis (Lane C)", lane_a, summary,
                          case="paraboloid_analysis", lane_label="C")

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

        _print_comparison("Paraboloid Optimization (Lane C)", lane_a, summary,
                          case="paraboloid_optimization", lane_label="C")

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
            case="ocp_caravan_basic", lane_label="C",
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
            case="ocp_oas_coupled", lane_label="C",
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestEvtNativeSizingLaneC:

    @pytest.mark.slow
    async def test_sizing_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "evt_native_sizing"))
        from evt_native_sizing.lane_a.sizing import run as lane_a_run
        from evt_native_sizing.shared import CONFIG_DIR, CONFIG_NAME, TOL_PARITY

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-evt-native", plan_id="lane-c-evt-native",
            name="Native eVTOL sizing (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-evt-native", comp_id="evtol",
            comp_type="evt/Sizing",
            config={
                "config_dir": CONFIG_DIR,
                "config_name": CONFIG_NAME,
                "solver": "newton",
            },
        )
        plan_yaml = await _assemble_and_validate("lane-c-evt-native")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        keys = ["sized_mtow_kg", "total_mission_energy_kw_hr", "peak_power_kw"]
        _print_comparison("Native eVTOL Sizing (Lane C)", lane_a, summary,
                          keys=keys, case="evt_native_sizing", lane_label="C")

        assert summary["converged"] == 1.0
        for k in keys:
            assert summary[k] == pytest.approx(lane_a[k], **TOL_PARITY)


class TestOASAeroLaneC:

    @pytest.mark.slow
    async def test_aero_analysis_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "oas_aero_rect"))
        from oas_aero_rect.lane_a.aero_analysis import run as lane_a_run
        from oas_aero_rect.shared import FLIGHT, WING

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-oas-aero", plan_id="lane-c-oas-aero",
            name="Rect wing VLM analysis (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-oas-aero", comp_id="wing", comp_type="oas/AeroPoint",
            config={"surfaces": [dict(WING)]},
        )
        await plan_set_operating_point("lane-c-oas-aero", fields=dict(FLIGHT))
        plan_yaml = await _assemble_and_validate("lane-c-oas-aero")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison("OAS Aero Analysis (Lane C)", lane_a, summary,
                          keys=["CL", "CD"],
                          case="oas_aero_rect", lane_label="C")

        assert summary["CL"] == pytest.approx(lane_a["CL"], rel=1e-6)
        assert summary["CD"] == pytest.approx(lane_a["CD"], rel=1e-6)


class TestOASAerostructLaneC:

    @pytest.mark.slow
    async def test_aerostruct_analysis_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "oas_aerostruct_rect"))
        from oas_aerostruct_rect.lane_a.aerostruct_analysis import (
            run as lane_a_run,
        )
        from oas_aerostruct_rect.shared import FLIGHT, WING

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-oas-aerostruct", plan_id="lane-c-oas-aerostruct",
            name="Rect wing aerostruct analysis (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-oas-aerostruct", comp_id="wing",
            comp_type="oas/AerostructPoint",
            config={"surfaces": [dict(WING)]},
        )
        # Match the Lane B solvers.yaml (not shared.SOLVERS, which the Lane A
        # script applies to its own hand-built coupled group).
        await plan_set_solver(
            "lane-c-oas-aerostruct",
            nonlinear="NewtonSolver", linear="DirectSolver",
            nonlinear_options={"maxiter": 20, "atol": 1.0e-6},
        )
        await plan_set_operating_point(
            "lane-c-oas-aerostruct", fields=dict(FLIGHT)
        )
        plan_yaml = await _assemble_and_validate("lane-c-oas-aerostruct")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison("OAS Aerostruct Analysis (Lane C)", lane_a, summary,
                          keys=["CL", "CD"],
                          case="oas_aerostruct_rect", lane_label="C")

        assert summary["CL"] == pytest.approx(lane_a["CL"], rel=1e-6)
        assert summary["CD"] == pytest.approx(lane_a["CD"], rel=1e-6)


class TestOCPCaravanFullLaneC:

    @pytest.mark.slow
    async def test_full_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_caravan_full"))
        from ocp_caravan_full.lane_a.full_mission import run as lane_a_run
        from ocp_caravan_full.shared import MISSION

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-caravan-full", plan_id="lane-c-caravan-full",
            name="Caravan full mission (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-caravan-full", comp_id="caravan-mission",
            comp_type="ocp/FullMission",
            config=_mission_config(MISSION, solver_settings=dict(_OCP_NEWTON)),
        )
        plan_yaml = await _assemble_and_validate("lane-c-caravan-full")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "OCP Caravan Full Mission (Lane C)", lane_a, summary,
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
            case="ocp_caravan_full", lane_label="C",
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPHybridTwinLaneC:

    @pytest.mark.slow
    async def test_hybrid_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_hybrid_twin"))
        from ocp_hybrid_twin.lane_a.hybrid_mission import run as lane_a_run
        from ocp_hybrid_twin.shared import MISSION, PROPULSION

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-hybrid-twin", plan_id="lane-c-hybrid-twin",
            name="King Air series-hybrid mission (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-hybrid-twin", comp_id="hybrid-mission",
            comp_type="ocp/FullMission",
            config=_mission_config(
                MISSION,
                template="kingair",
                architecture=PROPULSION["architecture"],
                solver_settings=dict(_OCP_NEWTON),
                extra={
                    "propulsion_overrides": {
                        "battery_specific_energy":
                            PROPULSION["battery_specific_energy"],
                    },
                },
            ),
        )
        plan_yaml = await _assemble_and_validate("lane-c-hybrid-twin")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "OCP Hybrid Twin Mission (Lane C)", lane_a, summary,
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
            case="ocp_hybrid_twin", lane_label="C",
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOASOCPCombinedLaneC:

    @pytest.mark.slow
    async def test_wing_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "oas_ocp_combined"))
        from oas_ocp_combined.lane_a.wing_mission import run as lane_a_run
        from oas_ocp_combined.shared import FLIGHT, MISSION, WING

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-oas-ocp-combined", plan_id="lane-c-oas-ocp-combined",
            name="Wing aero + Caravan mission composite (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-oas-ocp-combined", comp_id="wing",
            comp_type="oas/AeroPoint",
            config={"surfaces": [dict(WING)]},
        )
        await plan_add_component(
            "lane-c-oas-ocp-combined", comp_id="mission",
            comp_type="ocp/BasicMission",
            config=_mission_config(MISSION, solver_settings=dict(_OCP_NEWTON)),
        )
        await plan_set_composition_policy(
            "lane-c-oas-ocp-combined", policy="explicit"
        )
        await plan_set_operating_point(
            "lane-c-oas-ocp-combined", fields=dict(FLIGHT)
        )
        plan_yaml = await _assemble_and_validate("lane-c-oas-ocp-combined")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        wing_c = summary["components"]["wing"]
        mission_c = summary["components"]["mission"]
        lane_c_flat = {
            "wing_CL": wing_c["CL"],
            "wing_CD": wing_c["CD"],
            "fuel_burn_kg": mission_c["fuel_burn_kg"],
            "OEW_kg": mission_c["OEW_kg"],
            "MTOW_kg": mission_c["MTOW_kg"],
        }

        _print_comparison(
            "OAS+OCP Combined (Lane C, uncoupled)", lane_a, lane_c_flat,
            keys=["wing_CL", "wing_CD", "fuel_burn_kg", "OEW_kg", "MTOW_kg"],
            case="oas_ocp_combined", lane_label="C",
        )

        assert lane_c_flat["wing_CL"] == pytest.approx(
            lane_a["wing_CL"], rel=1e-6,
        )
        assert lane_c_flat["wing_CD"] == pytest.approx(
            lane_a["wing_CD"], rel=1e-6,
        )
        assert lane_c_flat["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPOASDirectLaneC:

    @pytest.mark.slow
    async def test_direct_coupled_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_oas_direct"))
        from ocp_oas_direct.lane_a.direct_coupled_mission import (
            run as lane_a_run,
        )
        from ocp_oas_direct.shared import MISSION, VLM_CONFIG

        lane_a = lane_a_run()

        slots = {
            "drag": {"provider": "oas/vlm-direct", "config": dict(VLM_CONFIG)},
        }
        await plan_init(
            "lane-c-ocp-oas-direct", plan_id="lane-c-ocp-oas-direct",
            name="Caravan mission, direct-coupled VLM drag "
                 "(Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-ocp-oas-direct", comp_id="mission",
            comp_type="ocp/BasicMission",
            config=_mission_config(
                MISSION, slots=slots,
                solver_settings={
                    "solver_type": "newton", "maxiter": 30,
                    "atol": 1.0e-8, "rtol": 1.0e-8,
                },
            ),
        )
        plan_yaml = await _assemble_and_validate("lane-c-ocp-oas-direct")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "OCP+OAS Direct-Coupled Mission (Lane C)", lane_a, summary,
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
            case="ocp_oas_direct", lane_label="C",
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestPyCycleTurbojetLaneC:

    @pytest.mark.slow
    async def test_turbojet_design_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "pyc_turbojet"))
        from pyc_turbojet.lane_a.design_analysis import run as lane_a_run
        from pyc_turbojet.shared import DESIGN_POINT, ENGINE_PARAMS

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-pyc-turbojet", plan_id="lane-c-pyc-turbojet",
            name="Turbojet design point (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-pyc-turbojet", comp_id="turbojet",
            comp_type="pyc/TurbojetDesign", config=dict(ENGINE_PARAMS),
        )
        await plan_set_operating_point(
            "lane-c-pyc-turbojet", fields=dict(DESIGN_POINT)
        )
        plan_yaml = await _assemble_and_validate("lane-c-pyc-turbojet")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "pyCycle Turbojet Design Point (Lane C)", lane_a, summary,
            keys=["Fn", "TSFC", "OPR"],
            case="pyc_turbojet", lane_label="C",
        )

        assert summary["Fn"] == pytest.approx(lane_a["Fn"], rel=1e-6)
        assert summary["TSFC"] == pytest.approx(lane_a["TSFC"], rel=1e-6)
        assert summary["OPR"] == pytest.approx(lane_a["OPR"], rel=1e-6)


class TestOCPThreeToolLaneC:

    @pytest.mark.slow
    async def test_coupled_mission_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_three_tool"))
        from ocp_three_tool.lane_a.coupled_mission import run as lane_a_run
        from ocp_three_tool.shared import MISSION, PYC_SURR_CONFIG, VLM_CONFIG

        lane_a = lane_a_run()

        slots = {
            "drag": {"provider": "oas/vlm", "config": dict(VLM_CONFIG)},
            "propulsion": {
                "provider": "pyc/surrogate", "config": dict(PYC_SURR_CONFIG),
            },
        }
        await plan_init(
            "lane-c-ocp-three-tool", plan_id="lane-c-ocp-three-tool",
            name="B738 three-tool mission (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-ocp-three-tool", comp_id="mission",
            comp_type="ocp/BasicMission",
            config=_mission_config(
                MISSION, slots=slots,
                template="b738", architecture="twin_turbofan",
                # NLBGS: dual-surrogate coupling leaves Newton ill-conditioned.
                solver_settings={
                    "solver_type": "nlbgs", "maxiter": 200,
                    "atol": 1.0e-8, "rtol": 1.0e-8,
                },
            ),
        )
        plan_yaml = await _assemble_and_validate("lane-c-ocp-three-tool")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison(
            "OCP Three-Tool B738 Mission (Lane C)", lane_a, summary,
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
            case="ocp_three_tool", lane_label="C",
        )

        assert summary["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


# ── Aviary (subprocess factory into .venv-avy) ───────────────────────────

AVY_PYTHON = Path(__file__).resolve().parents[4] / ".venv-avy" / "bin" / "python"


@pytest.mark.skipif(
    not AVY_PYTHON.exists(),
    reason="needs the isolated Aviary venv (bash scripts/setup-avy-venv.sh)",
)
class TestAvySingleAisleLaneC:

    @pytest.mark.slow
    async def test_sizing_parity(self):
        sys.path.insert(0, str(EXAMPLES_DIR / "avy_single_aisle"))
        from avy_single_aisle.lane_a.sizing import run as lane_a_run
        from avy_single_aisle.shared import (
            DECK,
            MAX_ITER,
            METRICS,
            OPTIMIZER,
            PHASE_INFO_MODULE,
            TARGET_RANGE_NM,
            TOL_PARITY,
        )

        lane_a = lane_a_run()

        await plan_init(
            "lane-c-avy-sizing", plan_id="lane-c-avy-sizing",
            name="Aviary single-aisle sizing (Lane C tool surface)",
        )
        await plan_add_component(
            "lane-c-avy-sizing", comp_id="aviary",
            comp_type="avy/Sizing",
            config={
                "deck": DECK,
                "phase_info_module": PHASE_INFO_MODULE,
                "target_range_nm": TARGET_RANGE_NM,
                "optimizer": OPTIMIZER,
                "max_iter": MAX_ITER,
            },
        )
        plan_yaml = await _assemble_and_validate("lane-c-avy-sizing")

        env = await run_plan(plan_yaml, mode="analysis")
        summary = _summary(env)

        _print_comparison("Aviary Single-Aisle Sizing (Lane C)", lane_a, summary,
                          keys=METRICS, case="avy_single_aisle", lane_label="C")

        assert summary["converged"] == 1.0
        for k in METRICS:
            assert summary[k] == pytest.approx(lane_a[k], **TOL_PARITY)
