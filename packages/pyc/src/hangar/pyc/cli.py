"""pyCycle CLI registry -- builds the tool registry for the hangar CLI framework."""

from __future__ import annotations

from typing import Callable


def build_pyc_registry() -> dict[str, Callable]:
    """Import pyCycle tool functions and build name -> function map."""
    from hangar.pyc import server  # noqa: F401
    from hangar.pyc.tools import session as _session_tools
    from hangar.sdk.provenance.db import init_db as _prov_init_db

    _prov_init_db()

    tool_names = [
        "create_engine",
        "run_design_point",
        "run_off_design",
        "reset",
        "list_artifacts",
        "get_artifact",
        "get_artifact_summary",
        "delete_artifact",
        "get_run",
        "pin_run",
        "unpin_run",
        "get_last_logs",
        "configure_session",
        "set_requirements",
        "visualize",
    ]

    registry: dict[str, Callable] = {}
    for name in tool_names:
        fn = getattr(server, name, None)
        if fn is not None:
            registry[name] = fn

    registry["start_session"] = _session_tools.start_session
    registry["log_decision"] = _session_tools.log_decision
    registry["export_session_graph"] = _session_tools.export_session_graph

    return registry


def main() -> None:
    """pyCycle CLI entry point."""
    from hangar.sdk.cli.runner import set_registry_builder
    from hangar.sdk.cli.main import main as _cli_main

    set_registry_builder(build_pyc_registry)
    _cli_main(
        prog="pyc-cli",
        description="pyCycle CLI -- run cycle analysis tools from the command line.",
    )
