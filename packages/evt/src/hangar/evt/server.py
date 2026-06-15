"""evt MCP server -- FastMCP entry point.

Exposes evtolpy electric VTOL sizing and mission-energy analysis tools to AI
agents via the Model Context Protocol.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

import os

from mcp.server.fastmcp import FastMCP

from hangar.sdk.auth.oidc import build_auth_settings, build_token_verifier
from hangar.sdk.provenance.middleware import capture_tool

# ---------------------------------------------------------------------------
# Import tool functions
# ---------------------------------------------------------------------------

from hangar.evt.tools.vehicle import (
    define_vehicle,
    list_vehicle_templates,
    load_vehicle_template,
    set_environment,
    set_power,
    set_propulsion,
)
from hangar.evt.tools.mission import configure_mission
from hangar.evt.tools.analysis import run_mission_analysis, run_sizing
from hangar.evt.tools.sweep import run_parameter_sweep
from hangar.evt.tools.session import (
    configure_session,
    delete_artifact,
    export_session_graph,
    get_artifact,
    get_artifact_summary,
    get_detailed_results,
    get_last_logs,
    get_run,
    link_cross_tool_result,
    list_artifacts,
    log_decision,
    pin_run,
    record_conclusion,
    reset,
    set_requirements,
    start_session,
    unpin_run,
    visualize,
)

# Re-export for tests
from hangar.evt.state import sessions as _sessions, artifacts as _artifacts  # noqa: F401

# ---------------------------------------------------------------------------
# Register evt plot types with the SDK viewer infrastructure
# ---------------------------------------------------------------------------

from hangar.evt.viz.plotting import EVT_PLOT_TYPES, generate_evt_plot
from hangar.sdk.viz.viewer_server import register_plot_generator, register_plot_types

register_plot_types("mission", ["segment_energy", "segment_power", "mass_breakdown"])
register_plot_types("sizing", ["mtow_convergence", "mass_breakdown"])
register_plot_types("sweep", ["sweep"])
register_plot_generator(EVT_PLOT_TYPES, generate_evt_plot)

# ---------------------------------------------------------------------------
# FastMCP construction
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "evt",
    auth=build_auth_settings(),
    token_verifier=build_token_verifier(),
    host=os.environ.get("EVT_HOST", "127.0.0.1"),
    instructions="""evtolpy electric VTOL aircraft sizing and mission-energy analysis server.

REQUIRED WORKFLOW -- always follow this order:
  0. start_session            -- begin a provenance session (call once at workflow start)
  1. load_vehicle_template    -- seed a complete config from a baseline
     log_decision             -- record vehicle choice (decision_type="architecture_choice")
  2. define_vehicle / configure_mission / set_power / set_propulsion / set_environment
                              -- (optional) override individual parameters
  3. run_mission_analysis     -- energy, power, and mass tables at the configured MTOW
     run_sizing               -- converge MTOW (separate iteration)
     log_decision             -- interpret results (decision_type="result_interpretation")
  4. run_parameter_sweep      -- (optional) 1-D sensitivity studies
  5. export_session_graph     -- save the provenance DAG at workflow end
  6. reset (optional)         -- clear state between unrelated experiments

VEHICLE TEMPLATES:
  * test_all  -- lift+cruise eVTOL reference (6 lift + 6 tilt rotors + 1 pusher)
  Call list_vehicle_templates for the live list.

CRITICAL CONSTRAINTS:
  * A config must be complete before analysis. load_vehicle_template first; the
    setters only override individual keys.
  * evtolpy silently ignores unrecognized config keys, so the setters REJECT
    unknown parameter names (with a typo suggestion). Use the exact schema keys.
  * run_mission_analysis reads the aircraft at the as-configured MTOW (no
    sizing). run_sizing runs the MTOW iteration -- they are separate.
  * The MTOW iteration can diverge for self-inconsistent inputs; run_sizing then
    fails with a USER_INPUT_ERROR pointing at the likely culprits.
  * Units are baked into key/attribute names (_kg, _kw, _kw_hr, _m, _m_p_s, _s);
    never convert implicitly.

RESPONSE ENVELOPE (all analysis tools):
  Every analysis tool returns a versioned envelope (schema_version="1.0"):
    * results:    energy_kw_hr, avg_electric_power_kw, mass_breakdown_kg, totals,
                  geometry, aero, propulsion (mission); history + sized_mtow_kg (sizing)
    * validation: physics/numerics checks -- check "passed" before trusting results
    * telemetry:  timing and cache info
    * run_id:     use for get_run(), pin_run(), get_detailed_results(), visualize()
    * error:      present when the tool failed; check error.code

