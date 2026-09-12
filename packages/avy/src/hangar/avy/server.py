"""Aviary MCP server -- FastMCP entry point.

Exposes NASA Aviary aircraft sizing + mission optimization tools to AI
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
from hangar.avy.tools import session as _prov_tools

# ---------------------------------------------------------------------------
# Import tool functions
# ---------------------------------------------------------------------------

from hangar.avy.tools.aircraft import (
    add_external_subsystem,
    configure_mission,
    define_aircraft,
    list_aircraft_templates,
    list_external_subsystems,
    load_aircraft_template,
)
from hangar.avy.tools.analysis import run_off_design, run_payload_range, run_sizing
from hangar.avy.tools.session import (
    configure_session,
    delete_artifact,
    get_artifact,
    get_artifact_summary,
    get_detailed_results,
    get_last_logs,
    get_run,
    list_artifacts,
    pin_run,
    record_conclusion,
    reset,
    set_requirements,
    unpin_run,
    visualize,
)

# Re-export for tests
from hangar.avy.state import sessions as _sessions, artifacts as _artifacts  # noqa: F401

# ---------------------------------------------------------------------------
# Register Aviary plot types with the SDK viewer infrastructure
# ---------------------------------------------------------------------------

from hangar.avy.viz.plotting import AVY_PLOT_TYPES, generate_avy_plot
from hangar.sdk.viz.viewer_server import register_plot_generator, register_plot_types

register_plot_types("sizing", [
    "mission_profile", "mass_breakdown", "performance_summary",
])
register_plot_types("off_design", [
    "mission_profile", "mass_breakdown", "performance_summary",
])
register_plot_types("payload_range", [
    "payload_range", "mission_profile", "mass_breakdown", "performance_summary",
])
register_plot_generator(AVY_PLOT_TYPES, generate_avy_plot)

# ---------------------------------------------------------------------------
# FastMCP construction
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Aviary",
    auth=build_auth_settings(),
    token_verifier=build_token_verifier(),
    host=os.environ.get("AVY_HOST", "127.0.0.1"),
    instructions="""NASA Aviary aircraft sizing and mission optimization server.

Aviary couples aircraft sizing (legacy FLOPS/GASP mass and aero methods) with
dymos trajectory optimization -- gross mass, fuel, and the flight path are
solved together. EVERY run is an optimizer run; there is no cheap
evaluate-only path (which is why the analysis tool is run_sizing, not
run_mission_analysis).

REQUIRED WORKFLOW -- always follow this order:
  0. start_session            -- begin a provenance session (once per workflow)
  1. load_aircraft_template   -- seed a complete aircraft deck from a shipped model
     log_decision             -- record aircraft choice (decision_type="architecture_choice")
  2. define_aircraft          -- (optional) override individual deck variables
     configure_mission        -- (optional) set range / phases; defaults used if skipped
     add_external_subsystem   -- (optional) attach 'oas_wing_mass' (OpenAeroStruct
                                 wingbox wing mass replacing the FLOPS estimate;
                                 adds a ~40 s nested sub-optimization per run)
  3. run_sizing               -- coupled sizing + mission optimization (~20 s - minutes)
     log_decision             -- interpret results (decision_type="result_interpretation")
     run_off_design           -- (optional) fly max_range/min_fuel missions with the
                                 sized design (re-runs the sizing internally, ~2x)
     run_payload_range        -- (optional) 4-point payload-range diagram (~3x)
  4. visualize                -- mission_profile / mass_breakdown / performance_summary
                                 / payload_range (payload-range runs only)
  5. export_session_graph     -- save the provenance DAG at workflow end
  6. reset (optional)         -- clear state between unrelated experiments

CRITICAL CONSTRAINTS:
  * OPTIMIZER NON-CONVERGENCE DOES NOT RAISE. Always check validation.passed
    and the 'optimizer.success' finding (and results.optimizer.success)
    before trusting any number -- a failed run returns the last iterate.
  * Default optimizer is SLSQP (always available). IPOPT/SNOPT require
    pyoptsparse and are rejected with instructions when it is absent.
  * Deck variable names use Aviary's 'aircraft:wing:span' hierarchy and are
    validated against the variable metadata -- typos error with close matches.
  * Only energy_state (FLOPS-style height-energy) missions run today; GASP
    2DOF decks are listed by list_aircraft_templates but rejected by analysis.
  * Aircraft names must match exactly between load_aircraft_template and
    subsequent calls.
  * Runs execute in managed per-run scratch directories; expect tens of
    seconds to minutes of wall-clock per run_sizing call.

