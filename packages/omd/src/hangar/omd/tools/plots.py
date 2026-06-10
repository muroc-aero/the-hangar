"""Plot generation and view-URL tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from hangar.sdk.errors import UserInputError

from hangar.omd.tools._helpers import view_urls


def _run_plot_context(run_id: str) -> tuple[str | None, dict | None, dict | None]:
    """Return (component_type, component_types, slot_providers) for a run."""
    from hangar.omd.db import init_analysis_db, query_entity

    init_analysis_db()
    entity = query_entity(run_id)
    if entity is None:
        raise UserInputError(f"Run not found: {run_id}")
    meta: dict = {}
    try:
        meta = json.loads(entity.get("metadata") or "{}")
    except Exception:
        pass
    return (
        meta.get("component_type"),
        meta.get("component_types"),
        meta.get("slot_providers"),
    )


async def list_plot_types(
    run_id: Annotated[str, "Run entity ID returned by run_plan"],
) -> dict:
    """List the plot types available for a completed run's component type(s)."""
    from hangar.omd.registry import get_plot_provider, get_plot_provider_with_slots

    def _list() -> dict:
        component_type, component_types, slot_providers = _run_plot_context(run_id)
        if component_types and len(component_types) > 1:
            per_component = {
                comp_id: sorted(get_plot_provider(ctype).keys())
                for comp_id, ctype in component_types.items()
            }
            return {
                "run_id": run_id,
                "component_types": component_types,
                "plot_types": per_component,
            }
        provider = get_plot_provider_with_slots(component_type, slot_providers)
        return {
            "run_id": run_id,
            "component_type": component_type,
            "plot_types": sorted(provider.keys()),
        }

    return await asyncio.to_thread(_list)


async def generate_plots(
    run_id: Annotated[str, "Run entity ID returned by run_plan"],
    plot_type: Annotated[str, "Plot type to generate, or 'all' for every applicable type"] = "all",
    surface: Annotated[str | None, "Surface name filter (multi-surface OAS plans)"] = None,
) -> dict:
    """Generate analysis plots from a completed run's recorder data.

    PNGs land in the run's plots directory; ``urls.plots`` lists them in the
    browser and ``urls`` carries per-plot image links when a viewer is
    reachable. Use list_plot_types to see what applies to this run.
    """
    from hangar.omd.db import omd_data_root, recordings_dir
    from hangar.omd.plotting import generate_plots as _generate_plots

    def _generate() -> dict:
        component_type, component_types, slot_providers = _run_plot_context(run_id)
        rec_path = recordings_dir() / f"{run_id}.sql"
        if not rec_path.exists():
            raise UserInputError(f"Recorder not found for run {run_id!r}: {rec_path}")

        out_dir = omd_data_root() / "plots" / run_id
        saved = _generate_plots(
            rec_path,
            plot_types=None if plot_type == "all" else [plot_type],
            surface_name=surface,
            output_dir=out_dir,
            component_type=component_type,
            component_types=component_types,
            slot_providers=slot_providers,
        )
        urls = view_urls(run_id=run_id)
        plots_base = urls.get("plots")
        result = {
            "run_id": run_id,
            "output_dir": str(out_dir),
            "saved": {ptype: str(path) for ptype, path in (saved or {}).items()},
            "urls": urls,
        }
        if plots_base and saved:
            base = plots_base.split("/omd-plots")[0]
            result["plot_urls"] = {
                ptype: f"{base}/omd-plot-img?run_id={run_id}&name={Path(path).name}"
                for ptype, path in saved.items()
            }
        return result

    return await asyncio.to_thread(_generate)


async def get_view_urls(
    run_id: Annotated[str | None, "Run entity ID (enables run-scoped views)"] = None,
    plan_id: Annotated[str | None, "Plan identifier (enables plan-scoped views)"] = None,
) -> dict:
    """Return clickable URLs for every reachable view.

    Includes the SDK provenance viewer, the omd plan/run views (provenance
    DAG, plan detail, problem DAG, plots, N2 diagram), and the range-safety
    dashboard when one is running. Empty ``urls`` means no viewer is
    reachable in this deployment.
    """
    return {"run_id": run_id, "plan_id": plan_id, "urls": view_urls(run_id, plan_id)}
