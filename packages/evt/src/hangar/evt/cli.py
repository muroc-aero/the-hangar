"""evt CLI registry -- builds the tool registry for the hangar CLI framework."""

from __future__ import annotations

from typing import Callable


def build_evt_registry() -> dict[str, Callable]:
    """Import evt tool functions and build name -> function map."""
    from hangar.evt import server  # noqa: F401
    from hangar.evt.tools import session as _session_tools
    from hangar.sdk.provenance.db import init_db as _prov_init_db

    _prov_init_db()

    tool_names = [
        "list_vehicle_templates",
        "load_vehicle_template",
        "define_vehicle",
        "set_propulsion",
        "set_power",
        "set_environment",
        "configure_mission",
        "run_mission_analysis",
        "run_sizing",
        "run_parameter_sweep",
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
    """evt CLI entry point."""
    from hangar.sdk.cli.runner import set_registry_builder, set_setup_tools
    from hangar.sdk.cli.main import main as _cli_main, viewer_command

    set_registry_builder(build_evt_registry)
    # Tools that establish the working config before an analysis can run.
    set_setup_tools([
        "load_vehicle_template",
        "define_vehicle",
        "set_propulsion",
        "set_power",
        "set_environment",
        "configure_mission",
    ])

    _cli_main(
        prog="evt-cli",
        description="evt CLI -- run eVTOL sizing and mission analysis from the command line.",
        viewer_callback=viewer_command,
    )