KEY OUTPUTS:
  * energy_kw_hr           -- per-segment energy across 18 mission segments (kW*hr)
  * avg_electric_power_kw  -- per-segment average electric power (kW)
  * mass_breakdown_kg      -- 15-component empty-mass breakdown (kg)
  * totals.total_mission_energy_kw_hr -- non-reserve mission energy
  * sized_mtow_kg          -- converged maximum takeoff mass (run_sizing)

VISUALIZATION:
  Call visualize(run_id, plot_type) after an analysis:
    * segment_energy / segment_power -- per-segment bar charts (mission runs)
    * mass_breakdown                 -- component mass bars (mission or sizing runs)
    * mtow_convergence               -- MTOW vs iteration (sizing runs)
    * sweep                          -- metric vs swept parameter (sweep runs)

Use the prompts (mission_analysis, sizing_study, battery_sweep) for guided
workflows, and the resources (evt://reference, evt://workflows) for lookup.""",
)

# ---------------------------------------------------------------------------
# Register vehicle / config tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(list_vehicle_templates))
mcp.tool()(capture_tool(load_vehicle_template))
mcp.tool()(capture_tool(define_vehicle))
mcp.tool()(capture_tool(set_propulsion))
mcp.tool()(capture_tool(set_power))
mcp.tool()(capture_tool(set_environment))
mcp.tool()(capture_tool(configure_mission))

# ---------------------------------------------------------------------------
# Register analysis tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(run_mission_analysis))
mcp.tool()(capture_tool(run_sizing))
mcp.tool()(capture_tool(run_parameter_sweep))
mcp.tool()(capture_tool(reset))

# ---------------------------------------------------------------------------
# Register artifact management tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(list_artifacts))
mcp.tool()(capture_tool(get_artifact))
mcp.tool()(capture_tool(get_artifact_summary))
mcp.tool()(capture_tool(delete_artifact))

# ---------------------------------------------------------------------------
# Register observability tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(get_run))
mcp.tool()(capture_tool(pin_run))
mcp.tool()(capture_tool(unpin_run))
mcp.tool()(capture_tool(get_detailed_results))
mcp.tool()(capture_tool(get_last_logs))

# ---------------------------------------------------------------------------
# Register visualization tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(visualize))

# ---------------------------------------------------------------------------
# Register session configuration tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(configure_session))
mcp.tool()(capture_tool(set_requirements))
mcp.tool()(capture_tool(record_conclusion))

# ---------------------------------------------------------------------------
# Register provenance tools
# ---------------------------------------------------------------------------

mcp.tool()(start_session)
mcp.tool()(log_decision)
mcp.tool()(link_cross_tool_result)
mcp.tool()(export_session_graph)

# ---------------------------------------------------------------------------
# Register MCP resources
# ---------------------------------------------------------------------------

from hangar.evt.tools.resources import (  # noqa: E402
    artifact_by_run_id,
    reference_guide,
    workflow_guide,
)

mcp.resource("evt://reference", description="Parameter reference for all evt MCP tools")(reference_guide)
mcp.resource("evt://workflows", description="Step-by-step workflows for common analysis tasks")(workflow_guide)
mcp.resource("evt://artifacts/{run_id}", description="Retrieve a saved analysis artifact by run_id")(artifact_by_run_id)

# ---------------------------------------------------------------------------
# Register MCP prompts
# ---------------------------------------------------------------------------

from hangar.evt.tools.prompts import (  # noqa: E402
    prompt_battery_sweep,
    prompt_mission_analysis,
    prompt_sizing_study,
)

mcp.prompt(
    name="mission_analysis",
    description="Guided eVTOL mission energy/power/mass analysis",
)(prompt_mission_analysis)

mcp.prompt(
    name="sizing_study",
    description="Guided MTOW convergence (sizing) workflow",
)(prompt_sizing_study)

mcp.prompt(
    name="battery_sweep",
    description="Battery specific-energy sensitivity sweep on sized MTOW",
)(prompt_battery_sweep)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Console-script entry point for evt-server."""
    from hangar.sdk.server_main import run_server_main

    run_server_main(
        mcp,
        tool="evt",
        env_prefix="EVT",
        # 8000=oas, 8001=ocp, 8002=pyc, 8003=omd, 8004=evt
        # (matches the docker-compose host ports)
        default_port=8004,
        description="evt MCP Server",
    )


if __name__ == "__main__":
    main()
