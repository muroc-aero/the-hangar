"""OpenAeroStruct MCP server -- FastMCP entry point.

Migrated from: OpenAeroStruct/oas_mcp/server.py
"""

from __future__ import annotations

# Load .env before any module-level env var reads.
# FastMCP() is constructed at module level — dotenv must run first.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

import os

from mcp.server.fastmcp import FastMCP

from hangar.sdk.auth.oidc import build_auth_settings, build_token_verifier, _env as _auth_env
from hangar.sdk.provenance.middleware import capture_tool, _prov_session_id
from hangar.oas.tools import session as _prov_tools

# ---------------------------------------------------------------------------
# Import tool functions from submodules
# ---------------------------------------------------------------------------

from hangar.oas.tools.geometry import create_surface
from hangar.oas.tools.analysis import (
    compute_drag_polar,
    compute_stability_derivatives,
    run_aero_analysis,
    run_aerostruct_analysis,
)
from hangar.oas.tools.optimization import run_optimization
from hangar.oas.tools.session import (
    delete_artifact,
    get_artifact,
    get_artifact_summary,
    list_artifacts,
)
from hangar.oas.tools.session import (
    get_detailed_results,
    get_last_logs,
    get_n2_html,
    get_run,
    pin_run,
    unpin_run,
    visualize,
)
from hangar.oas.tools.session import configure_session, reset, set_requirements
from hangar.oas.tools.resources import (
    WIDGET_URI as _WIDGET_URI,
    artifact_by_run_id,
    oas_dashboard_view,
    reference_guide,
    workflow_guide,
)
from hangar.oas.tools.prompts import (
    prompt_analyze_wing,
    prompt_aerostructural_design,
    prompt_compare_designs,
    prompt_optimize_wing,
)

# Re-export shared state and helpers for backward compatibility with tests
from hangar.sdk.state import sessions as _sessions, artifacts as _artifacts  # noqa: F401
from hangar.sdk.helpers import _get_viewer_base_url  # noqa: F401