RESPONSE ENVELOPE (all analysis tools):
  Every analysis tool returns a versioned envelope (schema_version="1.0"):
    * results:     performance (gross mass, fuel, range), design, optimizer,
                   timeseries (downsampled mission history)
    * validation:  physics and numerics checks -- check "passed" before trusting
    * telemetry:   timing info
    * run_id:      use for get_run(), pin_run(), visualize(), get_detailed_results()
    * error:       present when the tool failed; check error.code
  Error codes: USER_INPUT_ERROR, SOLVER_CONVERGENCE_ERROR, CACHE_EVICTED_ERROR, INTERNAL_ERROR

KEY OUTPUTS (results.performance):
  * gross_mass_lbm       -- sized takeoff gross mass; THE sizing headline
  * total_fuel_mass_lbm  -- mission + reserve fuel
  * fuel_burned_lbm      -- mission fuel burned
  * range_nmi            -- achieved mission range (matches target when converged)
  * final_time_min       -- mission duration

PROVENANCE & DECISION LOGGING:
  Agents MUST call log_decision at these points:
  * After load_aircraft_template: decision_type="architecture_choice"
  * After run_sizing:             decision_type="result_interpretation"
  Always pass prior_call_id when informed by a specific tool result.

Use the prompts (sizing_study, range_sensitivity, deck_override_study) for
guided workflows, and the resources (avy://reference, avy://workflows) for
quick lookup.""",
)

# ---------------------------------------------------------------------------
# Register aircraft definition tools (with @capture_tool for provenance)
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(list_aircraft_templates))
mcp.tool()(capture_tool(load_aircraft_template))
mcp.tool()(capture_tool(define_aircraft))
mcp.tool()(capture_tool(configure_mission))
mcp.tool()(capture_tool(list_external_subsystems))
mcp.tool()(capture_tool(add_external_subsystem))

# ---------------------------------------------------------------------------
# Register analysis tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(run_sizing))
mcp.tool()(capture_tool(run_off_design))
mcp.tool()(capture_tool(run_payload_range))
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

mcp.tool()(_prov_tools.start_session)
mcp.tool()(_prov_tools.log_decision)
mcp.tool()(_prov_tools.link_cross_tool_result)
mcp.tool()(_prov_tools.export_session_graph)

# ---------------------------------------------------------------------------
# Register MCP resources
# ---------------------------------------------------------------------------

from hangar.avy.tools.resources import (  # noqa: E402
    artifact_by_run_id,
    reference_guide,
    workflow_guide,
)

mcp.resource("avy://reference", description="Parameter reference for all avy MCP tools")(reference_guide)
mcp.resource("avy://workflows", description="Step-by-step workflows for common sizing tasks")(workflow_guide)
mcp.resource("avy://artifacts/{run_id}", description="Retrieve a saved analysis artifact by run_id")(artifact_by_run_id)

# ---------------------------------------------------------------------------
# Register MCP prompts
# ---------------------------------------------------------------------------

from hangar.avy.tools.prompts import (  # noqa: E402
    prompt_deck_override_study,
    prompt_range_sensitivity,
    prompt_sizing_study,
)

mcp.prompt(
    name="sizing_study",
    description="Guided aircraft sizing workflow",
)(prompt_sizing_study)

mcp.prompt(
    name="range_sensitivity",
    description="Two-point design-range sensitivity study",
)(prompt_range_sensitivity)

mcp.prompt(
    name="deck_override_study",
    description="Deck-variable override sizing comparison",
)(prompt_deck_override_study)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Console-script entry point for avy-server."""
    from hangar.sdk.server_main import run_server_main

    run_server_main(
        mcp,
        tool="avy",
        env_prefix="AVY",
        # 8000=oas, 8001=ocp, 8002=pyc, 8003=omd, 8004=evt, 8005=avy
        default_port=8005,
        description="Aviary MCP Server",
    )


if __name__ == "__main__":
    main()
