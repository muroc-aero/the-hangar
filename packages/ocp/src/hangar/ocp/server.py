"""OpenConcept MCP server -- FastMCP entry point."""

from __future__ import annotations

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

import os

from mcp.server.fastmcp import FastMCP

from hangar.sdk.auth.oidc import build_auth_settings, build_token_verifier
from hangar.sdk.provenance.middleware import capture_tool, _prov_session_id

# ---------------------------------------------------------------------------
# Import tool functions
# ---------------------------------------------------------------------------

from hangar.ocp.tools.aircraft import (
    define_aircraft,
    list_aircraft_templates,
    load_aircraft_template,
)
from hangar.ocp.tools.propulsion import set_propulsion_architecture
from hangar.ocp.tools.mission import configure_mission, run_mission_analysis
from hangar.ocp.tools.sweep import run_parameter_sweep
from hangar.ocp.tools.optimization import run_optimization
from hangar.ocp.tools.session import (
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
    reset,
    set_requirements,
    start_session,
    unpin_run,
)
from hangar.ocp.tools.resources import (
    artifact_by_run_id,
    reference_guide,
    workflow_guide,
)
from hangar.ocp.tools.prompts import (
    prompt_compare_architectures,
    prompt_electric_feasibility,
    prompt_hybrid_design,
    prompt_mission_analysis,
)

# Re-export state for tests
from hangar.ocp.state import sessions as _sessions, artifacts as _artifacts  # noqa: F401

# ---------------------------------------------------------------------------
# FastMCP construction
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "OpenConcept",
    auth=build_auth_settings(),
    token_verifier=build_token_verifier(),
    host=os.environ.get("OCP_HOST", "127.0.0.1"),
    instructions="""OpenConcept aircraft conceptual design and mission analysis server.

REQUIRED WORKFLOW — always follow this order:
  0. start_session              — begin a provenance session
  1. load_aircraft_template / define_aircraft — define the aircraft
     log_decision               — record aircraft choice (decision_type="architecture_choice")
  2. set_propulsion_architecture — select propulsion system
     log_decision               — record architecture choice
  3. configure_mission          — set mission profile (optional, uses defaults if skipped)
  4. run_mission_analysis       — run the analysis
     log_decision               — interpret results (decision_type="result_interpretation")
  5. run_parameter_sweep        — (optional) trade studies
  6. run_optimization           — (optional) design optimization
     log_decision               — before: dv_selection + constraint_choice; after: convergence_assessment
  7. export_session_graph       — save the provenance DAG at workflow end
  8. reset (optional)           — clear state between unrelated experiments

PROPULSION ARCHITECTURES:
  turboprop, twin_turboprop, series_hybrid, twin_series_hybrid, twin_turbofan

MISSION TYPES:
  full     — balanced-field takeoff + climb/cruise/descent
  basic    — climb/cruise/descent only (no takeoff)
  with_reserve — basic + reserve climb/cruise/descent + loiter

BUILT-IN AIRCRAFT TEMPLATES:
  caravan   — Cessna 208 Caravan (single turboprop, 675 hp, 3970 kg MTOW)
  b738      — Boeing 737-800 (twin turbofan, 2x 27klbf, 79002 kg MTOW)
  kingair   — King Air C90GT (twin turboprop, hybrid-ready, 4581 kg MTOW)
  tbm850    — TBM 850 (fast single turboprop, 850 hp, 3353 kg MTOW)

CRITICAL CONSTRAINTS:
  • num_nodes must be ODD (3, 5, 7, …, 11, 21, …) for Simpson's rule integration.
  • Hybrid architectures require battery_weight and motor/generator ratings.
  • Architecture changes invalidate the cached problem — set architecture before mission.
  • descent_vs is provided as a positive number and automatically negated.

RESPONSE ENVELOPE (all analysis tools):
  Every analysis tool returns a versioned envelope (schema_version="1.0"):
    • results:     fuel_burn_kg, OEW_kg, TOFL_ft, battery_SOC_final, phase_results, ...
    • validation:  physics and numerics checks — check "passed" before trusting results
    • telemetry:   timing and cache hit info
    • run_id:      use for get_run(), pin_run(), get_detailed_results()
    • summary:     narrative interpretation with derived metrics and delta vs previous run

PARAMETER SWEEP:
  Supported sweep parameters: mission_range, cruise_altitude, battery_weight,
  battery_specific_energy, hybridization, engine_rating, motor_rating.

OPTIMIZATION:
  Common objectives: fuel_burn, mixed_objective (fuel + MTOW/100), MTOW.
  Common DVs: ac|weights|MTOW, ac|geom|wing|S_ref, ac|propulsion|engine|rating,
  ac|propulsion|motor|rating, ac|propulsion|generator|rating, ac|weights|W_battery,
  cruise.hybridization, climb.hybridization, descent.hybridization.
  Common constraints: margins.MTOW_margin >= 0, descent.propmodel.batt1.SOC_final >= 0,
  climb.throttle <= 1.05.

PROVENANCE & DECISION LOGGING:
  Agents MUST call log_decision at these points:
  • After load_aircraft_template:    decision_type="architecture_choice"
  • After set_propulsion_architecture: decision_type="architecture_choice"
  • After any analysis tool:         decision_type="result_interpretation"
  • Before run_optimization:         decision_type="dv_selection" + "constraint_choice"
  • After run_optimization:          decision_type="convergence_assessment"
""",
)