# ---------------------------------------------------------------------------
# FastMCP construction
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "OpenAeroStruct",
    auth=build_auth_settings(),
    token_verifier=build_token_verifier(),
    # Pass host at construction time so FastMCP configures DNS rebinding protection
    # correctly.  When host="0.0.0.0" FastMCP skips the localhost-only allowlist,
    # which is required for ngrok (requests arrive with Host: <ngrok-url>).
    host=os.environ.get("OAS_HOST", "127.0.0.1"),
    instructions="""OpenAeroStruct aerostructural analysis and optimisation server.

REQUIRED WORKFLOW — always follow this order:
  0. start_session     — begin a provenance session (call once at workflow start)
  1. create_surface    — define geometry (call once per surface; must precede any analysis)
     log_decision      — record mesh/geometry choices (decision_type="mesh_resolution")
  2. run_aero_analysis / run_aerostruct_analysis / compute_drag_polar / etc. — analyse
     log_decision      — interpret results (decision_type="result_interpretation", prior_call_id=…)
  3. run_optimization (optional) — optimise design variables
     log_decision      — before: dv_selection + constraint_choice; after: convergence_assessment
  4. export_session_graph — save the provenance DAG at workflow end
  5. reset (optional)  — clear state between unrelated experiments

CRITICAL CONSTRAINTS:
  • num_y must be ODD (3, 5, 7, 9, …). Passing an even value raises an error.
  • Structural tools (run_aerostruct_analysis, and aerostruct optimization) require
    create_surface to have been called with fem_model_type="tube" or "wingbox" plus
    material properties (E, G, yield_stress, mrho). Aero-only surfaces will error.
  • Surface names are arbitrary strings but must match exactly between create_surface
    and analysis calls.
  • Ground effect (groundplane=True on create_surface) requires symmetry=True and is
    incompatible with sideslip (beta != 0). Using both raises an error.
  • omega (angular velocity) changes the OpenMDAO model topology — the first call with
    omega builds a new problem; subsequent calls reuse that rotational-enabled cache.

RESPONSE ENVELOPE (all analysis tools):
  Every analysis tool returns a versioned envelope (schema_version="1.0"):
    • results:     tool-specific payload (CL, CD, etc.)
    • validation:  physics and numerics checks — check "passed" before trusting results
    • telemetry:   timing and cache hit info
    • run_id:      use for get_run(), pin_run(), get_detailed_results(), visualize()
    • error:       present when the tool failed; check error.code for action to take
  Error codes: USER_INPUT_ERROR, SOLVER_CONVERGENCE_ERROR, CACHE_EVICTED_ERROR, INTERNAL_ERROR

VALIDATION:
  • Each response includes a "validation" block with physics/numerics checks.
  • Check validation.passed — if False, review validation.findings for error/warning details.
  • Each finding has: check_id, severity (error/warning/info), message, remediation hint.

OBSERVABILITY TOOLS:
  • get_run(run_id)                    — full manifest: inputs, outputs, validation, cache state
  • pin_run(run_id, surfaces, type)    — prevent cache eviction during multi-step workflows
  • unpin_run(run_id)                  — release pin when done
  • get_detailed_results(run_id, lvl)  — "standard" = sectional data; "full" = raw arrays
  • visualize(run_id, plot_type)       — ImageContent: lift_distribution, drag_polar,
                                         stress_distribution, convergence, planform,
                                         opt_history, opt_dv_evolution, opt_comparison,
                                         deflection_profile, weight_breakdown,
                                         failure_heatmap, twist_chord_overlay,
                                         mesh_3d, multipoint_comparison
  • get_last_logs(run_id)              — server-side log records for debugging
  • configure_session(session_id, ...) — set per-session defaults (detail level, auto-plots, etc.)

VISUALIZATION OUTPUT MODES:
  visualize() supports three output modes, controlled per-call (output=) or per-session
  (configure_session(visualization_output=)):
  • "inline" (default) — returns [metadata, ImageContent] — best for claude.ai
  • "file"             — saves PNG to disk, returns [metadata] with file_path — no [image] noise in CLI
  • "url"              — returns [metadata] with dashboard_url + plot_url — clickable links for CLI
  The per-call output= parameter overrides the session default.
  In CLI environments (Claude Code), prefer "file" or "url" mode to avoid unhelpful [image] output.

PARAMETER TIPS:
  • Cruise conditions: velocity=248 m/s, Mach_number=0.84, density=0.38 kg/m³, re=1e6
  • Good starting mesh: num_x=2, num_y=7 (fast); use num_y=15 for higher fidelity
  • wing_type="CRM" produces a realistic transport wing with built-in twist;
    wing_type="rect" produces a flat untwisted planform — simpler but less realistic
  • failure > 1.0 means structural failure (utilisation ratio > 1); failure < 1.0 = OK
  • L_equals_W residual near 0 means the wing is sized to carry the aircraft weight
  • mesh_3d plot: use run_aerostruct_analysis (not aero-only) with fem_model_type="tube"
    or "wingbox" to see structural elements + deflection overlay. Aero-only runs show
    wireframe only.
  • beta (sideslip angle, deg): set on run_aero_analysis / run_aerostruct_analysis /
    compute_drag_polar / compute_stability_derivatives. Default 0.0.
  • groundplane=True on create_surface enables ground effect; pair with height_agl
    (metres above ground, default 8000) on analysis tools. Low height_agl → more effect.
  • omega=[p, q, r] in deg/s on analysis tools enables rotational velocity effects
    (e.g. roll rate). Requires cg to be set for the moment arm calculation.

CONTROL-POINT ORDERING:
  • All *_cp arrays (twist_cp, chord_cp, thickness_cp, etc.) are ordered ROOT-to-TIP:
    cp[0] = root value, cp[-1] = tip value.
  • Example: twist_cp=[-7, 0] means root=-7° (washed in), tip=0° — correct washout.
  • Optimised DV arrays returned by run_optimization use the same root-to-tip ordering.

PERFORMANCE:
  • The first run_aero_analysis call builds and sets up the OpenMDAO problem (~0.1 s).
    Subsequent calls with the same surfaces reuse the cached problem — only the flight
    conditions change, so parameter sweeps are very fast.
  • Calling create_surface again with the same name invalidates the cache.
  • Use pin_run() to guarantee cache availability during multi-step workflows.

ARTIFACT STORAGE (every analysis is automatically saved):
  • Each analysis tool returns a run_id — use it to retrieve results later.
  • Storage hierarchy: {HANGAR_DATA_DIR}/{user}/{project}/{session_id}/{run_id}.json
  • HANGAR_USER env var sets user identity (default: OS login name)
  • OAS_PROJECT env var sets default project (default: "default")
  • Pass run_name="my label" to any analysis tool to tag a run
  • list_artifacts(session_id?, analysis_type?, user?, project?) — browse saved runs
  • get_artifact(run_id) — full metadata + results for a past run
  • get_artifact_summary(run_id) — metadata only (lightweight)
  • delete_artifact(run_id) — remove a saved artifact
  • oas://artifacts/{run_id} — resource access to any artifact by run_id

DESIGN VARIABLE NAMES FOR run_optimization:
  • All models:   'twist', 'chord', 'sweep', 'taper', 'alpha'
    Note: '_cp' suffix is accepted as an alias (e.g. 'twist_cp' → 'twist')
  • Tube only:    'thickness'   (maps to thickness_cp — does NOT exist on wingbox surfaces)
  • Wingbox only: 'spar_thickness', 'skin_thickness'  (do NOT use 'thickness' for wingbox)

CONSTRAINT NAMES FOR run_optimization:
  • All aerostruct: 'CL', 'CD', 'CM', 'failure', 'L_equals_W'
  • Tube only:      'thickness_intersects'  (NOT available for wingbox — raises an error)

Use the prompts (analyze_wing, aerostructural_design, optimize_wing, compare_designs) for guided
workflows, and the resources (oas://reference, oas://workflows) for quick lookup.

PROVENANCE & DECISION LOGGING:
  Agents MUST call log_decision at these decision points during every workflow:
  • After create_surface:        decision_type="mesh_resolution"
                                  — why this num_x / num_y / wing_type was chosen
  • After any analysis tool:     decision_type="result_interpretation"
                                  — what the results mean and what to do next
                                  — pass prior_call_id from the analysis _provenance.call_id
  • Before run_optimization:     decision_type="dv_selection"
                                  — why these design variables and bounds
  • Before run_optimization:     decision_type="constraint_choice"
                                  — why these constraints and targets
  • After run_optimization:      decision_type="convergence_assessment"
                                  — did it converge, is the result trustworthy
                                  — pass prior_call_id from the optimization _provenance.call_id
  Always pass prior_call_id when the decision is directly informed by a specific tool result.

  Tool signatures:
  • start_session(notes)           — begin a named provenance session; call at workflow start
  • log_decision(type, reasoning, selected_action, prior_call_id?, confidence?) — record why
  • export_session_graph(session_id?, output_path?) — export DAG as JSON; load into viewer""",
)

