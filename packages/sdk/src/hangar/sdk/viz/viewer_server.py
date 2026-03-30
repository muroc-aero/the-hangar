"""Daemon thread viewer for stdio transport (local dev).

Migrated from: OpenAeroStruct/oas_mcp/provenance/viewer_server.py
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from hangar.sdk.provenance.db import _dumps, get_session_graph, list_sessions

VIEWER_HTML = Path(__file__).parent / "viewer" / "index.html"
_DEFAULT_PORT = 7654

# Maps analysis_type to applicable plot types (for /plot_types endpoint)
ANALYSIS_PLOT_TYPES: dict[str, list[str]] = {
    "aero":         ["lift_distribution", "planform", "mesh_3d", "twist_chord_overlay"],
    "aerostruct":   ["lift_distribution", "stress_distribution", "planform", "mesh_3d",
                     "failure_heatmap", "deflection_profile", "twist_chord_overlay",
                     "weight_breakdown"],
    "drag_polar":   ["drag_polar"],
    "stability":    ["lift_distribution"],
    "optimization": ["opt_history", "opt_dv_evolution", "opt_comparison", "planform",
                     "mesh_3d", "twist_chord_overlay"],
}


def generate_plot_png(run_id: str, plot_type: str, *, user: str | None = None) -> bytes | None:
    """Load an artifact by run_id and return a rendered PNG as bytes.

    Returns None if the artifact is not found.
    Raises ValueError for invalid plot_type or if matplotlib is unavailable.

    Parameters
    ----------
    user:
        If given, restrict the artifact lookup to this user's directory.
        ``None`` (the default) searches all users.
    """
    from hangar.sdk.artifacts.store import ArtifactStore
    from hangar.sdk.viz.plotting import PLOT_TYPES, generate_plot

    if plot_type not in PLOT_TYPES or plot_type == "n2":
        raise ValueError(
            f"Unsupported plot_type {plot_type!r}. "
            f"Supported: {sorted(PLOT_TYPES - {'n2'})}"
        )

    store = ArtifactStore()
    artifact = store.get(run_id, user=user)
    if artifact is None and user is not None:
        # Fallback: artifact may have been created before per-user scoping
        # was enabled (stored under a different username).
        artifact = store.get(run_id)
    if artifact is None:
        return None

    results = artifact.get("results", {})
    artifact_type = artifact.get("metadata", {}).get("analysis_type", "aero")

    # For optimization runs, aero results live inside final_results
    if artifact_type == "optimization":
        plot_results = dict(results.get("final_results", {}))
    else:
        plot_results = dict(results)

    standard = results.get("standard_detail", {})

    # Inject sectional_data into per-surface dicts for lift/stress plots
    if standard.get("sectional_data"):
        for surf_name, sect in standard["sectional_data"].items():
            if surf_name in plot_results.get("surfaces", {}):
                plot_results["surfaces"][surf_name]["sectional_data"] = sect
        plot_results["sectional_data"] = standard.get("sectional_data", {})

    # Build mesh_data for planform / mesh_3d plots
    mesh_data: dict = {}
    mesh_snap = standard.get("mesh_snapshot", {})
    if mesh_snap:
        mesh_data["mesh_snapshot"] = mesh_snap
        for _surf_name, surf_mesh in mesh_snap.items():
            # Prefer full mesh (for mesh_3d); fall back to LE/TE (for planform)
            full_mesh = surf_mesh.get("mesh")
            if full_mesh is not None:
                mesh_data["mesh"] = full_mesh
            else:
                le = surf_mesh.get("leading_edge")
                te = surf_mesh.get("trailing_edge")
                if le and te:
                    mesh_data["mesh"] = np.array([le, te]).tolist()
            # Deformed mesh for deflection overlay
            def_mesh = surf_mesh.get("def_mesh")
            if def_mesh is not None:
                mesh_data["def_mesh"] = def_mesh
            # Structural FEM data for tube/wingbox rendering
            for struct_key in ("radius", "thickness", "fem_origin", "fem_model_type",
                               "spar_thickness", "skin_thickness"):
                if struct_key in surf_mesh:
                    mesh_data[struct_key] = surf_mesh[struct_key]
            break

    # Convergence data
    conv_data = results.get("convergence") or artifact.get("convergence") or {}

    # Optimization history for opt_* plots
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


def get_plot_types_for_run(run_id: str, *, user: str | None = None) -> list[str] | None:
    """Return applicable plot types for a run, or None if not found.

    Parameters
    ----------
    user:
        If given, restrict the lookup to this user's artifacts.
    """
    from hangar.sdk.artifacts.store import ArtifactStore

    store = ArtifactStore()
    summary = store.get_summary(run_id, user=user)
    if summary is None and user is not None:
        summary = store.get_summary(run_id)
    if summary is None:
        return None
    analysis_type = summary.get("analysis_type", "aero")
    return ANALYSIS_PLOT_TYPES.get(analysis_type, ["lift_distribution", "planform"])


def generate_dashboard_html(run_id: str, *, user: str | None = None) -> str | None:
    """Generate a context-rich HTML dashboard for a given run_id.

    Returns None if the artifact is not found.

    Parameters
    ----------
    user:
        If given, restrict the lookup to this user's artifacts.
    """
    from hangar.sdk.artifacts.store import ArtifactStore

    store = ArtifactStore()
    artifact = store.get(run_id, user=user)
    if artifact is None and user is not None:
        artifact = store.get(run_id)
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

    # Flight conditions
    flight = {}
    for key in ("velocity", "Mach_number", "density", "re", "alpha"):
        if key in results:
            flight[key] = results[key]

    # Key scalar results
    scalars = {}
    for key in ("CL", "CD", "L_over_D", "total_weight", "structural_mass"):
        if key in results:
            scalars[key] = results[key]
    # Check surfaces for failure
    for surf_name, surf_data in results.get("surfaces", {}).items():
        if "failure" in surf_data:
            scalars[f"{surf_name}.failure"] = surf_data["failure"]

    # For optimization runs, pull from final_results too
    if analysis_type == "optimization":
        final = results.get("final_results", {})
        for key in ("CL", "CD", "L_over_D", "total_weight"):
            if key in final and key not in scalars:
                scalars[key] = final[key]

    # Determine available plot types
    plot_types = ANALYSIS_PLOT_TYPES.get(analysis_type, ["lift_distribution", "planform"])

    # Build HTML
    flight_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in flight.items()
    )
    scalar_rows = "".join(
        f"<tr><td>{k}</td><td>{f'{v:.6g}' if isinstance(v, float) else v}</td></tr>"
        for k, v in scalars.items()
    )
    plot_panels = ""
    for pt in plot_types:
        pt_title = pt.replace("_", " ").title()
        onerror = "this.parentElement.innerHTML='<p class=no-data>Not available</p>'"
        plot_panels += (
            f'<div class="plot-panel">'
            f'<h3>{pt_title}</h3>'
            f'<img src="/plot?run_id={run_id}&amp;plot_type={pt}" '
            f'alt="{pt}" style="max-width:100%;height:auto;" '
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
            f'[{f.get("severity", "?")}] {f.get("message", "")}</div>'
        )

    viewer_link = ""
    if session_id:
        viewer_link = (
            f'<p><a href="/viewer?session_id={session_id}">'
            f'View provenance graph for session {session_id}</a></p>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OAS Dashboard — {run_id}</title>
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
  <h1>{analysis_type.replace("_", " ").title()} Analysis{f" — {run_name}" if run_name else ""}</h1>
  <div class="meta">
    Run ID: {run_id} &nbsp;|&nbsp; Surfaces: {", ".join(surfaces) if surfaces else "N/A"}
    &nbsp;|&nbsp; {timestamp}
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
    <p><a href="/plot_types?run_id={run_id}">Available plot types (JSON)</a></p>
  </div>
</div>

<h2 style="margin:20px 0 12px;color:#1a365d;">Plots</h2>
<div class="plots">
  {plot_panels}
</div>

<div class="footer">
  Generated by OpenAeroStruct MCP Server
</div>
</body>
</html>"""
    return html


