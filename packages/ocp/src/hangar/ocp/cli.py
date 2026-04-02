"""OCP CLI entry point using the SDK CLI framework."""

from __future__ import annotations

from typing import Callable


def build_ocp_registry() -> dict[str, Callable]:
    """Discover and return all OCP tools for the CLI."""
    from hangar.sdk.provenance.db import init_db as _prov_init_db
    _prov_init_db()

    from hangar.ocp.tools.aircraft import (
        define_aircraft,
        list_aircraft_templates,
        load_aircraft_template,
    )
    from hangar.ocp.tools.propulsion import set_propulsion_architecture
    from hangar.ocp.tools.mission import configure_mission, run_mission_analysis
    from hangar.ocp.tools.sweep import run_parameter_sweep
    from hangar.ocp.tools.optimization import run_optimization
    from hangar.ocp.tools.session import (
        configure_session,
        delete_artifact,
        export_session_graph,
        get_artifact,
        get_artifact_summary,
        get_detailed_results,
        get_last_logs,
        get_run,
        link_cross_tool_result,
        list_artifacts,
        log_decision,
        pin_run,
        reset,
        set_requirements,
        start_session,
        unpin_run,
        visualize,
    )

    return {
        "list_aircraft_templates": list_aircraft_templates,
        "load_aircraft_template": load_aircraft_template,
        "define_aircraft": define_aircraft,
        "set_propulsion_architecture": set_propulsion_architecture,
        "configure_mission": configure_mission,
        "run_mission_analysis": run_mission_analysis,
        "run_parameter_sweep": run_parameter_sweep,
        "run_optimization": run_optimization,
        "start_session": start_session,
        "log_decision": log_decision,
        "link_cross_tool_result": link_cross_tool_result,
        "export_session_graph": export_session_graph,
        "configure_session": configure_session,
        "set_requirements": set_requirements,
        "reset": reset,
        "list_artifacts": list_artifacts,
        "get_artifact": get_artifact,
        "get_artifact_summary": get_artifact_summary,
        "delete_artifact": delete_artifact,
        "get_run": get_run,
        "pin_run": pin_run,
        "unpin_run": unpin_run,
        "get_detailed_results": get_detailed_results,
        "get_last_logs": get_last_logs,
        "visualize": visualize,
    }


def main():
    """CLI entry point."""
    from hangar.sdk.cli.runner import set_registry_builder, set_setup_tools
    from hangar.sdk.cli.main import main as _cli_main

    set_registry_builder(build_ocp_registry)
    set_setup_tools([
        "load_aircraft_template",
        "define_aircraft",
        "set_propulsion_architecture",
        "configure_mission",
    ])
    def _start_viewer(port: int = 7654, db: str | None = None):
        from hangar.sdk.viz.viewer_server import start_viewer_server
        start_viewer_server(port=port, db_path=db)

    _cli_main(
        prog="ocp-cli",
        description="OpenConcept CLI -- run conceptual design tools from the command line.",
        viewer_callback=_start_viewer,
    )
