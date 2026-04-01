"""pyCycle MCP server -- FastMCP entry point.

Exposes gas turbine cycle analysis tools to AI agents via the
Model Context Protocol.
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
from hangar.sdk.provenance.middleware import capture_tool, _prov_session_id
from hangar.pyc.tools import session as _prov_tools

# ---------------------------------------------------------------------------
# Import tool functions
# ---------------------------------------------------------------------------

from hangar.pyc.tools.engine import create_engine
from hangar.pyc.tools.analysis import run_design_point, run_off_design
from hangar.pyc.tools.session import (
    configure_session,
    delete_artifact,
    get_artifact,
    get_artifact_summary,
    get_last_logs,
    get_run,
    list_artifacts,
    pin_run,
    reset,
    set_requirements,
    unpin_run,
    visualize,
)

# Re-export for tests
from hangar.sdk.state import sessions as _sessions, artifacts as _artifacts  # noqa: F401

# ---------------------------------------------------------------------------
# Register pyCycle plot types with the SDK viewer infrastructure
# ---------------------------------------------------------------------------

from hangar.pyc.viz.plotting import PYC_PLOT_TYPES, generate_pyc_plot
from hangar.sdk.viz.viewer_server import register_plot_generator, register_plot_types

register_plot_types("design", [
    "station_properties", "ts_diagram", "performance_summary", "component_bars",
])
register_plot_types("off_design", [
    "station_properties", "ts_diagram", "performance_summary", "component_bars",
    "design_vs_offdesign",
])
register_plot_generator(PYC_PLOT_TYPES, generate_pyc_plot)

# ---------------------------------------------------------------------------
# FastMCP construction
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "pyCycle",
    auth=build_auth_settings(),
    token_verifier=build_token_verifier(),
    host=os.environ.get("PYC_HOST", "127.0.0.1"),
    instructions="""pyCycle gas turbine thermodynamic cycle analysis and optimisation server.

REQUIRED WORKFLOW -- always follow this order:
  0. start_session     -- begin a provenance session (call once at workflow start)
  1. create_engine     -- define engine from archetype + parameters
     log_decision      -- record archetype/parameter choices (decision_type="archetype_selection")
  2. run_design_point  -- size the engine at design conditions (MUST precede off-design)
     log_decision      -- interpret results (decision_type="result_interpretation", prior_call_id=...)
  3. run_off_design    -- evaluate at off-design conditions (requires design point first)
     log_decision      -- interpret off-design results
  4. export_session_graph -- save the provenance DAG at workflow end
  5. reset (optional)  -- clear state between unrelated experiments

AVAILABLE ARCHETYPES:
  * turbojet          -- single-spool turbojet (compressor, burner, turbine, nozzle)
  (more archetypes coming: hbtf, mixedflow_turbofan, turboshaft, electric_propulsor)

CRITICAL CONSTRAINTS:
  * run_design_point MUST be called before run_off_design -- the design point sizes
    the engine geometry which is fixed for off-design analysis.
  * Engine names must match exactly between create_engine and analysis calls.
  * T4_target should not exceed ~3600 degR (material limits).
  * Newton solver requires good initial guesses -- defaults are provided for each
    archetype but may need adjustment for extreme operating conditions.

RESPONSE ENVELOPE (all analysis tools):
  Every analysis tool returns a versioned envelope (schema_version="1.0"):
    * results:     performance (TSFC, Fn, OPR), flow_stations, components
    * validation:  physics and numerics checks -- check "passed" before trusting
    * telemetry:   timing and cache info
    * run_id:      use for get_run(), pin_run(), get_artifact()
    * error:       present when the tool failed

KEY OUTPUTS:
  * TSFC  -- thrust-specific fuel consumption (lbm/hr/lbf); lower = more efficient
  * Fn    -- net thrust (lbf)
  * OPR   -- overall pressure ratio (Pt3/Pt2)
  * Flow stations report total/static P, T, W, MN at each engine station
  * Component data includes PR, efficiency, power, torque for each element

DESIGN vs OFF-DESIGN:
  * Design point: you specify desired performance (thrust, T4) and component
    parameters (PR, efficiency). The solver sizes the engine (areas, map scalars).
  * Off-design: the sized geometry is fixed. You specify flight conditions and
    thrust requirement. The solver adjusts FAR, shaft speed, and mass flow.

PARAMETER TIPS:
  * For a simple turbojet: comp_PR=13.5, comp_eff=0.83, turb_eff=0.86
  * SLS design: alt=0, MN=0.000001 (near-zero, not exactly 0)
  * Cruise design: alt=35000, MN=0.8
  * TABULAR thermo is ~10x faster than CEA with similar accuracy for Jet-A

PROVENANCE & DECISION LOGGING:
  Agents MUST call log_decision at these points:
  * After create_engine:      decision_type="archetype_selection"
  * After run_design_point:   decision_type="result_interpretation"
  * After run_off_design:     decision_type="result_interpretation"
  Always pass prior_call_id when informed by a specific tool result.

VISUALIZATION:
  Call visualize(run_id, plot_type) after any analysis to generate plots:
    * station_properties   -- Pt, Tt, Mach, mass flow through the engine (2x2 grid)
    * ts_diagram           -- T-s diagram of the Brayton cycle
    * performance_summary  -- table card with all key engine metrics
    * component_bars       -- bar chart comparing component PR, efficiency, power
    * design_vs_offdesign  -- paired bars comparing design vs off-design (off-design only)""",
)

# ---------------------------------------------------------------------------
# Register analysis tools (with @capture_tool for provenance)
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(create_engine))
mcp.tool()(capture_tool(run_design_point))
mcp.tool()(capture_tool(run_off_design))
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

# ---------------------------------------------------------------------------
# Register provenance tools
# ---------------------------------------------------------------------------

mcp.tool()(_prov_tools.start_session)
mcp.tool()(_prov_tools.log_decision)
mcp.tool()(_prov_tools.link_cross_tool_result)
mcp.tool()(_prov_tools.export_session_graph)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Console-script entry point for pyc-server.

    Supports stdio (default) and HTTP transports.
    """
    import argparse
    from hangar.sdk.provenance.db import init_db as _prov_init_db, record_session as _prov_record_session

    parser = argparse.ArgumentParser(description="pyCycle MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("PYC_TRANSPORT", "stdio"),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("PYC_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PYC_PORT", "8001")),
    )
    args = parser.parse_args()

    # Provenance setup
    from hangar.sdk.provenance.middleware import set_tool_name
    set_tool_name("pyc")
    _prov_init_db()
    import uuid as _uuid
    _auto_sid = f"auto-{_uuid.uuid4().hex[:8]}"
    _prov_session_id.set(_auto_sid)
    _prov_record_session(_auto_sid, notes="Auto-created on pyCycle server startup")

    if args.transport == "stdio":
        # Legacy daemon thread viewer for local dev (localhost only, no auth)
        try:
            import sys as _sys
            from hangar.sdk.viz.viewer_server import start_viewer_server as _start_viewer
            _prov_port = _start_viewer()
            if _prov_port:
                _sep = "\u2500" * 54
                print(f"\n{_sep}", file=_sys.stderr)
                print("  PYC Provenance Viewer", file=_sys.stderr)
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
                "uvicorn required for HTTP transport. Install hangar-sdk[http]."
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
            print("  PYC Provenance Viewer (HTTP transport)", file=_sys.stderr)
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
        app = add_healthz(app, server_name="pyc")

        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