# ---------------------------------------------------------------------------
# Register analysis tools (with @capture_tool for provenance)
# ---------------------------------------------------------------------------

mcp.tool()(capture_tool(create_surface))
mcp.tool()(capture_tool(run_aero_analysis))
mcp.tool()(capture_tool(run_aerostruct_analysis))
mcp.tool()(capture_tool(compute_drag_polar))
mcp.tool()(capture_tool(compute_stability_derivatives))
mcp.tool()(capture_tool(run_optimization))
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
mcp.tool(meta={"ui": {"resourceUri": _WIDGET_URI}})(capture_tool(visualize))
mcp.tool()(capture_tool(get_n2_html))
mcp.tool()(capture_tool(get_last_logs))

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
# Register MCP resources
# ---------------------------------------------------------------------------

mcp.resource(
    _WIDGET_URI,
    name="OAS Dashboard",
    description="Interactive OpenAeroStruct dashboard (MCP Apps widget)",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"csp": {"resourceDomains": ["https://cdn.plot.ly", "https://unpkg.com"]}}},
)(oas_dashboard_view)

mcp.resource("oas://reference", description="Parameter reference for all OAS MCP tools")(reference_guide)
mcp.resource("oas://workflows", description="Step-by-step workflows for common analysis tasks")(workflow_guide)
mcp.resource("oas://artifacts/{run_id}", description="Retrieve a saved analysis artifact by run_id")(artifact_by_run_id)

