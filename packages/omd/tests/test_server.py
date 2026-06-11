"""Tests for the omd MCP server: tool surface, envelopes, authoring round-trip.

Uses the paraboloid factory throughout so the suite stays fast (no OAS).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hangar.sdk.errors import UserInputError


@pytest.fixture(autouse=True)
def isolate_data_root(tmp_path, monkeypatch):
    """Point the omd data root (workspace, plots, n2) at the test tmp dir.

    The shared conftest already isolates the DB / plan store / recordings.
    """
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "omd_data"))
    yield


def _paraboloid_plan(optimize: bool = False, requirements: list | None = None) -> dict:
    plan = {
        "metadata": {"id": "para-srv", "name": "Paraboloid server test", "version": 1},
        "components": [
            {"id": "paraboloid", "type": "paraboloid/Paraboloid", "config": {}},
        ],
        "operating_points": {"x": 0.0, "y": 0.0},
    }
    if optimize:
        plan["design_variables"] = [
            {"name": "x", "lower": -50.0, "upper": 50.0},
            {"name": "y", "lower": -50.0, "upper": 50.0},
        ]
        plan["objective"] = {"name": "paraboloid.f_xy"}
        plan["optimizer"] = {"type": "SLSQP", "options": {"maxiter": 50}}
    if requirements:
        plan["requirements"] = requirements
    return plan


def _write_plan(tmp_path: Path, plan: dict, name: str = "plan.yaml") -> Path:
    plan_path = tmp_path / name
    plan_path.write_text(yaml.dump(plan))
    return plan_path


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


def test_server_tool_surface():
    """Every omd-cli capability is registered as an MCP tool."""
    from hangar.omd import server

    registered = {t.name for t in server.mcp._tool_manager.list_tools()}
    expected = {
        # authoring
        "write_plan", "read_plan", "plan_init", "plan_add_component",
        "plan_add_requirement", "plan_add_dv", "plan_set_objective",
        "plan_set_operating_point", "plan_set_solver",
        "plan_set_analysis_strategy", "plan_add_shared_var",
        "plan_set_composition_policy", "plan_add_decision", "review_plan",
        # validation + execution
        "validate_plan", "assemble_plan", "run_plan", "run_polar",
        # results + provenance
        "get_results", "get_run_summary", "record_conclusion",
        "get_provenance", "export_plan",
        # visualization
        "generate_plots", "list_plot_types", "get_view_urls",
        # shared provenance tools
        "start_session", "log_decision", "link_cross_tool_result",
        "export_session_graph",
    }
    assert expected <= registered


def test_server_registers_omd_viewer_routes():
    """Importing the server makes the omd views servable on both transports."""
    import hangar.omd.server  # noqa: F401
    from hangar.sdk.viz.viewer_server import _CUSTOM_ROUTES

    for path in (
        "/omd-provenance", "/omd-plan-diff", "/omd-plots", "/omd-plot-img",
        "/omd-n2", "/omd-problem-dag", "/omd-plan-detail",
    ):
        assert path in _CUSTOM_ROUTES


def test_http_viewer_app_serves_custom_routes(monkeypatch):
    """build_viewer_app must include register_viewer_route routes (HTTP transport)."""
    import hangar.omd.server  # noqa: F401
    from hangar.sdk.viz.viewer_routes import build_viewer_app

    monkeypatch.setenv("HANGAR_VIEWER_USER", "u")
    monkeypatch.setenv("HANGAR_VIEWER_PASSWORD", "p")
    app, mode = build_viewer_app()
    assert mode == "basic"
    paths = {r.path for r in app.routes}
    assert "/omd-problem-dag" in paths
    assert "/omd-plots" in paths


# ---------------------------------------------------------------------------
# Execution envelope
# ---------------------------------------------------------------------------


async def test_run_plan_returns_envelope(tmp_path):
    from hangar.omd.tools.execution import run_plan

    plan_path = _write_plan(tmp_path, _paraboloid_plan())
    env = await run_plan(str(plan_path))

    assert env["schema_version"] == "1.0"
    assert env["tool_name"] == "run_plan"
    assert env["run_id"]
    assert "error" not in env
    assert env["results"]["status"] in ("completed", "converged")
    assert env["validation"]["passed"] is True
    assert isinstance(env["results"]["urls"], dict)
    assert env["telemetry"]["elapsed_s"] >= 0


async def test_run_plan_semantic_preflight_blocks_run(tmp_path):
    """DVs without an objective must abort before materialization."""
    from hangar.omd.tools.execution import run_plan

    plan = _paraboloid_plan()
    plan["design_variables"] = [{"name": "x", "lower": -50.0, "upper": 50.0}]
    plan_path = _write_plan(tmp_path, plan)

    env = await run_plan(str(plan_path))
    assert env["error"]["code"] == "USER_INPUT_ERROR"
    assert any("objective" in str(e) for e in env["error"]["details"]["errors"])


async def test_run_plan_rejects_bad_mode(tmp_path):
    from hangar.omd.tools.execution import run_plan

    plan_path = _write_plan(tmp_path, _paraboloid_plan())
    with pytest.raises(UserInputError):
        await run_plan(str(plan_path), mode="sweep")


async def test_run_polar_rejects_bad_alpha_range(tmp_path):
    from hangar.omd.tools.execution import run_polar

    plan_path = _write_plan(tmp_path, _paraboloid_plan())
    with pytest.raises(UserInputError):
        await run_polar(str(plan_path), alpha_start=5.0, alpha_end=-5.0)


async def test_run_plan_optimize_results_roundtrip(tmp_path):
    """Optimize, then pull results back through the MCP results tool."""
    from hangar.omd.tools.execution import run_plan
    from hangar.omd.tools.results_tools import get_results

    plan_path = _write_plan(tmp_path, _paraboloid_plan(optimize=True))
    env = await run_plan(str(plan_path), mode="optimize")
    assert "error" not in env
    run_id = env["run_id"]

    result = await get_results(run_id, summary=True)
    assert result.get("final") or result.get("run_id") == run_id


# ---------------------------------------------------------------------------
# Authoring round-trip (MCP-only agent path: no direct filesystem access)
# ---------------------------------------------------------------------------


async def test_authoring_roundtrip_assemble_validate_run():
    from hangar.omd.tools.authoring import (
        plan_add_component,
        plan_add_dv,
        plan_init,
        plan_set_objective,
        plan_set_operating_point,
    )
    from hangar.omd.tools.execution import assemble_plan, run_plan, validate_plan

    init = await plan_init("study1", plan_id="study1", name="Workspace study")
    plan_dir = init["plan_dir"]

    await plan_add_component(
        "study1", comp_id="paraboloid", comp_type="paraboloid/Paraboloid",
        config={}, rationale="trivial test component",
    )
    await plan_set_operating_point("study1", fields={"x": 0.0, "y": 0.0})
    await plan_add_dv("study1", name="x", lower=-50.0, upper=50.0)
    await plan_add_dv("study1", name="y", lower=-50.0, upper=50.0)
    await plan_set_objective("study1", name="f_xy")

    assembled = await assemble_plan("study1")
    assert not assembled["errors"]
    plan_yaml = assembled["output_path"]
    assert Path(plan_yaml).is_relative_to(Path(plan_dir))

    check = await validate_plan(plan_yaml)
    assert check["valid"] is True
    assert check["plan_id"] == "study1"

    env = await run_plan(plan_yaml, mode="optimize")
    assert "error" not in env
    # Paraboloid minimum f(10/3, -14/3) = -27.33
    f_xy = env["results"]["summary"].get("paraboloid.f_xy")
    if f_xy is not None:
        assert f_xy == pytest.approx(-27.333, abs=0.1)


async def test_authoring_rejects_bad_dv_bounds():
    from hangar.omd.tools.authoring import plan_add_component, plan_add_dv, plan_init

    await plan_init("study2", plan_id="study2", name="Bad DV study")
    await plan_add_component(
        "study2", comp_id="paraboloid", comp_type="paraboloid/Paraboloid", config={}
    )
    with pytest.raises(UserInputError):
        await plan_add_dv("study2", name="x", lower=1.0, upper=-1.0)


async def test_write_and_read_plan_in_workspace(tmp_path):
    from hangar.omd.tools.authoring import read_plan, write_plan
    from hangar.omd.tools._helpers import workspace_dir

    result = await write_plan("direct/plan.yaml", yaml.dump(_paraboloid_plan()))
    assert result["written"] is True
    written = Path(result["path"])
    assert written.is_relative_to(workspace_dir())

    back = await read_plan("direct/plan.yaml")
    assert back["is_dir"] is False
    assert yaml.safe_load(back["content"])["metadata"]["id"] == "para-srv"


async def test_write_plan_rejects_workspace_escape():
    from hangar.omd.tools.authoring import write_plan

    with pytest.raises(UserInputError):
        await write_plan("../escape.yaml", "a: 1")


async def test_write_plan_rejects_invalid_yaml():
    from hangar.omd.tools.authoring import write_plan

    with pytest.raises(UserInputError):
        await write_plan("bad.yaml", "a: [unclosed")


# ---------------------------------------------------------------------------
# Conclusion + summary + plots + URLs
# ---------------------------------------------------------------------------


async def test_record_conclusion_derives_verdicts(tmp_path):
    from hangar.omd.tools.execution import run_plan
    from hangar.omd.tools.results_tools import record_conclusion

    reqs = [{
        "id": "R1",
        "text": "Objective must be near the analytic minimum",
        "acceptance_criteria": [
            {"metric": "paraboloid.f_xy", "comparator": "<=", "threshold": -27.0},
        ],
    }]
    plan_path = _write_plan(tmp_path, _paraboloid_plan(optimize=True, requirements=reqs))
    env = await run_plan(str(plan_path), mode="optimize")
    assert "error" not in env

    result = await record_conclusion(
        env["run_id"], narrative="optimum found", plan_path=str(plan_path)
    )
    assert result["conclusion_id"]
    assert result["verdict"] in ("meets", "fails", "partial", "open")
    assert "urls" in result


async def test_get_run_summary_writes_html(tmp_path):
    from hangar.omd.tools.execution import run_plan
    from hangar.omd.tools.results_tools import get_run_summary

    plan_path = _write_plan(tmp_path, _paraboloid_plan())
    env = await run_plan(str(plan_path))

    result = await get_run_summary(env["run_id"], regenerate_plots=False)
    summary_path = Path(result["summary_path"])
    assert summary_path.exists()
    assert "<html" in summary_path.read_text().lower()


async def test_list_plot_types_and_generate_plots(tmp_path):
    from hangar.omd.tools.execution import run_plan
    from hangar.omd.tools.plots import generate_plots, list_plot_types

    plan_path = _write_plan(tmp_path, _paraboloid_plan(optimize=True))
    env = await run_plan(str(plan_path), mode="optimize")
    run_id = env["run_id"]

    types = await list_plot_types(run_id)
    assert "convergence" in types["plot_types"]

    result = await generate_plots(run_id, plot_type="convergence")
    assert "convergence" in result["saved"]
    assert Path(result["saved"]["convergence"]).exists()


async def test_get_view_urls_with_resource_server(monkeypatch):
    from hangar.omd.tools.plots import get_view_urls

    monkeypatch.setenv("RESOURCE_SERVER_URL", "https://mcp.example.dev")
    monkeypatch.setenv("RS_DASHBOARD_URL", "https://rs.example.dev")

    result = await get_view_urls(run_id="run-1", plan_id="plan-1")
    urls = result["urls"]
    assert urls["problem_dag"] == "https://mcp.example.dev/omd-problem-dag?run_id=run-1"
    assert urls["plan_detail"] == "https://mcp.example.dev/omd-plan-detail?plan_id=plan-1"
    assert urls["n2"] == "https://mcp.example.dev/omd-n2?run_id=run-1"
    assert urls["range_safety_dashboard"] == (
        "https://rs.example.dev/?plan_id=plan-1&run_id=run-1"
    )


async def test_get_provenance_timeline(tmp_path):
    from hangar.omd.tools.execution import run_plan
    from hangar.omd.tools.results_tools import get_provenance

    plan_path = _write_plan(tmp_path, _paraboloid_plan())
    env = await run_plan(str(plan_path))
    assert "error" not in env

    result = await get_provenance("para-srv", format="text")
    assert "timeline" in result

    result = await get_provenance("para-srv", format="json")
    assert "dag" in result


async def test_export_plan_returns_script(tmp_path):
    from hangar.omd.tools.results_tools import export_plan

    plan_path = _write_plan(tmp_path, _paraboloid_plan())
    result = await export_plan(str(plan_path))
    assert result["exported"] is True
    assert "openmdao" in result["content"] or "om." in result["content"]


# ---------------------------------------------------------------------------
# Error envelope wiring (typed errors -> capture_tool envelope)
# ---------------------------------------------------------------------------


async def test_capture_tool_wraps_user_input_error():
    from hangar.sdk.provenance.middleware import capture_tool

    from hangar.omd.tools.results_tools import get_results

    wrapped = capture_tool(get_results)
    env = await wrapped("no-such-run")
    assert env["error"]["code"] == "USER_INPUT_ERROR"
