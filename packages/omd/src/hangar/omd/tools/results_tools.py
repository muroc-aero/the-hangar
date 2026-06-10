"""Results, summary, conclusion, provenance, and export tools."""

from __future__ import annotations

import asyncio
from typing import Annotated

from hangar.sdk.errors import UserInputError

from hangar.omd.tools._helpers import (
    load_plan_for_run,
    resolve_plan_path,
    view_urls,
    workspace_write_target,
)


async def get_results(
    run_id: Annotated[str, "Run entity ID returned by run_plan"],
    variables: Annotated[list[str] | None, "Specific variable names to return (None = all)"] = None,
    summary: Annotated[bool, "Return only the final case with condensed output"] = False,
) -> dict:
    """Query recorded results for a completed run from the analysis DB."""
    from hangar.omd.results import get_results as _get_results

    result = await asyncio.to_thread(
        _get_results, run_id, variables=variables, summary=summary
    )
    if isinstance(result, dict) and "error" in result:
        raise UserInputError(str(result["error"]))
    return result


async def get_run_summary(
    run_id: Annotated[str, "Run entity ID returned by run_plan"],
    regenerate_plots: Annotated[bool, "Generate missing plots before rendering the summary"] = True,
) -> dict:
    """Render the one-page HTML run summary (plots, DVs, constraints, N2 link).

    Returns ``{run_id, summary_path, urls}``; ``urls.problem_dag`` is the
    interactive view of the same run when a viewer is reachable.
    """
    from hangar.omd.cli.summary import generate_summary

    out_path = await asyncio.to_thread(
        generate_summary, run_id, ensure_plots=regenerate_plots
    )
    return {
        "run_id": run_id,
        "summary_path": str(out_path),
        "urls": view_urls(run_id=run_id),
    }


async def record_conclusion(
    run_id: Annotated[str, "Run entity ID the conclusion is about"],
    narrative: Annotated[str, "Short narrative: what these results mean for the requirements"] = "",
    plan_path: Annotated[str | None, "Plan YAML (default: the run's plan from the plan store)"] = None,
) -> dict:
    """Conclude a study: judge the run against the plan's acceptance criteria.

    Auto-derives a per-requirement verdict from the run's final results,
    writes a conclusion entity with satisfies/violates edges, and returns
    ``{conclusion_id, verdict, requirements, urls}``. This populates the
    Concluding stage in the range-safety dashboard.
    """
    from hangar.omd.db import init_analysis_db
    from hangar.omd.run import record_conclusion as _record_conclusion

    await asyncio.to_thread(init_analysis_db)
    plan, plan_id = await asyncio.to_thread(load_plan_for_run, run_id, plan_path)
    result = await asyncio.to_thread(
        _record_conclusion, run_id, plan, plan_id, narrative=narrative
    )
    result["urls"] = view_urls(run_id=run_id, plan_id=plan_id)
    return result


async def get_provenance(
    plan_id: Annotated[str, "Plan identifier (metadata.id)"],
    format: Annotated[str, "Output format: 'text' (timeline) or 'json' (full DAG)"] = "text",
    diff_from: Annotated[int | None, "Compare plan versions: older version number"] = None,
    diff_to: Annotated[int | None, "Compare plan versions: newer version number"] = None,
) -> dict:
    """View the provenance for a plan: timeline, full DAG, or a version diff.

    Pass both ``diff_from`` and ``diff_to`` to compare two plan versions.
    Returns ``urls.plan_provenance`` for the interactive Cytoscape DAG.
    """
    from hangar.omd.db import init_analysis_db, query_provenance_dag
    from hangar.omd.provenance import provenance_diff, provenance_timeline

    await asyncio.to_thread(init_analysis_db)
    urls = view_urls(plan_id=plan_id)

    if (diff_from is None) != (diff_to is None):
        raise UserInputError("Pass both diff_from and diff_to, or neither.")
    if diff_from is not None:
        diff = await asyncio.to_thread(provenance_diff, plan_id, diff_from, diff_to)
        return {"plan_id": plan_id, "diff": diff, "urls": urls}

    if format == "json":
        dag = await asyncio.to_thread(query_provenance_dag, plan_id)
        return {"plan_id": plan_id, "dag": dag, "urls": urls}
    if format != "text":
        raise UserInputError(f"format must be 'text' or 'json' (got {format!r})")
    text = await asyncio.to_thread(provenance_timeline, plan_id)
    return {"plan_id": plan_id, "timeline": text, "urls": urls}


async def export_plan(
    plan_path: Annotated[str, "Path to assembled plan YAML"],
    output: Annotated[str | None, "Output .py path (default: <plan stem>_export.py in the workspace)"] = None,
) -> dict:
    """Export a plan to a standalone Python script (no omd dependency).

    Returns ``{exported, output_path, content}`` -- ``content`` is the full
    script text so MCP-only agents can read it without filesystem access.
    """
    from hangar.omd.export import export_plan_to_script

    src = resolve_plan_path(plan_path)
    if output:
        out_path = workspace_write_target(output)
    else:
        out_path = workspace_write_target(f"{src.stem}_export.py")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(export_plan_to_script, src, out_path)
    return {
        "exported": True,
        "output_path": str(out_path),
        "content": out_path.read_text(),
    }
