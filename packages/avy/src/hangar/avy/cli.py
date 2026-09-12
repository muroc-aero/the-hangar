"""Aviary CLI registry -- builds the tool registry for the hangar CLI framework."""

from __future__ import annotations

from typing import Callable


def build_avy_registry() -> dict[str, Callable]:
    """Import Aviary tool functions and build name -> function map."""
    from hangar.avy import server  # noqa: F401
    from hangar.avy.tools import session as _session_tools
    from hangar.sdk.provenance.db import init_db as _prov_init_db

    _prov_init_db()

    tool_names = [
        "list_aircraft_templates",
        "load_aircraft_template",
        "define_aircraft",
        "configure_mission",
        "list_external_subsystems",
        "add_external_subsystem",
        "run_sizing",
        "run_off_design",
        "run_payload_range",
        "reset",
        "list_artifacts",
        "get_artifact",
        "get_artifact_summary",
        "delete_artifact",
        "get_run",
        "pin_run",
        "unpin_run",
        "get_detailed_results",
        "get_last_logs",
        "configure_session",
        "set_requirements",
        "record_conclusion",
        "visualize",
    ]

    registry: dict[str, Callable] = {}
    for name in tool_names:
        fn = getattr(server, name, None)
        if fn is not None:
            registry[name] = fn

    registry["start_session"] = _session_tools.start_session
    registry["log_decision"] = _session_tools.log_decision
    registry["link_cross_tool_result"] = _session_tools.link_cross_tool_result
    registry["export_session_graph"] = _session_tools.export_session_graph

    return registry


def main() -> None:
    """Aviary CLI entry point."""
    from hangar.sdk.cli.runner import set_registry_builder, set_setup_tools
    from hangar.sdk.cli.main import main as _cli_main, viewer_command

    set_registry_builder(build_avy_registry)
    set_setup_tools(["load_aircraft_template"])

    _cli_main(
        prog="avy-cli",
        description="Aviary CLI -- run aircraft sizing tools from the command line.",
        viewer_callback=viewer_command,
    )
