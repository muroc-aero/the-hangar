"""HTTP routes for the provenance viewer.

Migrated from: OpenAeroStruct/oas_mcp/core/viewer_routes.py
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import secrets
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Basic Auth helpers (fallback mode)
# ---------------------------------------------------------------------------

def _check_basic_auth(request: Request, username: str, password: str) -> bool:
    """Return True if the request carries a valid Basic Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
    except Exception:
        return False
    parts = decoded.split(":", 1)
    if len(parts) != 2:
        return False
    return secrets.compare_digest(parts[0], username) and secrets.compare_digest(
        parts[1], password
    )


def _require_basic_auth(handler):
    """Decorator that enforces Basic Auth on a Starlette endpoint."""

    async def wrapper(request: Request) -> Response:
        username = request.app.state.viewer_user
        password = request.app.state.viewer_password
        if not _check_basic_auth(request, username, password):
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="OAS Viewer"'},
                media_type="text/plain",
            )
        return await handler(request)

    return wrapper


# ---------------------------------------------------------------------------
# Helpers for extracting effective user from the request
# ---------------------------------------------------------------------------

def _effective_user(request: Request) -> str | None:
    """Return the user to scope artifact lookups to, or ``None`` for all.

    In OIDC mode, regular users are scoped to their own artifacts; admins
    see everything (``None``).  In Basic Auth mode, returns ``None`` (no
    per-user scoping).
    """
    from hangar.sdk.viz.viewer_auth import get_viewer_user, is_viewer_admin

    user = get_viewer_user(request)
    if not user:
        return None  # Basic Auth mode — no per-user scoping
    if is_viewer_admin(request):
        return None  # Admin sees all
    return user


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------
# These are *undecorated* — the auth decorator is applied at app-build time
# depending on the auth mode.

async def viewer_html(request: Request) -> Response:
    """Serve the viewer/index.html page."""
    from hangar.sdk.viz.viewer_server import VIEWER_HTML

    if not VIEWER_HTML.exists():
        return Response("Viewer HTML not found", status_code=404, media_type="text/plain")
    content = await asyncio.to_thread(VIEWER_HTML.read_text, "utf-8")
    return HTMLResponse(content)


async def sessions_endpoint(request: Request) -> Response:
    """Return JSON list of provenance sessions (scoped to user in OIDC mode)."""
    from hangar.sdk.provenance.db import _dumps, list_sessions

    user = _effective_user(request)
    sessions = await asyncio.to_thread(list_sessions, user=user)
    return Response(
        content=_dumps(sessions),
        status_code=200,
        media_type="application/json",
    )