# ---------------------------------------------------------------------------
# Register analysis tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(list_aircraft_templates))
mcp.tool()(capture_tool(load_aircraft_template))
mcp.tool()(capture_tool(define_aircraft))
mcp.tool()(capture_tool(set_propulsion_architecture))
mcp.tool()(capture_tool(configure_mission))
mcp.tool()(capture_tool(run_mission_analysis))
mcp.tool()(capture_tool(run_parameter_sweep))
mcp.tool()(capture_tool(run_optimization))
mcp.tool()(capture_tool(reset))

# ---------------------------------------------------------------------------
# Register artifact tools
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
# Register session tools
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(configure_session))
mcp.tool()(capture_tool(set_requirements))

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

mcp.resource("ocp://reference", description="Parameter reference for all OCP MCP tools")(reference_guide)
mcp.resource("ocp://workflows", description="Step-by-step workflows for common analysis tasks")(workflow_guide)
mcp.resource("ocp://artifacts/{run_id}", description="Retrieve a saved analysis artifact by run_id")(artifact_by_run_id)

# ---------------------------------------------------------------------------
# Register MCP prompts
# ---------------------------------------------------------------------------

mcp.prompt(
    name="mission_analysis",
    description="Guided turboprop mission analysis workflow",
)(prompt_mission_analysis)

mcp.prompt(
    name="hybrid_design",
    description="Series-hybrid electric aircraft trade study",
)(prompt_hybrid_design)

mcp.prompt(
    name="electric_feasibility",
    description="All-electric range/battery feasibility study",
)(prompt_electric_feasibility)

mcp.prompt(
    name="compare_architectures",
    description="Compare turboprop vs hybrid vs electric for same mission",
)(prompt_compare_architectures)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Console-script entry point for ocp-server."""
    import argparse
    from hangar.sdk.provenance.db import init_db as _prov_init_db, record_session as _prov_record_session

    parser = argparse.ArgumentParser(description="OpenConcept MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("OCP_TRANSPORT", "stdio"),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OCP_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OCP_PORT", "8001")),
    )
    args = parser.parse_args()

    # Provenance setup
    from hangar.sdk.provenance.middleware import set_tool_name
    set_tool_name("ocp")
    _prov_init_db()
    import uuid as _uuid
    _auto_sid = f"auto-{_uuid.uuid4().hex[:8]}"
    _prov_session_id.set(_auto_sid)
    _prov_record_session(_auto_sid, notes="Auto-created on OCP server startup")

    if args.transport == "stdio":
        # Legacy daemon thread viewer for local dev (localhost only, no auth)
        try:
            import sys as _sys
            from hangar.sdk.viz.viewer_server import start_viewer_server as _start_viewer
            _prov_port = _start_viewer()
            if _prov_port:
                _sep = "\u2500" * 54
                print(f"\n{_sep}", file=_sys.stderr)
                print("  OCP Provenance Viewer", file=_sys.stderr)
                print(_sep, file=_sys.stderr)
                print(f"  Viewer    http://localhost:{_prov_port}/viewer", file=_sys.stderr)
                print(f"  Sessions  http://localhost:{_prov_port}/sessions", file=_sys.stderr)
                print(f"  Plot API  http://localhost:{_prov_port}/plot?run_id=<id>&plot_type=<type>", file=_sys.stderr)
                print(_sep + "\n", file=_sys.stderr)
        except Exception:
            pass
        mcp.run()
    else:
        try:
            import uvicorn
        except ImportError as exc:
            raise ImportError(
                "uvicorn is required for HTTP transport."
            ) from exc

        import sys as _sys
        from hangar.sdk.viz.viewer_routes import build_viewer_app

        mcp_asgi = mcp.streamable_http_app()
        viewer_app, auth_mode = build_viewer_app()

        if viewer_app is not None:
            # Run OIDC discovery before starting the server (if OIDC mode).
            if auth_mode == "oidc":
                import asyncio as _asyncio
                from hangar.sdk.viz.viewer_auth import discover_oidc_endpoints
                _asyncio.run(discover_oidc_endpoints(viewer_app.state.oidc_config))

            from hangar.sdk.viz.viewer_routes import make_fallback_app
            app = make_fallback_app(viewer_app, mcp_asgi)
            _sep = "\u2500" * 54
            print(f"\n{_sep}", file=_sys.stderr)
            print("  OCP Provenance Viewer (HTTP transport)", file=_sys.stderr)
            print(_sep, file=_sys.stderr)
            print(f"  Viewer    http://{args.host}:{args.port}/viewer", file=_sys.stderr)
            if auth_mode == "oidc":
                print(f"            Protected by OIDC ({viewer_app.state.oidc_config.issuer_url})", file=_sys.stderr)
            else:
                print(f"            Protected by Basic Auth", file=_sys.stderr)
            print(_sep + "\n", file=_sys.stderr)
        else:
            app = mcp_asgi

        # Add unauthenticated /healthz endpoint
        from hangar.sdk.health import add_healthz
        app = add_healthz(app, server_name="ocp")

        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
