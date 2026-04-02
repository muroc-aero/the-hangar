"""OAS CLI registry — builds the tool registry for the hangar CLI framework.

Migrated from: OpenAeroStruct/oas_mcp/cli_runner.py (OAS-specific parts)
"""

from __future__ import annotations

from typing import Callable


def build_oas_registry() -> dict[str, Callable]:
    """Import OAS tool functions and build name -> function map.

    This is passed to ``hangar.sdk.cli.runner.set_registry_builder``
    so the generic CLI framework can discover OAS tools.
    """
    # Deferred imports — avoids loading OpenAeroStruct until CLI is used.
    from hangar.oas import server  # noqa: F401  (side-effect: registers tools)
    from hangar.oas.tools import session as _session_tools
    from hangar.sdk.provenance.db import init_db as _prov_init_db

    # Ensure provenance DB is ready (MCP server does this at startup;
    # CLI mode needs it here since __main__ is never executed).
    _prov_init_db()

    # All tools that are registered on the server module
    tool_names = [
        "create_surface",
        "run_aero_analysis",
        "run_aerostruct_analysis",
        "compute_drag_polar",
        "compute_stability_derivatives",
        "run_optimization",
        "reset",
        "list_artifacts",
        "get_artifact",
        "get_artifact_summary",
        "delete_artifact",
        "get_run",
        "pin_run",
        "unpin_run",
        "get_detailed_results",
        "visualize",
        "get_n2_html",
        "get_last_logs",
        "configure_session",
        "set_requirements",
    ]

    registry: dict[str, Callable] = {}
    for name in tool_names:
        fn = getattr(server, name, None)
        if fn is not None:
            registry[name] = fn

    # Provenance tools
    registry["start_session"] = _session_tools.start_session
    registry["log_decision"] = _session_tools.log_decision
    registry["link_cross_tool_result"] = _session_tools.link_cross_tool_result
    registry["export_session_graph"] = _session_tools.export_session_graph

    return registry


def main() -> None:
    """OAS CLI entry point — wires the OAS registry into the generic CLI."""
    from hangar.sdk.cli.runner import set_registry_builder, set_setup_tools
    from hangar.sdk.cli.main import main as _cli_main

    set_registry_builder(build_oas_registry)
    set_setup_tools(["create_surface"])

    def _start_viewer(port: int = 7654, db: str | None = None):
        from hangar.sdk.viz.viewer_server import start_viewer_server
        start_viewer_server(port=port, db_path=db)

    _cli_main(
        prog="oas-cli",
        description="OpenAeroStruct CLI — run analysis tools from the command line.",
        viewer_callback=_start_viewer,
    )