async def graph_endpoint(request: Request) -> Response:
    """Return JSON DAG for a given session_id (scoped to user in OIDC mode)."""
    from hangar.sdk.provenance.db import _dumps, get_session_graph, get_session_owner

    session_id = request.query_params.get("session_id")
    if not session_id:
        return JSONResponse({"error": "Missing session_id query parameter"}, status_code=400)

    # Check ownership: non-admin users can only view their own sessions
    # (or sessions with no owner, for backward compat with pre-OIDC data).
    user = _effective_user(request)
    if user is not None:
        owner = await asyncio.to_thread(get_session_owner, session_id)
        if owner and owner != user:
            return JSONResponse({"error": "Session not found"}, status_code=404)

    try:
        graph = await asyncio.to_thread(get_session_graph, session_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    # Side-effect: flush graph file to artifact directory
    try:
        from hangar.sdk.provenance.flush import flush_session_graph
        await asyncio.to_thread(flush_session_graph, session_id)
    except Exception:
        pass

    return Response(
        content=_dumps(graph),
        status_code=200,
        media_type="application/json",
    )


async def plot_endpoint(request: Request) -> Response:
    """Render a saved analysis run as a PNG image."""
    from hangar.sdk.viz.viewer_server import generate_plot_png

    run_id = request.query_params.get("run_id")
    plot_type = request.query_params.get("plot_type")
    if not run_id or not plot_type:
        return JSONResponse(
            {"error": "Missing run_id or plot_type query parameters"}, status_code=400
        )
    user = _effective_user(request)
    try:
        png_bytes = await asyncio.to_thread(generate_plot_png, run_id, plot_type, user=user)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if png_bytes is None:
        return JSONResponse(
            {"error": f"Artifact not found: run_id={run_id!r}"}, status_code=404
        )
    return Response(content=png_bytes, status_code=200, media_type="image/png")


async def dashboard_endpoint(request: Request) -> Response:
    """Serve a context-rich HTML dashboard for a given run_id."""
    from hangar.sdk.viz.viewer_server import generate_dashboard_html

    run_id = request.query_params.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id query parameter"}, status_code=400)
    user = _effective_user(request)
    try:
        html = await asyncio.to_thread(generate_dashboard_html, run_id, user=user)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if html is None:
        return JSONResponse(
            {"error": f"Artifact not found: run_id={run_id!r}"}, status_code=404
        )
    return HTMLResponse(html)


async def plot_types_endpoint(request: Request) -> Response:
    """Return JSON list of applicable plot types for a run."""
    from hangar.sdk.viz.viewer_server import get_plot_types_for_run

    run_id = request.query_params.get("run_id")
    if not run_id:
        return JSONResponse({"error": "Missing run_id query parameter"}, status_code=400)
    user = _effective_user(request)
    try:
        types = await asyncio.to_thread(get_plot_types_for_run, run_id, user=user)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    if types is None:
        return JSONResponse(
            {"error": f"Artifact not found: run_id={run_id!r}"}, status_code=404
        )
    return JSONResponse(types)


# ---------------------------------------------------------------------------
# OIDC-specific route handlers (login, callback, logout)
# ---------------------------------------------------------------------------

def _build_oidc_routes(config):
    """Return Route objects for the OIDC login/callback/logout endpoints."""
    from hangar.sdk.viz.viewer_auth import handle_callback, handle_logout, login_redirect

    async def login_endpoint(request: Request) -> Response:
        return login_redirect(request, config)

    async def callback_endpoint(request: Request) -> Response:
        return await handle_callback(request, config)

    async def logout_endpoint(request: Request) -> Response:
        return await handle_logout(request, config)

    return [
        Route("/viewer/login", login_endpoint),
        Route("/viewer/callback", callback_endpoint),
        Route("/viewer/logout", logout_endpoint),
    ]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _wrap_handlers(decorator):
    """Apply *decorator* to every content-serving handler and return a route list."""
    return [
        Route("/viewer", decorator(viewer_html)),
        Route("/viewer/", decorator(viewer_html)),
        Route("/sessions", decorator(sessions_endpoint)),
        Route("/graph", decorator(graph_endpoint)),
        Route("/plot", decorator(plot_endpoint)),
        Route("/plot_types", decorator(plot_types_endpoint)),
        Route("/dashboard", decorator(dashboard_endpoint)),
        Route("/dashboard/", decorator(dashboard_endpoint)),
    ]


def build_viewer_app() -> tuple[Starlette | None, str]:
    """Build and return ``(viewer_app, auth_mode)`` or ``(None, "")``.

    Auth mode priority:
      1. OIDC (if ``OIDC_ISSUER_URL`` + ``HANGAR_VIEWER_OIDC_CLIENT_SECRET`` set)
      2. Basic Auth (if ``HANGAR_VIEWER_USER`` + ``HANGAR_VIEWER_PASSWORD`` set)
      3. Disabled (viewer not mounted)

    Returns
    -------
    tuple
        ``(Starlette app, "oidc"|"basic")`` on success, or ``(None, "")``
        when the viewer is disabled.
    """
    from hangar.sdk.viz.viewer_auth import build_viewer_oidc_config, require_viewer_oidc

    oidc_config = build_viewer_oidc_config()

    if oidc_config is not None:
        # --- OIDC mode ---
        oidc_decorator = require_viewer_oidc(oidc_config)
        routes = _wrap_handlers(oidc_decorator) + _build_oidc_routes(oidc_config)

        resource_server_url = os.environ.get(
            "RESOURCE_SERVER_URL", "http://localhost:8000"
        )
        https_only = resource_server_url.startswith("https")

        from starlette.middleware.sessions import SessionMiddleware

        app = Starlette(
            routes=routes,
            middleware=[
                Middleware(
                    SessionMiddleware,
                    secret_key=oidc_config.session_secret,
                    session_cookie="hangar_viewer_session",
                    same_site="lax",
                    https_only=https_only,
                    max_age=86400,  # 24 hours
                ),
                Middleware(
                    CORSMiddleware,
                    allow_origins=[resource_server_url.rstrip("/")],
                    allow_methods=["GET"],
                    allow_credentials=True,
                ),
            ],
        )
        # Stash config on app state for use by on_startup handler.
        app.state.oidc_config = oidc_config
        return app, "oidc"

    # --- Basic Auth fallback ---
    from hangar.sdk.env import _hangar_env

    viewer_user = _hangar_env("HANGAR_VIEWER_USER", "OAS_VIEWER_USER")
    viewer_password = _hangar_env("HANGAR_VIEWER_PASSWORD", "OAS_VIEWER_PASSWORD")

    if not viewer_user or not viewer_password:
        logger.warning(
            "Set HANGAR_VIEWER_OIDC_CLIENT_SECRET (for OIDC) or "
            "HANGAR_VIEWER_USER + HANGAR_VIEWER_PASSWORD (for Basic Auth) "
            "to enable the provenance viewer on the HTTP transport."
        )
        return None, ""

    routes = _wrap_handlers(_require_basic_auth)

    app = Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET"],
                allow_headers=["Authorization"],
            ),
        ],
    )
    app.state.viewer_user = viewer_user
    app.state.viewer_password = viewer_password
    return app, "basic"


# Paths the viewer app handles — used by the fallback dispatcher.
_VIEWER_PATHS = frozenset({
    "/viewer", "/viewer/",
    "/viewer/login", "/viewer/callback", "/viewer/logout",
    "/sessions", "/graph", "/plot", "/plot_types",
    "/dashboard", "/dashboard/",
})


def make_fallback_app(viewer_app: Starlette, fallback_app) -> Starlette:
    """Compose *viewer_app* with a fallback ASGI app (typically the MCP app).

    Requests whose path matches a viewer route go to *viewer_app*; everything
    else is forwarded to *fallback_app*.  CORS preflight (OPTIONS) for viewer
    paths is also handled by the viewer app.
    """

    async def dispatcher(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path in _VIEWER_PATHS:
                await viewer_app(scope, receive, send)
                return
        await fallback_app(scope, receive, send)

    # Return a thin wrapper that looks like an ASGI app
    return dispatcher  # type: ignore[return-value]
