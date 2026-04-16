"""Plotting package for omd analysis results.

Provides factory-aware plot generation. Each component type can
register a plot provider (dict of plot type names to callables).
Generic plots (convergence, DV evolution) work for any OpenMDAO problem.

Backward compatibility: all plot functions can be imported directly
from this package (e.g., ``from hangar.omd.plotting import plot_planform``).
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from hangar.omd.plotting._common import (  # noqa: F401 -- re-export
    detect_surface_name,
    find_outputs,
    find_first_output,
    get_reader_and_final_case,
    get_span_eta,
    mirror_spanwise,
    compute_elliptical_lift,
)
from hangar.omd.plotting.generic import (  # noqa: F401 -- re-export
    plot_convergence,
    plot_dv_evolution,
    GENERIC_PLOTS,
)
from hangar.omd.plotting.oas import (  # noqa: F401 -- re-export
    plot_planform,
    plot_lift_distribution,
    plot_structural_deformation,
    plot_twist,
    plot_thickness,
    plot_vonmises,
    plot_skin_spar,
    plot_t_over_c,
    plot_mesh_3d,
    OAS_AERO_PLOTS,
    OAS_AEROSTRUCT_PLOTS,
)

logger = logging.getLogger(__name__)

# Backward-compatible aliases for private helpers
_find_outputs = find_outputs
_find_first_output = find_first_output
_get_reader_and_final_case = get_reader_and_final_case

# Legacy PLOT_TYPES dict (all OAS + generic merged)
PLOT_TYPES = {**GENERIC_PLOTS, **OAS_AEROSTRUCT_PLOTS}


def generate_plots(
    recorder_path: Path,
    plot_types: list[str] | None = None,
    surface_name: str | None = None,
    output_dir: Path | None = None,
    component_type: str | None = None,
    component_types: dict[str, str] | None = None,
    slot_providers: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Generate one or more plot types and save as PNG files.

    Uses the factory registry to discover applicable plot types for
    the given component type. Falls back to all registered types if
    component type is unknown.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        plot_types: List of plot type names, or None for all applicable.
        surface_name: Surface name (auto-detected if None).
        output_dir: Directory to save PNGs. Uses current dir if None.
        component_type: Component type string (e.g., "oas/AerostructPoint").
            Used to select the right plot provider. If None, tries all.
        component_types: Dict mapping component_id to type string for
            composite problems. When provided with multiple types, plots
            from each component type are generated with prefixed filenames.
        slot_providers: Dict mapping slot names to provider names
            (e.g. {"drag": "oas/vlm"}). Used to merge slot-specific
            plot providers into the available set.

    Returns:
        Dict mapping plot type to saved file path.
    """
    from hangar.omd.registry import (
        get_plot_provider, get_plot_provider_with_slots, get_all_plot_providers,
    )

    # Track which plots come from which component (for filename prefixing)
    _plot_source: dict[str, str] = {}  # plot_name -> component_id

    # Get available plots for this component type
    if component_types and len(component_types) > 1:
        # Composite: merge providers from all component types
        available: dict = {}
        for comp_id, ctype in component_types.items():
            provider = get_plot_provider(ctype)
            for pname, pfunc in provider.items():
                if pname not in available:
                    available[pname] = pfunc
                    # Generic plots get no prefix
                    if pname not in _GENERIC_PLOTS:
                        _plot_source[pname] = comp_id
    elif component_type:
        available = get_plot_provider_with_slots(component_type, slot_providers)
    else:
        available = get_all_plot_providers()

    if plot_types is None:
        plot_types = list(available.keys())

    if output_dir is None:
        output_dir = Path(".")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract run_id from recorder filename for plot subtitles
    run_id = recorder_path.stem  # e.g. "run-20260405T110441-53360153"

    saved: dict[str, Path] = {}

    for ptype in plot_types:
        # N2 is special: copy pre-generated HTML instead of rendering matplotlib
        if ptype == "n2":
            try:
                n2_path = _resolve_n2(run_id, output_dir)
                if n2_path:
                    saved["n2"] = n2_path
            except Exception as exc:
                logger.warning("Skipping n2: %s", exc)
            continue

        func = available.get(ptype)
        if func is None:
            logger.warning("Unknown plot type: %s", ptype)
            continue

        try:
            kwargs: dict = {"run_id": run_id}
            # Pass surface_name if the function accepts it
            import inspect
            sig = inspect.signature(func)
            if "surface_name" in sig.parameters:
                kwargs["surface_name"] = surface_name
            # Only pass run_id if function accepts it
            if "run_id" not in sig.parameters and "kwargs" not in str(sig):
                kwargs.pop("run_id", None)

            fig = func(recorder_path, **kwargs)
            # Prefix type-specific plots with component_id for composites
            if ptype in _plot_source:
                out_path = output_dir / f"{_plot_source[ptype]}_{ptype}.png"
            else:
                out_path = output_dir / f"{ptype}.png"
            fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
            plt.close(fig)
            saved[ptype] = out_path
            logger.info("Saved %s plot to %s", ptype, out_path)
        except Exception as exc:
            logger.warning("Skipping %s plot: %s", ptype, exc)

    return saved


def _resolve_n2(run_id: str, output_dir: Path) -> Path | None:
    """Copy pre-generated N2 HTML to the plot output directory.

    The N2 HTML is generated during `omd-cli run` and stored at
    hangar_data/omd/n2/{run_id}.html. This copies it to the plot
    output directory for consistency.

    Returns the output path, or None if no N2 file exists.
    """
    import shutil
    from hangar.omd.db import n2_dir

    src = n2_dir() / f"{run_id}.html"
    if not src.exists():
        logger.warning("No N2 diagram found at %s (run predates N2 generation?)", src)
        return None

    dst = output_dir / "n2.html"
    shutil.copy2(src, dst)
    logger.info("N2 diagram copied to %s", dst)
    return dst