# ---------------------------------------------------------------------------
# Register MCP prompts
# ---------------------------------------------------------------------------

mcp.prompt(
    name="analyze_wing",
    description="Set up and run a complete aerodynamic wing analysis (aero + drag polar + stability)",
)(prompt_analyze_wing)

mcp.prompt(
    name="aerostructural_design",
    description="Run a coupled aerostructural analysis and interpret structural health",
)(prompt_aerostructural_design)

mcp.prompt(
    name="optimize_wing",
    description="Optimise wing twist and/or thickness for minimum drag or fuel burn",
)(prompt_optimize_wing)

mcp.prompt(
    name="compare_designs",
    description="Compare two OAS analysis runs side by side using run_ids",
)(prompt_compare_designs)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Console-script entry point for oas-mcp.

    Supports two transports:

    * ``stdio`` (default) — standard MCP stdio transport for Claude Desktop /
      local clients.
    * ``http`` — streamable HTTP transport for remote clients.  Requires the
      ``[http]`` extra (``pip install 'openaerostruct[http]'``).  Reads host
      and port from ``--host`` / ``--port`` CLI args or ``OAS_HOST`` /
      ``OAS_PORT`` env vars.

    Set the transport via ``--transport`` or the ``OAS_TRANSPORT`` env var.

    Environment variables are loaded from a ``.env`` file in the working
    directory (or any parent) via ``python-dotenv`` at module import time,
    before Keycloak settings and FastMCP are initialised.  Variables already
    set in the process environment take precedence over the file.
    """
    import argparse
    from hangar.sdk.provenance.db import init_db as _prov_init_db, record_session as _prov_record_session

    parser = argparse.ArgumentParser(description="OpenAeroStruct MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("OAS_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OAS_HOST", "127.0.0.1"),
        help="Bind host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OAS_PORT", "8000")),
        help="Bind port for HTTP transport (default: 8000)",
    )
    args = parser.parse_args()

    # --- Provenance setup ---
    from hangar.sdk.provenance.middleware import set_tool_name
    set_tool_name("oas")
    _prov_init_db()
    import uuid as _uuid
    _auto_sid = f"auto-{_uuid.uuid4().hex[:8]}"
    _prov_session_id.set(_auto_sid)
    _prov_record_session(_auto_sid, notes="Auto-created on server startup")
    if args.transport == "stdio":
        # Legacy daemon thread viewer for local dev (localhost only, no auth)
        try:
            import sys as _sys
            from hangar.sdk.viz.viewer_server import start_viewer_server as _start_viewer
            _prov_port = _start_viewer()
            if _prov_port:
                _sep = "\u2500" * 54
                print(f"\n{_sep}", file=_sys.stderr)
                print("  OAS Provenance Viewer", file=_sys.stderr)
                print(_sep, file=_sys.stderr)
                print(f"  Viewer    http://localhost:{_prov_port}/viewer", file=_sys.stderr)
                print(f"            Interactive DAG \u2014 load any session from the", file=_sys.stderr)
                print(f"            drop-down or drop an exported JSON file.", file=_sys.stderr)
                print(f"  Sessions  http://localhost:{_prov_port}/sessions", file=_sys.stderr)
                print(f"            JSON list of all recorded provenance sessions.", file=_sys.stderr)
                print(f"  Plot API  http://localhost:{_prov_port}/plot?run_id=<id>&plot_type=<type>", file=_sys.stderr)
                print(f"            Render a saved analysis run as a PNG image.", file=_sys.stderr)
                print(_sep + "\n", file=_sys.stderr)
        except Exception:
            pass
        mcp.run()
    else:
        # --- HTTP transport ---
        try:
            import uvicorn
        except ImportError as exc:
            raise ImportError(
                "uvicorn is required for HTTP transport. "
                "Install it with: pip install 'openaerostruct[http]'"
            ) from exc

        import sys as _sys
        from hangar.sdk.viz.viewer_routes import build_viewer_app

        _warn_if_unauthenticated(args.host, args.port)
        mcp_asgi = mcp.streamable_http_app()
        viewer_app, auth_mode = build_viewer_app()

        if viewer_app is not None:
            # Run OIDC discovery before starting the server (if OIDC mode).
            if auth_mode == "oidc":
                import asyncio as _asyncio
                from hangar.sdk.viz.viewer_auth import discover_oidc_endpoints
                _asyncio.run(discover_oidc_endpoints(viewer_app.state.oidc_config))

            # Compose viewer + MCP: viewer handles its known paths,
            # everything else falls through to the MCP ASGI app.
            from hangar.sdk.viz.viewer_routes import make_fallback_app
            app = make_fallback_app(viewer_app, mcp_asgi)
            # Print viewer info
            _sep = "\u2500" * 54
            print(f"\n{_sep}", file=_sys.stderr)
            print("  OAS Provenance Viewer (HTTP transport)", file=_sys.stderr)
            print(_sep, file=_sys.stderr)
            print(f"  Viewer    http://{args.host}:{args.port}/viewer", file=_sys.stderr)
            if auth_mode == "oidc":
                print(f"            Protected by OIDC ({viewer_app.state.oidc_config.issuer_url})", file=_sys.stderr)
            else:
                print(f"            Protected by Basic Auth (OAS_VIEWER_USER/PASSWORD)", file=_sys.stderr)
            print(_sep + "\n", file=_sys.stderr)
        else:
            app = mcp_asgi

        # Add unauthenticated /healthz endpoint
        from hangar.sdk.health import add_healthz
        app = add_healthz(app, server_name="oas")

        uvicorn.run(app, host=args.host, port=args.port)
    # --- End provenance setup ---


def _warn_if_unauthenticated(host: str, port: int) -> None:
    """Print a loud warning to stderr when HTTP transport runs without auth."""
    import sys

    issuer_url = _auth_env("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL")

    if issuer_url:
        print(
            f"\n  OAS MCP \u2014 HTTP transport  |  auth: OIDC ({issuer_url})\n",
            file=sys.stderr,
        )
        return

    url = f"http://{host}:{port}/mcp"
    print(
        "\n"
        "\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557\n"
        "\u2551                  \u26a0  NO AUTHENTICATION ENABLED  \u26a0                \u2551\n"
        "\u2560\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2563\n"
        "\u2551  The server is accepting ALL requests on:                        \u2551\n"
        f"\u2551    {url:<60}  \u2551\n"
        "\u2551                                                                  \u2551\n"
        "\u2551  Anyone who can reach this port can call every tool, run         \u2551\n"
        "\u2551  optimizations, and read/delete all stored artifacts.            \u2551\n"
        "\u2551                                                                  \u2551\n"
        "\u2551  This is fine for local development.  For any deployment that    \u2551\n"
        "\u2551  is reachable over a network, set:                               \u2551\n"
        "\u2551                                                                  \u2551\n"
        "\u2551    OIDC_ISSUER_URL=https://<provider>/...                        \u2551\n"
        "\u2551    OIDC_CLIENT_ID=oas-mcp                                        \u2551\n"
        "\u2551    OIDC_CLIENT_SECRET=<secret>                                    \u2551\n"
        "\u2551                                                                  \u2551\n"
        "\u2551  Works with any OIDC provider (Authentik, Keycloak, Auth0, \u2026).  \u2551\n"
        "\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\n",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
