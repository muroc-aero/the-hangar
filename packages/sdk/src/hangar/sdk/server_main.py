"""Shared console-script entry point for the hangar MCP tool servers.

Every tool server's ``main()`` carried the same ~100 lines of argparse,
provenance seeding, stdio viewer banner, and HTTP transport assembly (and
only oas printed the no-auth warning). ``run_server_main`` is the single
copy; each package's ``main()`` calls it with its FastMCP instance and
identifiers.
"""

from __future__ import annotations

import os
import sys


def _warn_if_unauthenticated(host: str, port: int, tool: str) -> None:
    """Print a loud warning to stderr when HTTP transport runs without auth."""
    from hangar.sdk.auth.oidc import _env as _auth_env

    issuer_url = _auth_env("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL")

    if issuer_url:
        print(
            f"\n  {tool.upper()} MCP — HTTP transport  |  auth: OIDC ({issuer_url})\n",
            file=sys.stderr,
        )
        return

    url = f"http://{host}:{port}/mcp"
    client_id = f"OIDC_CLIENT_ID={tool}-mcp"
    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════════╗\n"
        "║                  ⚠  NO AUTHENTICATION ENABLED  ⚠                ║\n"
        "╠══════════════════════════════════════════════════════════════════╣\n"
        "║  The server is accepting ALL requests on:                        ║\n"
        f"║    {url:<60}  ║\n"
        "║                                                                  ║\n"
        "║  Anyone who can reach this port can call every tool, run         ║\n"
        "║  analyses, and read/delete all stored artifacts.                  ║\n"
        "║                                                                  ║\n"
        "║  This is fine for local development.  For any deployment that    ║\n"
        "║  is reachable over a network, set:                               ║\n"
        "║                                                                  ║\n"
        "║    OIDC_ISSUER_URL=https://<provider>/...                        ║\n"
        f"║    {client_id:<60}  ║\n"
        "║    OIDC_CLIENT_SECRET=<secret>                                    ║\n"
        "║                                                                  ║\n"
        "║  Works with any OIDC provider (Authentik, Keycloak, Auth0, …).  ║\n"
        "╚══════════════════════════════════════════════════════════════════╝\n",
        file=sys.stderr,
    )


def run_server_main(
    mcp,
    *,
    tool: str,
    env_prefix: str,
    default_port: int,
    description: str,
    banner_title: str | None = None,
) -> None:
    """Run a hangar MCP server: argparse, provenance seeding, transport.

    Parameters
    ----------
    mcp:
        The package's FastMCP instance.
    tool:
        Short tool name (``"oas"``, ``"ocp"``, ``"pyc"``) used for provenance
        attribution, the /healthz payload, and the no-auth warning.
    env_prefix:
        Env-var prefix for transport settings (``{PREFIX}_TRANSPORT``,
        ``{PREFIX}_HOST``, ``{PREFIX}_PORT``).
    default_port:
        Native default HTTP port (oas=8000, ocp=8001, pyc=8002).
    description:
        argparse description shown in ``--help``.
    banner_title:
        Viewer banner label; defaults to ``tool.upper()``.
    """
    import argparse

    from hangar.sdk.provenance.db import (
        init_db as _prov_init_db,
        record_session as _prov_record_session,
    )

    title = banner_title or tool.upper()

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get(f"{env_prefix}_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get(f"{env_prefix}_HOST", "127.0.0.1"),
        help="Bind host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get(f"{env_prefix}_PORT", str(default_port))),
        help=f"Bind port for HTTP transport (default: {default_port})",
    )
    args = parser.parse_args()

    # --- Provenance setup ---
    import uuid

    from hangar.sdk.provenance.middleware import set_default_session_id, set_tool_name

    set_tool_name(tool)
    _prov_init_db()
    auto_sid = f"auto-{uuid.uuid4().hex[:8]}"
    # Seed the per-process fallback so tool calls from users who never call
    # start_session land somewhere. Per-user active sessions (start_session)
    # override this; the ContextVar stays reserved for test isolation.
    set_default_session_id(auto_sid)
    _prov_record_session(auto_sid, notes=f"Auto-created on {title} server startup")

    if args.transport == "stdio":
        # Legacy daemon thread viewer for local dev (localhost only, no auth)
        try:
            from hangar.sdk.viz.viewer_server import start_viewer_server

            prov_port = start_viewer_server()
            if prov_port:
                sep = "─" * 54
                print(f"\n{sep}", file=sys.stderr)
                print(f"  {title} Provenance Viewer", file=sys.stderr)
                print(sep, file=sys.stderr)
                print(f"  Viewer    http://localhost:{prov_port}/viewer", file=sys.stderr)
                print("            Interactive DAG — load any session from the", file=sys.stderr)
                print("            drop-down or drop an exported JSON file.", file=sys.stderr)
                print(f"  Sessions  http://localhost:{prov_port}/sessions", file=sys.stderr)
                print("            JSON list of all recorded provenance sessions.", file=sys.stderr)
                print(f"  Plot API  http://localhost:{prov_port}/plot?run_id=<id>&plot_type=<type>", file=sys.stderr)
                print("            Render a saved analysis run as a PNG image.", file=sys.stderr)
                print(sep + "\n", file=sys.stderr)
        except Exception:
            pass
        mcp.run()
        return

    # --- HTTP transport ---
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "uvicorn is required for HTTP transport. "
            "Install it with: pip install 'hangar-sdk[http]'"
        ) from exc

    from hangar.sdk.viz.viewer_routes import build_viewer_app

    _warn_if_unauthenticated(args.host, args.port, tool)
    mcp_asgi = mcp.streamable_http_app()
    viewer_app, auth_mode = build_viewer_app()

    if viewer_app is not None:
        # Run OIDC discovery before starting the server (if OIDC mode).
        if auth_mode == "oidc":
            import asyncio

            from hangar.sdk.viz.viewer_auth import discover_oidc_endpoints

            asyncio.run(discover_oidc_endpoints(viewer_app.state.oidc_config))

        # Compose viewer + MCP: viewer handles its known paths,
        # everything else falls through to the MCP ASGI app.
        from hangar.sdk.viz.viewer_routes import make_fallback_app

        app = make_fallback_app(viewer_app, mcp_asgi)
        sep = "─" * 54
        print(f"\n{sep}", file=sys.stderr)
        print(f"  {title} Provenance Viewer (HTTP transport)", file=sys.stderr)
        print(sep, file=sys.stderr)
        print(f"  Viewer    http://{args.host}:{args.port}/viewer", file=sys.stderr)
        if auth_mode == "oidc":
            print(f"            Protected by OIDC ({viewer_app.state.oidc_config.issuer_url})", file=sys.stderr)
        else:
            print("            Protected by Basic Auth", file=sys.stderr)
        print(sep + "\n", file=sys.stderr)
    else:
        app = mcp_asgi

    # Add unauthenticated /healthz endpoint
    from hangar.sdk.health import add_healthz

    app = add_healthz(app, server_name=tool)

    uvicorn.run(app, host=args.host, port=args.port)
