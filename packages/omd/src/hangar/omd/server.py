"""omd MCP server -- FastMCP entry point.

Exposes the full omd-cli surface (plan authoring, validation, execution,
results, plots, provenance, conclusions) to AI agents via the Model Context
Protocol, wired through the shared SDK envelope/provenance/auth stack like
the oas/ocp/pyc servers. Each tool calls the same implementation functions
as omd-cli, so the two front ends never drift.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

import os
import sys
import threading

from mcp.server.fastmcp import FastMCP

from hangar.sdk.auth.oidc import build_auth_settings, build_token_verifier
from hangar.sdk.provenance.middleware import capture_tool
from hangar.sdk.provenance.tools import build_provenance_tools
from hangar.sdk.state import sessions as _sessions

# ---------------------------------------------------------------------------
# Import tool functions
# ---------------------------------------------------------------------------

from hangar.omd.instructions import INSTRUCTIONS
from hangar.omd.tools.authoring import (
    plan_add_component,
    plan_add_decision,
    plan_add_dv,
    plan_add_requirement,
    plan_add_shared_var,
    plan_init,
    plan_set_analysis_strategy,
    plan_set_composition_policy,
    plan_set_objective,
    plan_set_operating_point,
    plan_set_solver,
    read_plan,
    review_plan,
    write_plan,
)
from hangar.omd.tools.execution import (
    assemble_plan,
    run_plan,
    run_polar,
    validate_plan,
)
from hangar.omd.tools.plots import (
    generate_plots,
    get_view_urls,
    list_plot_types,
)
from hangar.omd.tools.results_tools import (
    export_plan,
    get_provenance,
    get_results,
    get_run_summary,
    record_conclusion,
)
from hangar.omd.tools.study import (
    get_study_results,
    get_study_status,
    plot_study,
    review_study,
    run_study,
)

# ---------------------------------------------------------------------------
# Register the omd views with the SDK viewer infrastructure
# ---------------------------------------------------------------------------
# Same routes as `omd-cli viewer`: /omd-provenance, /omd-plan-detail,
# /omd-problem-dag, /omd-plots, /omd-plot-img, /omd-n2, /omd-plan-diff.
# Served by the stdio daemon viewer and by the HTTP transport's viewer app.

from hangar.omd.cli.server_routes import register_omd_viewer_routes

register_omd_viewer_routes()

# ---------------------------------------------------------------------------
# FastMCP construction
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "omd",
    auth=build_auth_settings(),
    token_verifier=build_token_verifier(),
    host=os.environ.get("OMD_HOST", "127.0.0.1"),
    instructions=INSTRUCTIONS,
)

# ---------------------------------------------------------------------------
# Register plan authoring tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(write_plan))
mcp.tool()(capture_tool(read_plan))
mcp.tool()(capture_tool(plan_init))
mcp.tool()(capture_tool(plan_add_component))
mcp.tool()(capture_tool(plan_add_requirement))
mcp.tool()(capture_tool(plan_add_dv))
mcp.tool()(capture_tool(plan_set_objective))
mcp.tool()(capture_tool(plan_set_operating_point))
mcp.tool()(capture_tool(plan_set_solver))
mcp.tool()(capture_tool(plan_set_analysis_strategy))
mcp.tool()(capture_tool(plan_add_shared_var))
mcp.tool()(capture_tool(plan_set_composition_policy))
mcp.tool()(capture_tool(plan_add_decision))
mcp.tool()(capture_tool(review_plan))

# ---------------------------------------------------------------------------
# Register validation + execution tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(validate_plan))
mcp.tool()(capture_tool(assemble_plan))
mcp.tool()(capture_tool(run_plan))
mcp.tool()(capture_tool(run_polar))

# ---------------------------------------------------------------------------
# Register study tools (multi-case studies; see hangar.sdk.study)
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(review_study))
mcp.tool()(capture_tool(run_study))
mcp.tool()(capture_tool(get_study_status))
mcp.tool()(capture_tool(get_study_results))
mcp.tool()(capture_tool(plot_study))

# ---------------------------------------------------------------------------
# Register results + provenance tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(get_results))
mcp.tool()(capture_tool(get_run_summary))
mcp.tool()(capture_tool(record_conclusion))
mcp.tool()(capture_tool(get_provenance))
mcp.tool()(capture_tool(export_plan))

# ---------------------------------------------------------------------------
# Register visualization tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(generate_plots))
mcp.tool()(capture_tool(list_plot_types))
mcp.tool()(capture_tool(get_view_urls))

# ---------------------------------------------------------------------------
# Register shared provenance tools
# ---------------------------------------------------------------------------

_prov_tools = build_provenance_tools(_sessions)
start_session = _prov_tools.start_session
log_decision = _prov_tools.log_decision
link_cross_tool_result = _prov_tools.link_cross_tool_result
export_session_graph = _prov_tools.export_session_graph

mcp.tool()(start_session)
mcp.tool()(log_decision)
mcp.tool()(link_cross_tool_result)
mcp.tool()(export_session_graph)

# ---------------------------------------------------------------------------
# Register MCP resources
# ---------------------------------------------------------------------------

from hangar.omd.tools.resources import (  # noqa: E402
    plan_by_id,
    plan_schema_resource,
    reference_guide,
)

mcp.resource("omd://reference", description="Parameter reference for all omd MCP tools")(reference_guide)
mcp.resource("omd://plan-schema", description="JSON Schema for omd plan YAML")(plan_schema_resource)
mcp.resource("omd://plans/{plan_id}", description="Latest assembled YAML for a plan")(plan_by_id)

# ---------------------------------------------------------------------------
# Register MCP prompts
# ---------------------------------------------------------------------------

from hangar.omd.tools.prompts import (  # noqa: E402
    prompt_author_plan_study,
    prompt_run_existing_plan,
)

mcp.prompt(
    name="author_plan_study",
    description="Author a plan over MCP, then validate, run, and conclude",
)(prompt_author_plan_study)

mcp.prompt(
    name="run_existing_plan",
    description="Validate, run, and review an existing plan file",
)(prompt_run_existing_plan)


# ---------------------------------------------------------------------------
# Range-safety dashboard
# ---------------------------------------------------------------------------


def _maybe_start_rs_dashboard() -> None:
    """Make the range-safety dashboard reachable for the urls blocks.

    Deployments run the dashboard as its own service and set
    ``RS_DASHBOARD_URL``. For local development this starts the dashboard
    in a daemon thread (when hangar-range-safety is installed) so tool
    results can link to it; disable with ``RS_DASHBOARD_AUTOSTART=off``.
    """
    if os.environ.get("RS_DASHBOARD_URL"):
        return
    if os.environ.get("RS_DASHBOARD_AUTOSTART", "on").lower() in ("off", "0", "false"):
        return
    try:
        import uvicorn

        from hangar.range_safety.dashboard.app import app as rs_app
    except ImportError:
        return

    port = int(os.environ.get("RS_DASHBOARD_PORT", "7655"))
    config = uvicorn.Config(rs_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="rs-dashboard").start()
    os.environ["RS_DASHBOARD_URL"] = f"http://localhost:{port}"
    print(
        f"  Range-safety dashboard  http://localhost:{port}/",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console-script entry point for omd-server."""
    from hangar.sdk.server_main import run_server_main

    from hangar.omd.db import init_analysis_db

    init_analysis_db()
    _maybe_start_rs_dashboard()
    run_server_main(
        mcp,
        tool="omd",
        env_prefix="OMD",
        # 8000=oas, 8001=ocp, 8002=pyc, 8003=omd (matches docker-compose)
        default_port=8003,
        description="omd MCP Server (OpenMDAO plan runner)",
    )


if __name__ == "__main__":
    main()
