"""FastMCP server for hangar-omd.

Exposes plan validation, assembly, execution, results, and provenance
as MCP tools for AI agent workflows. Each tool calls the same implementation
functions as the CLI.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP

from hangar.sdk.provenance.middleware import capture_tool

mcp = FastMCP(
    "omd",
    instructions=(
        "MDAO analysis plan server. Materializes YAML analysis plans into "
        "OpenMDAO problems, runs them, and records results with provenance.\n\n"
        "WORKFLOW:\n"
        "  1. assemble -- merge modular YAML plan directory into canonical plan\n"
        "  2. validate_plan -- check plan against schema + semantic preflight\n"
        "  3. run_analysis -- materialize and execute the plan\n"
        "  4. get_results -- query results from the analysis DB\n"
        "  5. get_provenance -- view the plan's provenance DAG\n"
        "  6. export_plan -- generate a standalone Python script"
    ),
)


@mcp.tool()
@capture_tool
async def validate_plan(
    plan_path: Annotated[str, "Path to plan YAML file"],
    semantic: Annotated[bool, "Also run semantic checks (component types, DV/constraint name resolution)"] = True,
) -> dict:
    """Validate an analysis plan YAML against the schema and semantic checks."""
    from hangar.omd.plan_schema import load_and_validate

    plan, errors = load_and_validate(Path(plan_path))
    if errors:
        return {"valid": False, "errors": errors}

    if semantic and plan is not None:
        from hangar.omd.plan_validate import validate_plan_semantic
        from hangar.omd.registry import list_factories

        findings = validate_plan_semantic(plan, registry_types=set(list_factories()))
        if findings:
            return {
                "valid": False,
                "errors": [
                    {
                        "path": f.path,
                        "message": f.message,
                        "suggestions": f.suggestions,
                    }
                    for f in findings
                ],
            }

    return {"valid": True, "plan_id": plan.get("metadata", {}).get("id")}


@mcp.tool()
@capture_tool
async def assemble_plan(
    plan_dir: Annotated[str, "Path to plan directory with modular YAML files"],
    output: Annotated[str | None, "Output path for assembled plan"] = None,
) -> dict:
    """Assemble modular YAML files into a canonical plan."""
    from hangar.omd.assemble import assemble_plan as _assemble

    out = Path(output) if output else None
    return _assemble(Path(plan_dir), output=out)


@mcp.tool()
@capture_tool
async def run_analysis(
    plan_path: Annotated[str, "Path to assembled plan YAML"],
    mode: Annotated[str, "Execution mode: analysis or optimize"] = "analysis",
    recording_level: Annotated[str, "Recording level: minimal, driver, solver, full"] = "driver",
) -> dict:
    """Materialize and run an analysis plan."""
    from hangar.omd.run import run_plan

    return run_plan(Path(plan_path), mode=mode, recording_level=recording_level)


@mcp.tool()
@capture_tool
async def get_results(
    run_id: Annotated[str, "Run entity ID"],
    summary: Annotated[bool, "Return summary only"] = False,
) -> dict:
    """Query results for a completed run."""
    from hangar.omd.results import get_results as _get_results

    return _get_results(run_id, summary=summary)


@mcp.tool()
@capture_tool
async def get_provenance(
    plan_id: Annotated[str, "Plan identifier"],
    format: Annotated[str, "Output format: text or json"] = "text",
) -> dict:
    """View provenance for a plan."""
    from hangar.omd.provenance import provenance_timeline
    from hangar.omd.db import query_provenance_dag, init_analysis_db

    init_analysis_db()

    if format == "json":
        return query_provenance_dag(plan_id)
    else:
        text = provenance_timeline(plan_id)
        return {"timeline": text}


@mcp.tool()
@capture_tool
async def export_plan(
    plan_path: Annotated[str, "Path to assembled plan YAML"],
    output: Annotated[str, "Output Python script path"],
) -> dict:
    """Export a plan to a standalone Python script."""
    from hangar.omd.export import export_plan_to_script

    export_plan_to_script(Path(plan_path), Path(output))
    return {"exported": True, "output_path": output}


def main() -> None:
    """Entry point for omd-server."""
    parser = argparse.ArgumentParser(description="hangar-omd MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    args = parser.parse_args()

    from hangar.sdk.provenance.db import init_db as _prov_init_db
    _prov_init_db()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse")