class _ProvHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass  # Suppress request logging to avoid noise in MCP stdio output

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/viewer", "/viewer/"):
            self._serve_file(VIEWER_HTML, "text/html; charset=utf-8")
        elif path == "/graph":
            session_id = qs.get("session_id", [None])[0]
            if session_id is None:
                self._error(400, "Missing session_id query parameter")
                return
            try:
                graph = get_session_graph(session_id)
                self._json(graph)
                # Side-effect: flush graph file to artifact directory
                try:
                    from hangar.sdk.provenance.flush import flush_session_graph
                    flush_session_graph(session_id)
                except Exception:
                    pass
            except Exception as exc:
                self._error(500, str(exc))
        elif path == "/sessions":
            try:
                sessions = list_sessions()
                self._json(sessions)
            except Exception as exc:
                self._error(500, str(exc))
        elif path == "/plot":
            run_id = qs.get("run_id", [None])[0]
            plot_type = qs.get("plot_type", [None])[0]
            if not run_id or not plot_type:
                self._error(400, "Missing run_id or plot_type query parameters")
                return
            try:
                png_bytes = generate_plot_png(run_id, plot_type)
                if png_bytes is None:
                    self._error(404, f"Artifact not found: run_id={run_id!r}")
                else:
                    self._png(png_bytes)
            except ValueError as exc:
                self._error(400, str(exc))
            except Exception as exc:
                self._error(500, str(exc))
        elif path == "/plot_types":
            run_id = qs.get("run_id", [None])[0]
            if not run_id:
                self._error(400, "Missing run_id query parameter")
                return
            try:
                types = get_plot_types_for_run(run_id)
                if types is None:
                    self._error(404, f"Artifact not found: run_id={run_id!r}")
                else:
                    self._json(types)
            except Exception as exc:
                self._error(500, str(exc))
        elif path in ("/dashboard", "/dashboard/"):
            run_id = qs.get("run_id", [None])[0]
            if not run_id:
                self._error(400, "Missing run_id query parameter")
                return
            try:
                html = generate_dashboard_html(run_id)
                if html is None:
                    self._error(404, f"Artifact not found: run_id={run_id!r}")
                else:
                    self._html(html)
            except Exception as exc:
                self._error(500, str(exc))
        else:
            self._error(404, f"Not found: {path}")

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._error(404, f"File not found: {path}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj) -> None:
        data = _dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _png(self, data: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, message: str) -> None:
        data = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_viewer_server() -> int | None:
    """Start the viewer HTTP server in a background daemon thread.

    Returns the port number on success, or None if the port was busy.
    Disabled when ``HANGAR_PROV_VIEWER=off`` (recommended for production).
    """
    from hangar.sdk.env import _hangar_env

    if _hangar_env("HANGAR_PROV_VIEWER", "OAS_PROV_VIEWER").lower() == "off":
        return None
    port = int(
        _hangar_env("HANGAR_PROV_PORT", "OAS_PROV_PORT", default=str(_DEFAULT_PORT))
    )
    # Default to localhost in production; set HANGAR_PROV_HOST=0.0.0.0 explicitly
    # if Docker port mapping is needed in dev.
    bind_host = _hangar_env("HANGAR_PROV_HOST", "OAS_PROV_HOST", default="127.0.0.1")
    try:
        server = HTTPServer((bind_host, port), _ProvHandler)
    except OSError:
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port
