"""Unified Hangar provenance viewer.

A lightweight Starlette app that reads from all per-tool provenance
databases and artifact stores, giving a single view of cross-tool
workflows.

Environment variables
---------------------
HANGAR_VIEWER_DBS
    Comma-separated ``tool=path`` pairs pointing to each tool's SQLite
    provenance database.  Example::

        oas=/data/oas/provenance.db,ocp=/data/ocp/provenance.db,pyc=/data/pyc/provenance.db

HANGAR_VIEWER_DATA_DIRS
    Comma-separated ``tool=path`` pairs pointing to each tool's artifact
    data directory.  Example::

        oas=/data/oas,ocp=/data/ocp,pyc=/data/pyc

    If not set, derived from HANGAR_VIEWER_DBS by using the parent
    directory of each database file.

HANGAR_VIEWER_PORT
    Port to listen on (default: 8080).

HANGAR_VIEWER_HOST
    Host to bind to (default: 0.0.0.0).

Authentication
--------------
Supports the same auth modes as per-tool viewers:

1. OIDC (if ``OIDC_ISSUER_URL`` + ``HANGAR_VIEWER_OIDC_CLIENT_SECRET`` set)
2. Basic Auth (if ``HANGAR_VIEWER_USER`` + ``HANGAR_VIEWER_PASSWORD`` set)
3. No auth (dev only -- all endpoints are open)

In OIDC mode, ``RESOURCE_SERVER_URL`` should point to the unified viewer's
external URL (e.g. ``https://mcp.lakesideai.dev/viewer``) so the callback
redirect works correctly.
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from hangar.viewer.reader import MultiDBProvenanceReader, parse_db_spec

logger = logging.getLogger(__name__)

# Module-level state, initialised in main().
_reader: MultiDBProvenanceReader | None = None
_artifact_stores: dict[str, object] = {}  # tool -> ArtifactStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_reader() -> MultiDBProvenanceReader:
    if _reader is None:
        raise RuntimeError("Viewer not initialised -- set HANGAR_VIEWER_DBS")
    return _reader


def _dumps(obj) -> str:
    """JSON-encode with str() fallback for non-serialisable values."""
    def _default(o):
        return str(o)
    return json.dumps(obj, default=_default)


def _effective_user(request: Request) -> str | None:
    """Return the user to scope lookups to, or None for all.

    In OIDC mode regular users see only their own data; admins see all.
    In Basic Auth or no-auth mode returns None (no scoping).
    """
    user = getattr(request.state, "viewer_user", "")
    if not user:
        return None
    is_admin = getattr(request.state, "viewer_is_admin", False)
    if is_admin:
        return None
    return user


def _find_artifact(run_id: str, user: str | None = None):
    """Search all tool artifact stores for a run_id.

    When *user* is set (OIDC non-admin), only that user's artifacts
    are searched.  When *user* is None (admin or no auth), all
    artifacts are searched.
    """
    for tool, store in _artifact_stores.items():
        artifact = store.get(run_id, user=user)
        if artifact is not None:
            return artifact, tool
    return None, None


def _generate_plot_png_multi(run_id: str, plot_type: str, user: str | None = None) -> bytes | None:
    """Generate a plot PNG by searching all artifact stores.

    The SDK's generate_plot_png() only checks the default ArtifactStore.
    This wrapper finds the artifact across all tool stores, then calls
    the SDK plot renderer with the correct data.
    """
    from hangar.sdk.viz.plotting import PLOT_TYPES, generate_plot
    import numpy as np

    if plot_type not in PLOT_TYPES or plot_type == "n2":
        raise ValueError(
            f"Unsupported plot_type {plot_type!r}. "
            f"Supported: {sorted(PLOT_TYPES - {'n2'})}"
        )

    artifact, _tool = _find_artifact(run_id, user=user)
    if artifact is None:
        return None

    results = artifact.get("results", {})
    artifact_type = artifact.get("metadata", {}).get("analysis_type", "aero")

    if artifact_type == "optimization":
        plot_results = dict(results.get("final_results", {}))
    else:
        plot_results = dict(results)

    standard = results.get("standard_detail", {})

    # Inject sectional_data
    if standard.get("sectional_data"):
        for surf_name, sect in standard["sectional_data"].items():
            if surf_name in plot_results.get("surfaces", {}):
                plot_results["surfaces"][surf_name]["sectional_data"] = sect
        plot_results["sectional_data"] = standard.get("sectional_data", {})

    # Build mesh_data
    mesh_data: dict = {}
    mesh_snap = standard.get("mesh_snapshot", {})
    if mesh_snap:
        mesh_data["mesh_snapshot"] = mesh_snap
        for _surf_name, surf_mesh in mesh_snap.items():
            full_mesh = surf_mesh.get("mesh")
            if full_mesh is not None:
                mesh_data["mesh"] = full_mesh
            else:
                le = surf_mesh.get("leading_edge")
                te = surf_mesh.get("trailing_edge")
                if le and te:
                    mesh_data["mesh"] = np.array([le, te]).tolist()
            def_mesh = surf_mesh.get("def_mesh")
            if def_mesh is not None:
                mesh_data["def_mesh"] = def_mesh
            for struct_key in ("radius", "thickness", "fem_origin", "fem_model_type",
                               "spar_thickness", "skin_thickness"):
                if struct_key in surf_mesh:
                    mesh_data[struct_key] = surf_mesh[struct_key]
            break

    conv_data = results.get("convergence") or artifact.get("convergence") or {}

    opt_history: dict | None = None
    if artifact_type == "optimization" or plot_type.startswith("opt_"):
        raw_hist = results.get("optimization_history", {})
        opt_history = {
            **raw_hist,
            "final_dvs": results.get("optimized_design_variables", {}),
        }

    plot_result = generate_plot(
        plot_type, run_id, plot_results, conv_data, mesh_data, "", opt_history
    )
    return plot_result.image.data


def _generate_dashboard_html_multi(run_id: str, user: str | None = None) -> str | None:
    """Generate dashboard HTML by searching all artifact stores."""
    from hangar.sdk.viz.viewer_server import ANALYSIS_PLOT_TYPES

    artifact, _tool = _find_artifact(run_id, user=user)
    if artifact is None:
        return None

    metadata = artifact.get("metadata", {})
    results = artifact.get("results", {})
    validation = artifact.get("validation", {})
    analysis_type = metadata.get("analysis_type", "aero")
    run_name = metadata.get("run_name", "")
    timestamp = metadata.get("timestamp", "")
    surfaces = metadata.get("surfaces", [])
    session_id = metadata.get("session_id", "")
    tool_name = metadata.get("tool_name", "Hangar")

    flight = {}
    for key in ("velocity", "Mach_number", "density", "re", "alpha"):
        if key in results:
            flight[key] = results[key]

    scalars = {}
    for key in ("CL", "CD", "L_over_D", "total_weight", "structural_mass"):
        if key in results:
            scalars[key] = results[key]
    for surf_name, surf_data in results.get("surfaces", {}).items():
        if "failure" in surf_data:
            scalars[f"{surf_name}.failure"] = surf_data["failure"]

    if analysis_type == "optimization":
        final = results.get("final_results", {})
        for key in ("CL", "CD", "L_over_D", "total_weight"):
            if key in final and key not in scalars:
                scalars[key] = final[key]

    plot_types = ANALYSIS_PLOT_TYPES.get(analysis_type, [])

    _e = _html.escape

    flight_rows = "".join(
        f"<tr><td>{_e(str(k))}</td><td>{_e(str(v))}</td></tr>" for k, v in flight.items()
    )
    scalar_rows = "".join(
        f"<tr><td>{_e(str(k))}</td><td>{_e(f'{v:.6g}' if isinstance(v, float) else str(v))}</td></tr>"
        for k, v in scalars.items()
    )
    plot_panels = ""
    for pt in plot_types:
        pt_title = _e(pt.replace("_", " ").title())
        onerror = "this.parentElement.innerHTML='<p class=no-data>Not available</p>'"
        plot_panels += (
            f'<div class="plot-panel">'
            f'<h3>{pt_title}</h3>'
            f'<img src="plot?run_id={_e(run_id)}&amp;plot_type={_e(pt)}" '
            f'alt="{_e(pt)}" style="max-width:100%;height:auto;" '
            f'onerror="{onerror}">'
            f'</div>'
        )

    validation_passed = validation.get("passed", True)
    validation_badge = (
        '<span style="color:green;font-weight:bold;">PASSED</span>'
        if validation_passed
        else '<span style="color:red;font-weight:bold;">FAILED</span>'
    )
    findings_html = ""
    for f in validation.get("findings", []):
        color = {"error": "red", "warning": "orange"}.get(f.get("severity", ""), "#666")
        findings_html += (
            f'<div style="color:{color};margin:2px 0;">'
            f'[{_e(str(f.get("severity", "?")))}] {_e(str(f.get("message", "")))}</div>'
        )

    viewer_link = ""
    if session_id:
        viewer_link = (
            f'<p><a href="viewer?session_id={_e(session_id)}">'
            f'View provenance graph for session {_e(session_id)}</a></p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(tool_name)} Dashboard -- {_e(run_id)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f5f7fa; color: #333; padding: 20px; }}
  .header {{ background: #1a365d; color: white; padding: 20px 24px; border-radius: 8px;
             margin-bottom: 20px; }}
  .header h1 {{ font-size: 1.4em; margin-bottom: 8px; }}
  .header .meta {{ font-size: 0.85em; opacity: 0.85; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  .card {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .card h2 {{ font-size: 1em; color: #1a365d; margin-bottom: 10px; border-bottom: 1px solid #e2e8f0;
              padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
  td {{ padding: 4px 8px; border-bottom: 1px solid #f0f0f0; }}
  td:first-child {{ font-weight: 600; color: #555; width: 45%; }}
  .plots {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
            gap: 16px; margin-bottom: 20px; }}
  .plot-panel {{ background: white; border-radius: 8px; padding: 16px;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .plot-panel h3 {{ font-size: 0.95em; color: #1a365d; margin-bottom: 10px; }}
  .plot-panel img {{ border-radius: 4px; }}
  .no-data {{ color: #999; font-style: italic; padding: 20px; text-align: center; }}
  .footer {{ text-align: center; color: #999; font-size: 0.8em; margin-top: 20px; }}
  a {{ color: #2b6cb0; }}
</style>
</head>
<body>
<div class="header">
  <h1>{_e(analysis_type.replace("_", " ").title())} Analysis{f" -- {_e(run_name)}" if run_name else ""}</h1>
  <div class="meta">
    Run ID: {_e(run_id)} &nbsp;|&nbsp; Surfaces: {_e(", ".join(surfaces)) if surfaces else "N/A"}
    &nbsp;|&nbsp; {_e(timestamp)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Flight Conditions</h2>
    <table>{flight_rows if flight_rows else "<tr><td colspan='2' class='no-data'>No flight condition data</td></tr>"}</table>
  </div>
  <div class="card">
    <h2>Key Results</h2>
    <table>{scalar_rows if scalar_rows else "<tr><td colspan='2' class='no-data'>No scalar results</td></tr>"}</table>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Validation {validation_badge}</h2>
    {findings_html if findings_html else '<p class="no-data">All checks passed</p>'}
  </div>
  <div class="card">
    <h2>Links</h2>
    {viewer_link}
    <p><a href="plot_types?run_id={_e(run_id)}">Available plot types (JSON)</a></p>
  </div>
</div>

<h2 style="margin:20px 0 12px;color:#1a365d;">Plots</h2>
<div class="plots">
  {plot_panels}
</div>

<div class="footer">
  Generated by {_e(tool_name)} MCP Server
</div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def viewer_html(request: Request) -> Response:
    """Serve the viewer/index.html page."""
    try:
        from hangar.sdk.viz.viewer_server import VIEWER_HTML
        html_path = VIEWER_HTML
    except ImportError:
        return Response("Viewer HTML not found", status_code=404)

    if not html_path.exists():
        return Response("Viewer HTML not found", status_code=404)

    content = await asyncio.to_thread(html_path.read_text, "utf-8")
    return HTMLResponse(content)


async def sessions_endpoint(request: Request) -> Response:
    """Return merged session list from all tool DBs."""
    reader = _get_reader()
    user = _effective_user(request)
    sessions = await asyncio.to_thread(reader.list_sessions, user=user)
    return Response(
        content=_dumps(sessions),
        status_code=200,
        media_type="application/json",
    )


async def graph_endpoint(request: Request) -> Response:
    """Return merged provenance DAG for a session, across all tools."""
    session_id = request.query_params.get("session_id")
    if not session_id:
        return JSONResponse({"error": "Missing session_id query parameter"}, status_code=400)

    reader = _get_reader()

    # Check ownership in OIDC mode
    user = _effective_user(request)
    if user is not None:
        owner = await asyncio.to_thread(reader.get_session_owner, session_id)
        if owner and owner != user:
            return JSONResponse({"error": "Session not found"}, status_code=404)

    try:
        graph = await asyncio.to_thread(reader.get_session_graph, session_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    return Response(
        content=_dumps(graph),
        status_code=200,
        media_type="application/json",
    )


async def plot_endpoint(request: Request) -> Response:
    """Render a plot from any tool's artifact store."""
    run_id = request.query_params.get("run_id")
    plot_type = request.query_params.get("plot_type")
    if not run_id or not plot_type:
        return JSONResponse(
            {"error": "Missing run_id or plot_type query parameters"}, status_code=400,
        )

    user = _effective_user(request)
    try:
        png_bytes = await asyncio.to_thread(
            _generate_plot_png_multi, run_id, plot_type, user=user,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if png_bytes is None:
        return JSONResponse(
            {"error": f"Artifact not found: run_id={run_id!r}"}, status_code=404,
        )
    return Response(content=png_bytes, status_code=200, media_type="image/png")


async def plot_types_endpoint(request: Request) -> Response:
    """Return applicable plot types for a run (searches all stores)."""
    run_id = request.query_params.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id query parameter"}, status_code=400)

    from hangar.sdk.viz.viewer_server import ANALYSIS_PLOT_TYPES

    user = _effective_user(request)
    artifact, _tool = await asyncio.to_thread(_find_artifact, run_id, user)
    if artifact is None:
        return JSONResponse(
            {"error": f"Artifact not found: run_id={run_id!r}"}, status_code=404,
        )

    analysis_type = artifact.get("metadata", {}).get("analysis_type", "")
    types = ANALYSIS_PLOT_TYPES.get(analysis_type, [])
    return JSONResponse(types)


async def dashboard_endpoint(request: Request) -> Response:
    """Serve a dashboard for a run (searches all tool stores)."""
    run_id = request.query_params.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id query parameter"}, status_code=400)

    user = _effective_user(request)
    try:
        html = await asyncio.to_thread(
            _generate_dashboard_html_multi, run_id, user=user,
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if html is None:
        return JSONResponse(
            {"error": f"Artifact not found: run_id={run_id!r}"}, status_code=404,
        )
    return HTMLResponse(html)


async def healthz(request: Request) -> Response:
    """Unauthenticated health check."""
    return JSONResponse({"status": "ok", "server": "hangar-viewer"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _content_routes():
    """Return the list of content-serving route tuples (path, handler)."""
    return [
        ("/viewer", viewer_html),
        ("/viewer/", viewer_html),
        ("/sessions", sessions_endpoint),
        ("/graph", graph_endpoint),
        ("/plot", plot_endpoint),
        ("/plot_types", plot_types_endpoint),
        ("/dashboard", dashboard_endpoint),
        ("/dashboard/", dashboard_endpoint),
    ]


def build_app() -> tuple[Starlette, str]:
    """Build the unified viewer Starlette app with auth.

    Returns ``(app, auth_mode)`` where auth_mode is ``"oidc"``,
    ``"basic"``, or ``""`` (no auth).
    """
    from hangar.sdk.viz.viewer_auth import build_viewer_oidc_config, require_viewer_oidc
    from hangar.sdk.viz.viewer_routes import _build_oidc_routes, _require_basic_auth

    oidc_config = build_viewer_oidc_config()

    if oidc_config is not None:
        # --- OIDC mode ---
        oidc_decorator = require_viewer_oidc(oidc_config)
        routes = [Route(p, oidc_decorator(h)) for p, h in _content_routes()]
        routes += _build_oidc_routes(oidc_config)
        routes.append(Route("/healthz", healthz))

        resource_server_url = os.environ.get(
            "RESOURCE_SERVER_URL", "http://localhost:8080"
        ).rstrip("/")
        https_only = resource_server_url.startswith("https")

        from starlette.middleware.sessions import SessionMiddleware

        app = Starlette(
            routes=routes,
            middleware=[
                Middleware(
                    SessionMiddleware,
                    secret_key=oidc_config.session_secret,
                    session_cookie="hangar_unified_viewer_session",
                    same_site="lax",
                    https_only=https_only,
                    max_age=86400,
                ),
                Middleware(
                    CORSMiddleware,
                    allow_origins=[resource_server_url],
                    allow_methods=["GET"],
                    allow_credentials=True,
                ),
            ],
        )
        app.state.oidc_config = oidc_config
        return app, "oidc"

    # --- Basic Auth fallback ---
    from hangar.sdk.env import _hangar_env

    viewer_user = _hangar_env("HANGAR_VIEWER_USER", "OAS_VIEWER_USER")
    viewer_password = _hangar_env("HANGAR_VIEWER_PASSWORD", "OAS_VIEWER_PASSWORD")

    if viewer_user and viewer_password:
        routes = [Route(p, _require_basic_auth(h)) for p, h in _content_routes()]
        routes.append(Route("/healthz", healthz))

        resource_server_url = os.environ.get(
            "RESOURCE_SERVER_URL", "http://localhost:8080"
        ).rstrip("/")

        app = Starlette(
            routes=routes,
            middleware=[
                Middleware(
                    CORSMiddleware,
                    allow_origins=[resource_server_url],
                    allow_methods=["GET"],
                    allow_headers=["Authorization"],
                ),
            ],
        )
        app.state.viewer_user = viewer_user
        app.state.viewer_password = viewer_password
        return app, "basic"

    # --- No auth (dev mode) ---
    logger.warning(
        "Unified viewer running without authentication. "
        "Set HANGAR_VIEWER_OIDC_CLIENT_SECRET or HANGAR_VIEWER_USER/PASSWORD "
        "for production use."
    )
    routes = [Route(p, h) for p, h in _content_routes()]
    routes.append(Route("/healthz", healthz))

    app = Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET"],
            ),
        ],
    )
    return app, ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Console-script entry point for hangar-viewer."""
    global _reader, _artifact_stores

    import argparse

    parser = argparse.ArgumentParser(description="Hangar Unified Provenance Viewer")
    parser.add_argument(
        "--host",
        default=os.environ.get("HANGAR_VIEWER_HOST", "0.0.0.0"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("HANGAR_VIEWER_PORT", "8080")),
    )
    args = parser.parse_args()

    # Parse DB spec
    db_spec = os.environ.get("HANGAR_VIEWER_DBS", "")
    if not db_spec:
        logger.error(
            "HANGAR_VIEWER_DBS not set. Example: "
            "oas=/data/oas/provenance.db,ocp=/data/ocp/provenance.db"
        )
        raise SystemExit(1)

    db_paths = parse_db_spec(db_spec)
    _reader = MultiDBProvenanceReader(db_paths)

    # Parse or derive data dirs for artifact stores
    data_dir_spec = os.environ.get("HANGAR_VIEWER_DATA_DIRS", "")
    if data_dir_spec:
        data_dirs = {}
        for entry in data_dir_spec.split(","):
            entry = entry.strip()
            if "=" in entry:
                tool, path_str = entry.split("=", 1)
                data_dirs[tool.strip()] = Path(path_str.strip())
    else:
        # Derive from DB paths: /data/oas/provenance.db -> /data/oas
        data_dirs = {tool: path.parent for tool, path in db_paths.items()}

    # Create one ArtifactStore per tool, each pointing at that tool's data dir
    from hangar.sdk.artifacts.store import ArtifactStore

    for tool, data_dir in data_dirs.items():
        _artifact_stores[tool] = ArtifactStore(data_dir=data_dir)

    app, auth_mode = build_app()

    import sys
    _sep = "\u2500" * 54
    print(f"\n{_sep}", file=sys.stderr)
    print("  Hangar Unified Provenance Viewer", file=sys.stderr)
    print(_sep, file=sys.stderr)
    print(f"  Viewer    http://{args.host}:{args.port}/viewer", file=sys.stderr)
    print(f"  Sessions  http://{args.host}:{args.port}/sessions", file=sys.stderr)
    print(f"  Tools     {', '.join(sorted(db_paths.keys()))}", file=sys.stderr)
    for tool, path in sorted(db_paths.items()):
        exists = "\u2713" if path.exists() else "\u2717"
        print(f"    {exists} {tool}: {path}", file=sys.stderr)
    if auth_mode == "oidc":
        print(f"  Auth      OIDC", file=sys.stderr)
    elif auth_mode == "basic":
        print(f"  Auth      Basic Auth", file=sys.stderr)
    else:
        print(f"  Auth      NONE (dev mode)", file=sys.stderr)
    print(_sep + "\n", file=sys.stderr)

    # OIDC discovery (must happen before uvicorn starts)
    if auth_mode == "oidc":
        import asyncio as _asyncio
        from hangar.sdk.viz.viewer_auth import discover_oidc_endpoints
        _asyncio.run(discover_oidc_endpoints(app.state.oidc_config))

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
