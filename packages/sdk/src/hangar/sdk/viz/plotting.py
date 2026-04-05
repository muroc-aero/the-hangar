"""Matplotlib PNG generation and plot framework.

Migrated from: OpenAeroStruct/oas_mcp/core/plotting.py
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mcp.server.fastmcp.utilities.types import Image


@dataclass
class N2Result:
    """Container for a generated N2 diagram saved to disk.

    ``metadata`` is a plain dict with file path, size, hash, and compressed
    viewer data — small enough to return as a single TextContent.
    ``file_path`` is the absolute path to the saved HTML file.
    """
    metadata: dict  # plot_type, format, file_path, size_bytes, image_hash, viewer_data_compressed
    file_path: str  # absolute path to the saved HTML file


@dataclass
class PlotResult:
    """Container for a generated plot and its metadata.

    ``image`` is an MCP Image object (FastMCP converts it to ImageContent).
    ``metadata`` is a plain dict suitable for TextContent serialisation so
    text-only MCP clients still receive structured plot information.
    """
    image: Image
    metadata: dict  # plot_type, run_id, format, width_px, height_px, image_hash, note

# Lazy matplotlib import — avoid importing at module load to keep startup fast.
_MPL_AVAILABLE: bool | None = None


def _require_mpl():
    """Import matplotlib with non-interactive backend; raise if unavailable."""
    global _MPL_AVAILABLE
    if _MPL_AVAILABLE is False:
        raise ImportError(
            "matplotlib is required for visualisation. "
            "Install it with: pip install matplotlib"
        )
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive, safe for server-side use
        import matplotlib.pyplot as plt
        _MPL_AVAILABLE = True
        return matplotlib, plt
    except ImportError:
        _MPL_AVAILABLE = False
        raise ImportError(
            "matplotlib is required for visualisation. "
            "Install it with: pip install matplotlib"
        )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLOT_TYPES = frozenset({
    "lift_distribution",
    "drag_polar",
    "stress_distribution",
    "convergence",
    "planform",
    "opt_history",
    "opt_dv_evolution",
    "opt_comparison",
    "n2",
    "deflection_profile",
    "weight_breakdown",
    "failure_heatmap",
    "twist_chord_overlay",
    "mesh_3d",
    "multipoint_comparison",
})

_FIG_WIDTH_IN = 6.0   # inches
_FIG_HEIGHT_IN = 3.6  # inches
_DPI = 150            # → 900 × 540 px

_FIG_3D_WIDTH_IN = 8.0    # inches → 1200 px at 150 DPI
_FIG_3D_HEIGHT_IN = 5.33  # inches → ~800 px at 150 DPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fig_to_response(
    fig, run_id: str, plot_type: str, save_dir: str | Path | None = None,
) -> PlotResult:
    """Convert a matplotlib Figure to a PlotResult (Image + metadata dict).

    Pixel dimensions are captured before closing the figure so they reflect
    the actual rendered size (bbox_inches="tight" can adjust the canvas).
    The SHA-256 hash in the metadata is used for client-side caching.

    If *save_dir* is given, the PNG is also persisted to
    ``{save_dir}/plots/{run_id}_{plot_type}.png`` and ``file_path`` is added
    to the metadata dict.
    """
    _, plt = _require_mpl()
    # Capture dimensions *before* savefig/close — tight bbox may change them
    width_px = round(fig.get_size_inches()[0] * _DPI)
    height_px = round(fig.get_size_inches()[1] * _DPI)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    sha = "sha256-" + hashlib.sha256(png_bytes).hexdigest()[:16]
    img = Image(data=png_bytes, format="png")
    metadata = {
        "plot_type": plot_type,
        "run_id": run_id,
        "format": "png",
        "width_px": width_px,
        "height_px": height_px,
        "image_hash": sha,
        "note": (
            "Image attached as ImageContent. "
            "If not visible, use get_detailed_results() for the underlying data."
        ),
    }

    # Persist PNG to disk when save_dir is provided
    if save_dir is not None:
        plots_dir = Path(save_dir) / "plots"
        plots_dir.mkdir(parents=True, exist_ok=True)
        file_path = plots_dir / f"{run_id}_{plot_type}.png"
        file_path.write_bytes(png_bytes)
        metadata["file_path"] = str(file_path.resolve())

    return PlotResult(image=img, metadata=metadata)


def _make_fig(run_id: str, title: str) -> tuple:
    """Create a standard-size figure with the given title."""
    _, plt = _require_mpl()
    fig, ax = plt.subplots(figsize=(_FIG_WIDTH_IN, _FIG_HEIGHT_IN))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.98)
    return fig, ax


def _make_fig_3d(run_id: str, title: str) -> tuple:
    """Create a wider figure with a 3D Axes3D subplot."""
    _, plt = _require_mpl()
    fig = plt.figure(figsize=(_FIG_3D_WIDTH_IN, _FIG_3D_HEIGHT_IN))
    ax = fig.add_subplot(111, projection="3d")
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.98)
    return fig, ax


def _find_sectional(results: dict) -> dict | None:
    """Find sectional data dict from results, handling nested and flat layouts."""
    sectional = results.get("sectional_data", {})
    if sectional:
        if "y_span_norm" in sectional:
            return sectional
        for sd in sectional.values():
            if isinstance(sd, dict) and "y_span_norm" in sd:
                return sd
    # Try per-surface sectional data
    for surf_res in results.get("surfaces", {}).values():
        sect = surf_res.get("sectional_data", {})
        if sect and "y_span_norm" in sect:
            return sect
    return None


# ---------------------------------------------------------------------------
# Plot: lift_distribution
# ---------------------------------------------------------------------------


def plot_lift_distribution(run_id: str, results: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot spanwise lift loading distribution with elliptical overlay.

    Primary data: ``sectional_data.lift_loading`` — force-per-unit-span
    normalised by dynamic pressure, matching the ``plot_wing.py`` reference.
    Also plots the ideal elliptical distribution for comparison.

    Falls back to ``Cl`` (sectional lift coefficient) if ``lift_loading``
    is not available (e.g. older artifacts), and to a per-surface bar chart
    if no sectional data exists at all.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Lift Distribution — {case_name}" if case_name else "Lift Distribution"
    fig, ax = _make_fig(run_id, title)

    # Find sectional data — may be at top level or nested by surface name
    sectional = results.get("sectional_data", {})
    surf_data = None
    if sectional:
        # Try top-level keys first
        if "y_span_norm" in sectional:
            surf_data = sectional
        else:
            # Nested by surface name
            for sd in sectional.values():
                if isinstance(sd, dict) and "y_span_norm" in sd:
                    surf_data = sd
                    break

    if surf_data:
        y = surf_data.get("y_span_norm")
        lift = surf_data.get("lift_loading")
        lift_ell = surf_data.get("lift_elliptical")
        Cl = surf_data.get("Cl")

        # Prefer lift_loading (matches plot_wing.py); fall back to Cl
        plot_data = lift if lift else Cl
        ylabel = "Normalised lift  l(y)/q  [m]" if lift else "Sectional Cl  [—]"

        if plot_data and y and (len(plot_data) == len(y) or len(plot_data) == len(y) - 1):
            if len(plot_data) == len(y) - 1:
                y_plot = [(y[i] + y[i + 1]) / 2.0 for i in range(len(plot_data))]
            else:
                y_plot = y
            ax.plot(y_plot, plot_data, "b-o", markersize=3, linewidth=1.5, label="lift")

            # Elliptical overlay (green dashed, matches plot_wing.py)
            if lift_ell and y and len(lift_ell) == len(y):
                ax.plot(y, lift_ell, "--", color="g", linewidth=1.5, label="elliptical")
                ax.legend(fontsize=7)

            ax.set_xlabel("Normalised spanwise station η = 2y/b  [—]   (0 = root, 1 = tip)")
            ax.set_ylabel(ylabel)
            ax.set_xlim(0, 1)
            d_min, d_max = min(plot_data), max(plot_data)
            ax.set_title(
                f"[{d_min:.3f}, {d_max:.3f}]", fontsize=8
            )
        else:
            _lift_fallback_bar(ax, results)
    else:
        _lift_fallback_bar(ax, results)

    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "lift_distribution", save_dir=save_dir)


def _lift_fallback_bar(ax, results: dict):
    """Draw a per-surface CL bar chart when sectional data is absent."""
    surfaces = results.get("surfaces", {})
    names = list(surfaces.keys())
    cls = [surfaces[n].get("CL", 0.0) for n in names]
    ax.bar(names, cls, color="steelblue", edgecolor="navy", linewidth=0.8)
    ax.set_xlabel("Surface")
    ax.set_ylabel("CL  [—]")
    ax.set_title("Per-surface CL (sectional data not available)", fontsize=8)


# ---------------------------------------------------------------------------
# Plot: drag_polar
# ---------------------------------------------------------------------------


def plot_drag_polar(run_id: str, results: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot CL vs CD and L/D vs alpha side-by-side."""
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Drag Polar — {case_name}" if case_name else "Drag Polar"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(_FIG_WIDTH_IN, _FIG_HEIGHT_IN))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.98)

    alphas = results.get("alpha_deg", [])
    CLs = results.get("CL", [])
    CDs = results.get("CD", [])
    LoDs = results.get("L_over_D", [])

    # Panel 1: CL vs CD (drag polar)
    ax1.plot(CDs, CLs, "b-o", markersize=3, linewidth=1.5)
    ax1.set_xlabel("CD  [—]")
    ax1.set_ylabel("CL  [—]")
    ax1.set_title("CL vs CD", fontsize=8)
    if CDs and CLs:
        ax1.set_title(
            f"CL ∈ [{min(CLs):.3f}, {max(CLs):.3f}], CD ∈ [{min(CDs):.4f}, {max(CDs):.4f}]",
            fontsize=7,
        )
    ax1.grid(True, alpha=0.3)

    # Highlight best L/D
    best = results.get("best_L_over_D", {})
    if best and best.get("CL") is not None and best.get("CD") is not None:
        ax1.plot(
            best["CD"], best["CL"], "r*", markersize=10,
            label=f"Best L/D = {best.get('L_over_D', '?'):.2f}",
            zorder=5,
        )
        ax1.legend(fontsize=7)

    # Panel 2: L/D vs alpha
    valid = [(a, ld) for a, ld in zip(alphas, LoDs) if ld is not None]
    if valid:
        a_vals, ld_vals = zip(*valid)
        ax2.plot(a_vals, ld_vals, "g-o", markersize=3, linewidth=1.5)
    ax2.set_xlabel("α  [deg]")
    ax2.set_ylabel("L/D  [—]")
    ax2.set_title("L/D vs α", fontsize=8)
    ax2.axhline(0, color="k", linewidth=0.5, linestyle="--")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "drag_polar", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: stress_distribution
# ---------------------------------------------------------------------------


def plot_stress_distribution(run_id: str, results: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot spanwise stress with failure reference line.

    Handles both isotropic (von Mises) and composite (Tsai-Wu SR) surfaces.
    Falls back to scalar metrics when per-element arrays are unavailable.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Stress Distribution — {case_name}" if case_name else "Stress Distribution"
    fig, ax = plt.subplots(1, 1, figsize=(_FIG_WIDTH_IN, _FIG_HEIGHT_IN))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.98)

    def _elem_y(y_nodes: list, n_elem: int) -> list | None:
        """Map nodal y_span_norm to element midpoints."""
        if len(y_nodes) == n_elem:
            return y_nodes
        if len(y_nodes) == n_elem + 1:
            return [(y_nodes[i] + y_nodes[i + 1]) / 2.0 for i in range(n_elem)]
        return None

    # Detect material models across surfaces
    has_composite = False
    has_isotropic = False
    for surf_res in results.get("surfaces", {}).values():
        sectional = surf_res.get("sectional_data", {})
        if sectional.get("material_model") == "composite":
            has_composite = True
        else:
            has_isotropic = True

    # Choose plot mode: pure isotropic, pure composite, or mixed (utilization ratio)
    mixed = has_composite and has_isotropic

    plotted = False
    max_ref = 0.0  # max reference line value for y-limit

    for surf_name, surf_res in results.get("surfaces", {}).items():
        sectional = surf_res.get("sectional_data", {})
        y_nodes = sectional.get("y_span_norm")
        mat_model = sectional.get("material_model", "isotropic")

        if mat_model == "composite":
            sr = sectional.get("tsaiwu_sr_max")
            sf = sectional.get("safety_factor", 2.5)

            if y_nodes and sr:
                y_sr = _elem_y(y_nodes, len(sr))
                if y_sr is not None:
                    if mixed:
                        # Plot as utilization ratio: SR * SF
                        vals = [s * sf for s in sr]
                        ax.plot(y_sr, vals, label=f"{surf_name} (composite)", linewidth=2)
                    else:
                        ax.plot(y_sr, sr, label=surf_name, linewidth=2)
                    plotted = True
            elif surf_res.get("max_tsaiwu_sr") is not None:
                val = surf_res["max_tsaiwu_sr"]
                if mixed:
                    val = val * sf
                ax.axhline(val, linestyle="--",
                           label=f"{surf_name} max SR={surf_res['max_tsaiwu_sr']:.4f}",
                           linewidth=1.5)
                plotted = True

            # Failure threshold
            if mixed:
                ref = 1.0  # utilization ratio threshold
            else:
                ref = 1.0 / sf  # SR failure threshold
            if ref > max_ref:
                ax.axhline(ref, color="r", linewidth=2, linestyle="--")
                max_ref = ref

        else:
            # Isotropic (von Mises)
            vm = sectional.get("vonmises_MPa")
            yield_mpa = sectional.get("yield_stress_MPa")
            sf = sectional.get("safety_factor", 1.0)

            if y_nodes and vm:
                y_vm = _elem_y(y_nodes, len(vm))
                if y_vm is not None:
                    if mixed:
                        # Normalize to utilization ratio: VM / allowable
                        allowable = yield_mpa / sf if yield_mpa else 1.0
                        vals = [v / allowable for v in vm]
                        ax.plot(y_vm, vals, label=f"{surf_name} (isotropic)", linewidth=2)
                    else:
                        ax.plot(y_vm, vm, label=surf_name, linewidth=2)
                    plotted = True
                else:
                    max_vm = surf_res.get("max_vonmises_Pa")
                    if max_vm is not None:
                        ax.axhline(max_vm / 1e6, linestyle="--",
                                   label=f"{surf_name} max={max_vm/1e6:.1f} MPa",
                                   linewidth=1.5)
                        plotted = True
            else:
                max_vm = surf_res.get("max_vonmises_Pa")
                if max_vm is not None:
                    ax.axhline(max_vm / 1e6, linestyle="--",
                               label=f"{surf_name} max={max_vm/1e6:.1f} MPa",
                               linewidth=1.5)
                    plotted = True

            # Allowable stress reference line
            if yield_mpa is not None and not mixed:
                allowable_mpa = yield_mpa / sf
                ax.axhline(allowable_mpa, color="r", linewidth=2, linestyle="--")
                max_ref = max(max_ref, allowable_mpa)
            elif mixed:
                if 1.0 > max_ref:
                    ax.axhline(1.0, color="r", linewidth=2, linestyle="--")
                    max_ref = 1.0

    if max_ref > 0:
        ax.set_ylim([0, max_ref * 1.1])
        ax.text(0.075, 1.03, "failure limit", transform=ax.transAxes, color="r", fontsize=8)

    ax.set_xlabel("Normalised spanwise station η  [—]   (0 = root, 1 = tip)")
    if mixed:
        ax.set_ylabel("Strength Utilisation Ratio  [—]")
    elif has_composite:
        ax.set_ylabel("Tsai-Wu Strength Ratio  [—]")
    else:
        ax.set_ylabel("von Mises stress  [MPa]")

    if plotted:
        ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)

    if not plotted:
        ax.text(0.5, 0.5, "No stress data available", transform=ax.transAxes,
                ha="center", va="center", fontsize=10, color="gray")

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "stress_distribution", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: convergence
# ---------------------------------------------------------------------------


def plot_convergence(run_id: str, convergence_data: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot solver residual history.

    Parameters
    ----------
    convergence_data:
        Dict with keys ``residual_trace`` (list of floats) and optionally
        ``converged`` (bool), ``iterations`` (int), ``final_residual`` (float).
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Convergence — {case_name}" if case_name else "Convergence History"
    fig, ax = _make_fig(run_id, title)

    trace = convergence_data.get("residual_trace", [])
    converged = convergence_data.get("converged", None)
    final = convergence_data.get("final_residual")

    if trace:
        iters = list(range(len(trace)))
        ax.semilogy(iters, trace, "b-o", markersize=3, linewidth=1.5)
        ax.set_xlabel("Iteration  [—]")
        ax.set_ylabel("Residual norm  [—]")
        status = "converged" if converged else ("not converged" if converged is False else "")
        ax.set_title(f"Final residual: {final:.3e}  {status}" if final else "", fontsize=8)
    else:
        # No trace available — show summary only
        msg = (
            f"Solver: {convergence_data.get('solver_type', 'unknown')}\n"
            f"Iterations: {convergence_data.get('iterations', '?')}\n"
            f"Converged: {converged}\n"
            f"Final residual: {final}"
        )
        ax.text(0.5, 0.5, msg, transform=ax.transAxes,
                ha="center", va="center", fontsize=10,
                bbox={"facecolor": "lightyellow", "alpha": 0.8, "edgecolor": "gray"})
        ax.set_title("Residual trace not captured (opt-in: set capture_trace=True)", fontsize=8)
        ax.axis("off")

    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "convergence", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: planform
# ---------------------------------------------------------------------------


def plot_planform(run_id: str, mesh_data: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot wing planform (top view) with optional deflection overlay.

    Parameters
    ----------
    mesh_data:
        Dict with ``mesh`` (list of shape [nx, ny, 3]) and optionally
        ``def_mesh`` (deformed mesh list of same shape) for deflection overlay.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Planform — {case_name}" if case_name else "Wing Planform"
    fig, ax = _make_fig(run_id, title)

    mesh_list = mesh_data.get("mesh")
    def_mesh_list = mesh_data.get("def_mesh")

    if mesh_list is None:
        ax.text(0.5, 0.5, "Mesh data not available in artifact.\n"
                "Call get_detailed_results(run_id, 'standard') first.",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="gray")
        ax.axis("off")
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        return _fig_to_response(fig, run_id, "planform")

    mesh = np.array(mesh_list)
    nx, ny, _ = mesh.shape

    # Draw leading and trailing edges
    le = mesh[0, :, :]   # leading edge nodes
    te = mesh[-1, :, :]  # trailing edge nodes

    ax.plot(le[:, 1], le[:, 0], "b-", linewidth=1.5, label="LE (undeformed)")
    ax.plot(te[:, 1], te[:, 0], "b--", linewidth=1.0, label="TE (undeformed)")
    ax.plot([le[0, 1], te[0, 1]], [le[0, 0], te[0, 0]], "b-", linewidth=0.8)   # root
    ax.plot([le[-1, 1], te[-1, 1]], [le[-1, 0], te[-1, 0]], "b-", linewidth=0.8)  # tip

    if def_mesh_list is not None:
        def_mesh = np.array(def_mesh_list)
        def_le = def_mesh[0, :, :]
        def_te = def_mesh[-1, :, :]
        ax.plot(def_le[:, 1], def_le[:, 0], "r-", linewidth=1.5, label="LE (deformed)", alpha=0.7)
        ax.plot(def_te[:, 1], def_te[:, 0], "r--", linewidth=1.0, alpha=0.7)

    ax.set_xlabel("Spanwise y  [m]")
    ax.set_ylabel("Chordwise x  [m]")
    # Get original mesh dimensions from snapshot (the mesh array is 2×ny for LE/TE only)
    snap_nx, snap_ny = nx, ny
    for surf_snap in mesh_data.get("mesh_snapshot", {}).values():
        snap_nx = surf_snap.get("nx", nx)
        snap_ny = surf_snap.get("ny", ny)
        break
    ax.set_title(f"Mesh: {snap_nx}×{snap_ny} nodes", fontsize=8)
    # Standard math convention: LE (smaller x) at bottom, TE (larger x) at top.
    ax.text(0.02, 0.02, "Half-span shown (symmetry)", transform=ax.transAxes,
            fontsize=7, color="gray", va="bottom")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "planform", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: opt_history
# ---------------------------------------------------------------------------


def plot_opt_history(run_id: str, optimization_history: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot optimizer objective convergence history.

    Shows the objective value per optimizer iteration.  If only initial and
    final values are available (no per-iteration trace), displays a two-point
    comparison.

    Parameters
    ----------
    optimization_history:
        Dict from ``results.optimization_history`` with keys:
        ``objective_values`` (list[float]), ``num_iterations`` (int),
        ``initial_dvs`` (dict).
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Objective Convergence — {case_name}" if case_name else "Objective Convergence"
    fig, ax = _make_fig(run_id, title)

    obj_vals = optimization_history.get("objective_values", [])
    n_iter = optimization_history.get("num_iterations", 0)

    if obj_vals and len(obj_vals) > 1:
        iters = list(range(len(obj_vals)))
        ax.plot(iters, obj_vals, "b-o", markersize=4, linewidth=1.5)
        ax.set_xlabel("Optimizer iteration  [—]")
        ax.set_ylabel("Objective value  [—]")
        pct = 100.0 * (obj_vals[-1] - obj_vals[0]) / max(abs(obj_vals[0]), 1e-300)
        ax.set_title(
            f"Initial: {obj_vals[0]:.4g}   Final: {obj_vals[-1]:.4g}   "
            f"Change: {pct:+.1f}%",
            fontsize=8,
        )
    elif obj_vals:
        # Only one point recorded — show as a single marker with annotation
        ax.plot([0], obj_vals[:1], "bo", markersize=8)
        ax.set_xlabel("Optimizer iteration  [—]")
        ax.set_ylabel("Objective value  [—]")
        ax.set_title(f"Recorded: {obj_vals[0]:.4g}  (n_iter={n_iter})", fontsize=8)
    else:
        # No per-iteration data — show summary text
        msg = (
            f"No per-iteration objective trace captured.\n"
            f"Optimizer iterations: {n_iter}\n\n"
            "Run with a SqliteRecorder-enabled build to capture full history."
        )
        ax.text(0.5, 0.5, msg, transform=ax.transAxes,
                ha="center", va="center", fontsize=9, color="gray",
                bbox={"facecolor": "lightyellow", "alpha": 0.8, "edgecolor": "gray"})
        ax.axis("off")

    # Constraint traces on secondary y-axis (if available)
    constraint_history = optimization_history.get("constraint_history", {})
    if constraint_history and obj_vals and len(obj_vals) > 1:
        ax2 = ax.twinx()
        _CON_COLORS = {"failure": "red", "CL": "steelblue", "L_equals_W": "green", "CD": "orange", "CM": "purple"}
        _CON_REFS = {"failure": 1.0, "L_equals_W": 0.0}
        for con_name, con_vals in constraint_history.items():
            color = _CON_COLORS.get(con_name, "gray")
            citers = list(range(len(con_vals)))
            ax2.plot(citers, con_vals, "--", linewidth=1.2, color=color,
                     label=con_name, alpha=0.7)
            if con_name in _CON_REFS:
                ax2.axhline(_CON_REFS[con_name], color=color, linewidth=0.6,
                            linestyle=":", alpha=0.5)
        ax2.set_ylabel("Constraint value  [—]", fontsize=8)
        ax2.legend(fontsize=6, loc="center right")

    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "opt_history", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: opt_dv_evolution
# ---------------------------------------------------------------------------


def plot_opt_dv_evolution(
    run_id: str, optimization_history: dict, case_name: str = "", *,
    save_dir: str | Path | None = None,
    vector_dv_mode: str = "all",
) -> PlotResult:
    """Plot design variable evolution over optimizer iterations.

    Parameters
    ----------
    optimization_history:
        Dict from ``results.optimization_history`` with key
        ``dv_history`` (dict of DV name -> list of per-iteration values).
    vector_dv_mode:
        How to display vector DVs (e.g. chord_cp, twist_cp):
        ``"all"`` -- show individual elements plus the mean (default).
        ``"mean"`` -- show only the mean of the vector.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"DV Evolution -- {case_name}" if case_name else "Design Variable Evolution"
    fig, ax = _make_fig(run_id, title)

    dv_history = optimization_history.get("dv_history", {})

    if not dv_history:
        # Fall back to showing initial vs final values
        initial = optimization_history.get("initial_dvs", {})
        # Try to get final from dv_history or signal absence
        ax.text(0.5, 0.5, "No per-iteration DV history captured.\n"
                "Use opt_comparison to see initial vs final values.",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="gray")
        ax.axis("off")
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        return _fig_to_response(fig, run_id, "opt_dv_evolution")

    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    color_idx = 0
    for dv_name, history in dv_history.items():
        if not history:
            continue
        iters = list(range(len(history)))
        is_vector = isinstance(history[0], (list, np.ndarray)) and len(np.asarray(history[0]).ravel()) > 1

        if is_vector:
            # Individual elements (only when mode is "all")
            if vector_dv_mode == "all":
                n_elem = min(len(np.asarray(history[0]).ravel()), 10)
                for ei in range(n_elem):
                    try:
                        vals = [float(np.asarray(v).ravel()[ei]) for v in history]
                    except Exception:
                        continue
                    initial_val = vals[0] if vals else 0.0
                    if abs(initial_val) > 1e-12:
                        vals_norm = [x / initial_val for x in vals]
                    else:
                        vals_norm = [1.0] * len(vals)
                    color = colors[color_idx % len(colors)]
                    ax.plot(iters, vals_norm, "-o", markersize=2, linewidth=0.8,
                            label=f"{dv_name}[{ei}]", color=color, alpha=0.7)
                    color_idx += 1

            # Mean trace
            try:
                means = [float(np.asarray(v).mean()) for v in history]
                initial_val = means[0] if means else 0.0
                if abs(initial_val) > 1e-12:
                    means_norm = [m / initial_val for m in means]
                else:
                    means_norm = [1.0] * len(means)
                if vector_dv_mode == "all":
                    # Dashed overlay when elements are also shown
                    ax.plot(iters, means_norm, "--", markersize=0, linewidth=2.0,
                            label=f"{dv_name} (mean)", color="black", alpha=0.5)
                else:
                    # Primary trace when mean-only
                    color = colors[color_idx % len(colors)]
                    ax.plot(iters, means_norm, "-o", markersize=3, linewidth=1.5,
                            label=f"{dv_name} (mean)", color=color)
                    color_idx += 1
            except Exception:
                pass
        else:
            # Scalar DV
            try:
                means = [float(np.asarray(v).mean()) for v in history]
            except Exception:
                continue
            initial_val = means[0] if means else 0.0
            if abs(initial_val) > 1e-12:
                means_norm = [m / initial_val for m in means]
            else:
                means_norm = [1.0] * len(means)
            color = colors[color_idx % len(colors)]
            ax.plot(iters, means_norm, "-o", markersize=3, linewidth=1.5,
                    label=dv_name, color=color)
            color_idx += 1

    ax.axhline(1.0, color="gray", linewidth=0.8, linestyle="--", alpha=0.7)
    ax.set_xlabel("Optimizer iteration  [—]")
    ax.set_ylabel("DV / DV_initial  [—]")
    ax.set_title(f"{len(dv_history)} design variable(s)", fontsize=8)
    ax.legend(fontsize=7, loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "opt_dv_evolution", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: opt_comparison
# ---------------------------------------------------------------------------


def plot_opt_comparison(run_id: str, optimization_history: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot before/after comparison of design variable values.

    Generates a grouped bar chart with one group per DV, showing the initial
    value (or mean for vector DVs) alongside the final optimized value.

    Parameters
    ----------
    optimization_history:
        Dict from ``results.optimization_history`` with keys:
        ``initial_dvs`` (dict) and ``final_dvs`` (dict).
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Before/After DV Comparison — {case_name}" if case_name else "Before/After DV Comparison"
    fig, ax = _make_fig(run_id, title)

    initial = optimization_history.get("initial_dvs", {})
    final = optimization_history.get("final_dvs", {})

    # Merge keys from both dicts
    all_dvs = list({**initial, **final}.keys())

    if not all_dvs:
        ax.text(0.5, 0.5, "No initial/final DV data available.",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=10, color="gray")
        ax.axis("off")
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        return _fig_to_response(fig, run_id, "opt_comparison")

    def _scalar_mean(v) -> float:
        """Reduce a DV value (scalar or vector) to a representative float."""
        arr = np.asarray(v).ravel()
        return float(arr.mean())

    dv_history = optimization_history.get("dv_history", {})

    init_ratios = []
    final_ratios = []
    for k in all_dvs:
        # Prefer dv_history for physical values when available
        if k in dv_history and dv_history[k]:
            hist = dv_history[k]
            init_val = float(np.asarray(hist[0]).mean())
            final_val = float(np.asarray(hist[-1]).mean())
        else:
            init_val = _scalar_mean(initial[k]) if k in initial else float("nan")
            final_val = _scalar_mean(final[k]) if k in final else float("nan")
        # Normalize: initial is always 1.0; final is ratio to initial
        if abs(init_val) > 1e-12:
            init_ratios.append(1.0)
            final_ratios.append(final_val / init_val)
        else:
            init_ratios.append(1.0)
            final_ratios.append(float("nan"))

    x = np.arange(len(all_dvs))
    width = 0.35
    bars_i = ax.bar(x - width / 2, init_ratios, width, label="Initial", color="steelblue",
                    edgecolor="navy", linewidth=0.8, alpha=0.85)
    bars_f = ax.bar(x + width / 2, final_ratios, width, label="Optimized", color="darkorange",
                    edgecolor="saddlebrown", linewidth=0.8, alpha=0.85)

    ax.axhline(1.0, color="gray", linewidth=0.8, linestyle="--", alpha=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(all_dvs, rotation=15, ha="right", fontsize=8)
    ax.set_ylabel("DV / DV_initial  [—]")
    ax.set_title("Mean DV ratio: initial vs optimized", fontsize=8)
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "opt_comparison", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: deflection_profile
# ---------------------------------------------------------------------------


def plot_deflection_profile(run_id: str, results: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot spanwise vertical deflection profile.

    Primary data: ``sectional_data.deflection_m`` (per-node z-displacement).
    Falls back to scalar ``tip_deflection_m`` if spanwise data is unavailable.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Deflection Profile — {case_name}" if case_name else "Deflection Profile"
    fig, ax = _make_fig(run_id, title)

    plotted = False
    for surf_name, surf_res in results.get("surfaces", {}).items():
        sectional = surf_res.get("sectional_data", {})
        y = sectional.get("y_span_norm")
        defl = sectional.get("deflection_m")

        if y and defl:
            # deflection_m may have ny or ny-1 entries
            if len(defl) == len(y):
                y_plot = y
            elif len(defl) == len(y) - 1:
                y_plot = [(y[i] + y[i + 1]) / 2.0 for i in range(len(defl))]
            else:
                continue
            ax.plot(y_plot, defl, "-o", markersize=3, linewidth=1.5, label=surf_name)
            plotted = True
        elif surf_res.get("tip_deflection_m") is not None:
            tip_d = surf_res["tip_deflection_m"]
            ax.plot([1.0], [tip_d], "ro", markersize=8, label=f"{surf_name} tip")
            ax.annotate(f"{tip_d:.4f} m", (1.0, tip_d), textcoords="offset points",
                        xytext=(-40, 10), fontsize=8)
            plotted = True

    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_xlabel("Normalised spanwise station η  [—]   (0 = root, 1 = tip)")
    ax.set_ylabel("Vertical deflection  [m]")
    if plotted:
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "No deflection data available", transform=ax.transAxes,
                ha="center", va="center", fontsize=10, color="gray")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "deflection_profile", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: weight_breakdown
# ---------------------------------------------------------------------------


def plot_weight_breakdown(run_id: str, results: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot structural mass breakdown as a horizontal bar chart.

    Shows per-surface structural mass.  If ``element_mass_kg`` is available
    in sectional data, it is shown as a stacked detail alongside the total.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Weight Breakdown — {case_name}" if case_name else "Weight Breakdown"
    fig, ax = _make_fig(run_id, title)

    names = []
    masses = []
    for surf_name, surf_res in results.get("surfaces", {}).items():
        sm = surf_res.get("structural_mass_kg")
        if sm is not None:
            names.append(surf_name)
            masses.append(float(sm))

    # Also check top-level structural_mass
    total_sm = results.get("structural_mass")
    if total_sm is not None and not names:
        names.append("total")
        masses.append(float(total_sm))

    if names:
        y_pos = np.arange(len(names))
        bars = ax.barh(y_pos, masses, color="steelblue", edgecolor="navy", linewidth=0.8)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontsize=8)
        ax.set_xlabel("Structural mass  [kg]")
        # Annotate bar values
        for bar, m in zip(bars, masses):
            ax.text(bar.get_width() + max(masses) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{m:.2f}", va="center", fontsize=8)
        total = sum(masses)
        ax.set_title(f"Total structural mass: {total:.2f} kg", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No structural mass data available", transform=ax.transAxes,
                ha="center", va="center", fontsize=10, color="gray")
        ax.axis("off")

    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "weight_breakdown", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: failure_heatmap
# ---------------------------------------------------------------------------


def plot_failure_heatmap(
    run_id: str, results: dict, mesh_data: dict | None = None,
    case_name: str = "", *, save_dir: str | Path | None = None,
) -> PlotResult:
    """Plot failure index as a colour map over the wing planform.

    Each panel quad is coloured by its failure index value.  Uses
    ``matplotlib.collections.PolyCollection`` for efficient rendering.
    Green = safe (failure < 1), red = structural failure (failure >= 1).
    """
    _require_mpl()
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import Normalize

    title = f"Failure Heatmap — {case_name}" if case_name else "Failure Heatmap"
    fig, ax = _make_fig(run_id, title)

    mesh_data = mesh_data or {}
    mesh_list = mesh_data.get("mesh")

    # Find failure_index from surfaces
    failure = None
    for surf_res in results.get("surfaces", {}).values():
        sect = surf_res.get("sectional_data", {})
        fi = sect.get("failure_index")
        if fi:
            failure = fi
            break

    if mesh_list is None or failure is None:
        missing = []
        if mesh_list is None:
            missing.append("mesh")
        if failure is None:
            missing.append("failure_index")
        ax.text(0.5, 0.5, f"Data not available: {', '.join(missing)}",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=10, color="gray")
        ax.axis("off")
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        return _fig_to_response(fig, run_id, "failure_heatmap", save_dir=save_dir)

    mesh = np.array(mesh_list)
    nx, ny, _ = mesh.shape
    n_panels = ny - 1

    # Build quads: each panel is a polygon with 4 corners (LE_j, TE_j, TE_j+1, LE_j+1)
    # Plot in y (spanwise) vs x (chordwise) plane
    quads = []
    for j in range(n_panels):
        quad = [
            [mesh[0, j, 1], mesh[0, j, 0]],       # LE, station j
            [mesh[-1, j, 1], mesh[-1, j, 0]],      # TE, station j
            [mesh[-1, j + 1, 1], mesh[-1, j + 1, 0]],  # TE, station j+1
            [mesh[0, j + 1, 1], mesh[0, j + 1, 0]],    # LE, station j+1
        ]
        quads.append(quad)

    # Truncate/extend failure to match panels
    fi_arr = np.array(failure[:n_panels]) if len(failure) >= n_panels else np.array(failure)
    if len(fi_arr) < n_panels:
        fi_arr = np.pad(fi_arr, (0, n_panels - len(fi_arr)), constant_values=0.0)

    cmap = plt.get_cmap("RdYlGn_r")
    # Normalise: 0 to max(failure, 1.5) so the colour scale is meaningful
    vmax = max(float(fi_arr.max()), 1.5)
    norm = Normalize(vmin=0, vmax=vmax)

    pc = PolyCollection(quads, array=fi_arr, cmap=cmap, norm=norm,
                        edgecolors="k", linewidths=0.5)
    ax.add_collection(pc)
    ax.autoscale()

    cbar = fig.colorbar(pc, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Failure index  [—]  (>1.0 = failed)", fontsize=8)

    # Mark failure threshold
    if float(fi_arr.max()) > 1.0:
        ax.set_title(f"max failure = {float(fi_arr.max()):.3f} (FAILED)", fontsize=8, color="red")
    else:
        ax.set_title(f"max failure = {float(fi_arr.max()):.3f} (OK)", fontsize=8)

    ax.set_xlabel("Spanwise y  [m]")
    ax.set_ylabel("Chordwise x  [m]")
    ax.grid(True, alpha=0.2)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "failure_heatmap", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: twist_chord_overlay
# ---------------------------------------------------------------------------


def plot_twist_chord_overlay(
    run_id: str, results: dict, mesh_data: dict | None = None,
    case_name: str = "", *, save_dir: str | Path | None = None,
) -> PlotResult:
    """Plot twist and chord distributions vs spanwise station on dual y-axes.

    Twist (degrees) on the left axis, chord (metres) on the right axis.
    Extracts from ``sectional_data.twist_deg`` and ``chord_m``, or computes
    from the mesh leading/trailing edge coordinates as a fallback.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Twist & Chord — {case_name}" if case_name else "Twist & Chord Distribution"
    fig, ax1 = plt.subplots(figsize=(_FIG_WIDTH_IN, _FIG_HEIGHT_IN))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.98)

    twist = None
    chord = None
    y_span = None

    # Try sectional data first
    sect = _find_sectional(results)
    if sect:
        y_span = sect.get("y_span_norm")
        twist = sect.get("twist_deg")
        chord = sect.get("chord_m")

    # Fallback: compute from mesh
    mesh_data = mesh_data or {}
    mesh_list = mesh_data.get("mesh")
    if (twist is None or chord is None) and mesh_list is not None:
        mesh = np.array(mesh_list)
        le_x = mesh[0, :, 0]
        te_x = mesh[-1, :, 0]
        le_z = mesh[0, :, 2]
        te_z = mesh[-1, :, 2]
        chord_arr = te_x - le_x
        twist_arr = np.degrees(np.arctan2(te_z - le_z, chord_arr))
        # Reverse to root-to-tip
        if chord is None:
            chord = chord_arr[::-1].tolist()
        if twist is None:
            twist = twist_arr[::-1].tolist()
        if y_span is None:
            y_abs = np.abs(mesh[0, :, 1])
            y_max = y_abs.max() if y_abs.max() > 0 else 1.0
            y_span = (y_abs[::-1] / y_max).tolist()

    if twist is None and chord is None:
        ax1.text(0.5, 0.5, "No twist/chord data available", transform=ax1.transAxes,
                 ha="center", va="center", fontsize=10, color="gray")
        ax1.axis("off")
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        return _fig_to_response(fig, run_id, "twist_chord_overlay", save_dir=save_dir)

    x_axis = y_span if y_span else list(range(max(len(twist or []), len(chord or []))))

    # Twist on left axis (blue)
    color_tw = "tab:blue"
    ax1.set_xlabel("Normalised spanwise station η  [—]   (0 = root, 1 = tip)")
    if twist and len(twist) == len(x_axis):
        ax1.plot(x_axis, twist, color=color_tw, linewidth=1.5, marker="o", markersize=3, label="Twist")
        ax1.set_ylabel("Twist  [deg]", color=color_tw)
        ax1.tick_params(axis="y", labelcolor=color_tw)

    # Chord on right axis (red)
    ax2 = ax1.twinx()
    color_ch = "tab:red"
    if chord and len(chord) == len(x_axis):
        ax2.plot(x_axis, chord, color=color_ch, linewidth=1.5, marker="s", markersize=3, label="Chord")
        ax2.set_ylabel("Chord  [m]", color=color_ch)
        ax2.tick_params(axis="y", labelcolor=color_ch)

    ax1.grid(True, alpha=0.3)
    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    if lines1 or lines2:
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="best")

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "twist_chord_overlay", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Helpers: structural FEM rendering (from plot_wing.py lines 508-560)
# ---------------------------------------------------------------------------


def _draw_tube_structure(ax, mesh, radius, thickness, fem_origin):
    """Draw coloured cylindrical FEM tube elements along the spar.

    Adapted from ``openaerostruct/utils/plot_wing.py`` lines 508-560.
    Each element is a short cylinder segment coloured by normalised thickness.
    """
    matplotlib, _ = _require_mpl()
    cm = matplotlib.cm

    radius = np.asarray(radius)
    thickness = np.asarray(thickness)
    t_max = float(thickness.max()) if thickness.max() > 0 else 1.0
    colors = thickness / t_max  # normalise for colormap

    num_circ = 12
    p = np.linspace(0, 2 * np.pi, num_circ)

    chords = mesh[-1, :, 0] - mesh[0, :, 0]
    comp = fem_origin * chords + mesh[0, :, 0]

    for i in range(len(thickness)):
        r = np.array((radius[i], radius[i]))
        R, P = np.meshgrid(r, p)
        X, Z = R * np.cos(P), R * np.sin(P)

        X[:, 0] += comp[i]
        X[:, 1] += comp[i + 1]
        Z[:, 0] += fem_origin * (mesh[-1, i, 2] - mesh[0, i, 2]) + mesh[0, i, 2]
        Z[:, 1] += fem_origin * (mesh[-1, i + 1, 2] - mesh[0, i + 1, 2]) + mesh[0, i + 1, 2]

        Y = np.empty(X.shape)
        Y[:] = np.linspace(mesh[0, i, 1], mesh[0, i + 1, 1], 2)

        col = np.full(X.shape, colors[i])
        ax.plot_surface(X, Y, Z, rstride=1, cstride=1,
                        facecolors=cm.viridis(col), linewidth=0)


def _draw_wingbox_structure(ax, mesh, spar_thickness, skin_thickness, fem_origin):
    """Draw coloured rectangular spar panels for wingbox FEM model.

    Draws flat rectangular panels along the spar location, coloured by
    spar thickness. Simpler than the tube representation but clearly shows
    the structural element locations.
    """
    matplotlib, _ = _require_mpl()
    cm = matplotlib.cm

    spar_t = np.asarray(spar_thickness)
    t_max = float(spar_t.max()) if spar_t.max() > 0 else 1.0
    colors = spar_t / t_max

    chords = mesh[-1, :, 0] - mesh[0, :, 0]
    comp = fem_origin * chords + mesh[0, :, 0]

    for i in range(len(spar_t)):
        # Rectangular panel along spar between nodes i and i+1
        # Width = fraction of local chord for visibility
        half_h = max(chords[i], chords[i + 1]) * 0.08  # half-height of panel
        x_c0, x_c1 = comp[i], comp[i + 1]
        z0 = fem_origin * (mesh[-1, i, 2] - mesh[0, i, 2]) + mesh[0, i, 2]
        z1 = fem_origin * (mesh[-1, i + 1, 2] - mesh[0, i + 1, 2]) + mesh[0, i + 1, 2]
        y0, y1 = mesh[0, i, 1], mesh[0, i + 1, 1]

        # Four corners of the rectangular panel
        xs = np.array([[x_c0, x_c1], [x_c0, x_c1]])
        ys = np.array([[y0, y1], [y0, y1]])
        zs = np.array([[z0 - half_h, z1 - half_h], [z0 + half_h, z1 + half_h]])

        col = np.full(xs.shape, colors[i])
        ax.plot_surface(xs, ys, zs, rstride=1, cstride=1,
                        facecolors=cm.viridis(col), linewidth=0)


# ---------------------------------------------------------------------------
# Plot: mesh_3d  (adapted from openaerostruct/utils/plot_wing.py lines 462-578)
# ---------------------------------------------------------------------------


def plot_mesh_3d(
    run_id: str, mesh_data: dict, case_name: str = "", *,
    save_dir: str | Path | None = None,
    show_deflection: bool = True,
    deflection_scale: float = 2.0,
) -> PlotResult:
    """Plot 3D wireframe mesh with optional deflection overlay.

    Rendering approach is directly adapted from the proven
    ``openaerostruct/utils/plot_wing.py`` — using ``Axes3D.plot_wireframe``
    with the matplotlib Agg backend for headless PNG generation.

    Parameters
    ----------
    mesh_data:
        Dict with ``mesh`` (list of shape [nx, ny, 3]) and optionally
        ``def_mesh`` (deformed mesh, same shape) for deflection overlay.
    show_deflection:
        Whether to overlay the deformed mesh (when available).
    deflection_scale:
        Exaggeration factor for deflection visualisation (default 2.0).
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"3D Mesh — {case_name}" if case_name else "3D Wing Mesh"
    fig, ax = _make_fig_3d(run_id, title)

    mesh_list = mesh_data.get("mesh")
    if mesh_list is None:
        ax.text2D(0.5, 0.5, "Mesh data not available.\n"
                  "Call get_detailed_results(run_id, 'standard') first.",
                  transform=ax.transAxes, ha="center", va="center",
                  fontsize=9, color="gray")
        ax.set_axis_off()
        fig.subplots_adjust(left=0, right=1, bottom=0, top=0.90)
        return _fig_to_response(fig, run_id, "mesh_3d", save_dir=save_dir)

    mesh = np.array(mesh_list)
    x = mesh[:, :, 0]
    y = mesh[:, :, 1]
    z = mesh[:, :, 2]

    def_mesh_list = mesh_data.get("def_mesh")
    has_def = show_deflection and def_mesh_list is not None

    if has_def:
        def_mesh = np.array(def_mesh_list)
        # Exaggerate deflection (adapted from plot_wing.py line 490)
        def_mesh_vis = (def_mesh - mesh) * deflection_scale + def_mesh
        x_def = def_mesh_vis[:, :, 0]
        y_def = def_mesh_vis[:, :, 1]
        z_def = def_mesh_vis[:, :, 2]
        # Deformed in black, undeformed in light gray
        ax.plot_wireframe(x_def, y_def, z_def, rstride=1, cstride=1, color="k",
                          linewidth=0.8)
        ax.plot_wireframe(x, y, z, rstride=1, cstride=1, color="k", alpha=0.3,
                          linewidth=0.5)
    else:
        ax.plot_wireframe(x, y, z, rstride=1, cstride=1, color="k", linewidth=0.8)

    # Structural FEM rendering — use deformed mesh if available for spar position
    struct_mesh = def_mesh_vis if has_def else mesh
    fem_type = mesh_data.get("fem_model_type")
    struct_label = None

    if fem_type == "tube" and mesh_data.get("radius") is not None:
        radius = mesh_data["radius"]
        thickness = mesh_data.get("thickness", radius)
        fem_origin = mesh_data.get("fem_origin", 0.35)
        _draw_tube_structure(ax, struct_mesh, radius, thickness, fem_origin)
        struct_label = "tube (colour = thickness)"
    elif fem_type == "wingbox" and mesh_data.get("spar_thickness") is not None:
        spar_t = mesh_data["spar_thickness"]
        skin_t = mesh_data.get("skin_thickness", spar_t)
        fem_origin = mesh_data.get("fem_origin", 0.35)
        _draw_wingbox_structure(ax, struct_mesh, spar_t, skin_t, fem_origin)
        struct_label = "wingbox (colour = spar thickness)"

    # Per-axis scaling with equal aspect ratio so the wing fills the frame.
    # Compute actual data range per axis, then pad to equal half-range.
    all_pts = mesh
    if has_def:
        all_pts = np.concatenate([mesh, def_mesh_vis], axis=0)
    x_min, x_max = float(all_pts[:, :, 0].min()), float(all_pts[:, :, 0].max())
    y_min, y_max = float(all_pts[:, :, 1].min()), float(all_pts[:, :, 1].max())
    z_min, z_max = float(all_pts[:, :, 2].min()), float(all_pts[:, :, 2].max())
    # Equal half-range on each axis (preserves aspect ratio)
    ranges = [x_max - x_min, y_max - y_min, max(z_max - z_min, 0.5)]
    max_range = max(ranges) / 2.0
    x_mid = (x_max + x_min) / 2.0
    y_mid = (y_max + y_min) / 2.0
    z_mid = (z_max + z_min) / 2.0
    ax.auto_scale_xyz(
        [x_mid - max_range, x_mid + max_range],
        [y_mid - max_range, y_mid + max_range],
        [z_mid - max_range, z_mid + max_range],
    )
    ax.set_axis_off()
    ax.view_init(elev=25, azim=-135)

    # Subtitle with mesh dimensions and structural model info
    nx, ny, _ = mesh.shape
    sub = f"Mesh: {nx}×{ny} nodes"
    if struct_label:
        sub += f"  |  {struct_label}"
    if has_def:
        max_defl = float(np.max(np.abs(def_mesh[:, :, 2] - mesh[:, :, 2])))
        sub += f"  |  max z-deflection: {max_defl:.4f} m (x{deflection_scale} exaggerated)"
    ax.set_title(sub, fontsize=8, y=-0.02)

    fig.subplots_adjust(left=0, right=1, bottom=0.02, top=0.90)
    return _fig_to_response(fig, run_id, "mesh_3d", save_dir=save_dir)


# ---------------------------------------------------------------------------
# Plot: multipoint_comparison
# ---------------------------------------------------------------------------


def plot_multipoint_comparison(run_id: str, results: dict, case_name: str = "", *, save_dir: str | Path | None = None) -> PlotResult:
    """Plot side-by-side cruise vs maneuver comparison for multipoint results.

    Expects ``results["final_results"]`` keyed by role (e.g. "cruise", "maneuver").
    Shows 2x2 subplot grid: CL/CD bars, failure comparison, deflection, summary.
    """
    _require_mpl()
    import matplotlib.pyplot as plt

    title = f"Multipoint Comparison — {case_name}" if case_name else "Multipoint Comparison"
    fig, axes = plt.subplots(2, 2, figsize=(_FIG_WIDTH_IN * 1.3, _FIG_HEIGHT_IN * 1.3))
    fig.suptitle(f"{title}\n(run_id: {run_id})", fontsize=9, y=0.99)

    final = results.get("final_results", {})
    if not final or len(final) < 2:
        for ax in axes.flat:
            ax.axis("off")
        axes[0, 0].text(0.5, 0.5, "Multipoint results not available.\n"
                        "Requires optimization with multiple flight points.",
                        transform=axes[0, 0].transAxes, ha="center", va="center",
                        fontsize=10, color="gray")
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        return _fig_to_response(fig, run_id, "multipoint_comparison", save_dir=save_dir)

    roles = list(final.keys())
    colors = ["steelblue", "darkorange", "seagreen", "crimson"]

    # Panel 1: CL/CD grouped bar
    ax1 = axes[0, 0]
    x = np.arange(2)  # CL, CD
    width = 0.8 / len(roles)
    for i, role in enumerate(roles):
        pt = final[role]
        cl = pt.get("CL", 0.0)
        cd = pt.get("CD", 0.0)
        offset = (i - len(roles) / 2 + 0.5) * width
        ax1.bar(x + offset, [cl, cd], width, label=role, color=colors[i % len(colors)],
                edgecolor="k", linewidth=0.5, alpha=0.85)
    ax1.set_xticks(x)
    ax1.set_xticklabels(["CL", "CD"], fontsize=9)
    ax1.legend(fontsize=7)
    ax1.set_title("Aero coefficients", fontsize=8)
    ax1.grid(True, alpha=0.3, axis="y")

    # Panel 2: Failure index per point
    ax2 = axes[0, 1]
    plotted_fail = False
    for i, role in enumerate(roles):
        pt = final[role]
        for sname, sres in pt.get("surfaces", {}).items():
            fi = sres.get("sectional_data", {}).get("failure_index")
            y_s = sres.get("sectional_data", {}).get("y_span_norm")
            if fi and y_s:
                y_plot = y_s if len(fi) == len(y_s) else [(y_s[k] + y_s[k+1])/2 for k in range(len(fi))]
                ax2.plot(y_plot, fi, color=colors[i % len(colors)], linewidth=1.5, label=role)
                plotted_fail = True
    if plotted_fail:
        ax2.axhline(1.0, color="r", linewidth=1.5, linestyle="--", alpha=0.7)
        ax2.legend(fontsize=7)
    else:
        ax2.text(0.5, 0.5, "No failure data", transform=ax2.transAxes,
                 ha="center", va="center", fontsize=9, color="gray")
    ax2.set_title("Failure index", fontsize=8)
    ax2.set_xlabel("η", fontsize=8)
    ax2.grid(True, alpha=0.3)

    # Panel 3: Deflection per point
    ax3 = axes[1, 0]
    plotted_defl = False
    for i, role in enumerate(roles):
        pt = final[role]
        for sname, sres in pt.get("surfaces", {}).items():
            defl = sres.get("sectional_data", {}).get("deflection_m")
            y_s = sres.get("sectional_data", {}).get("y_span_norm")
            if defl and y_s and len(defl) == len(y_s):
                ax3.plot(y_s, defl, color=colors[i % len(colors)], linewidth=1.5, label=role)
                plotted_defl = True
    if plotted_defl:
        ax3.axhline(0, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
        ax3.legend(fontsize=7)
    else:
        ax3.text(0.5, 0.5, "No deflection data", transform=ax3.transAxes,
                 ha="center", va="center", fontsize=9, color="gray")
    ax3.set_title("Deflection [m]", fontsize=8)
    ax3.set_xlabel("η", fontsize=8)
    ax3.grid(True, alpha=0.3)

    # Panel 4: Summary table
    ax4 = axes[1, 1]
    ax4.axis("off")
    rows = []
    headers = ["Metric"] + roles
    metrics = [("CL", ".4f"), ("CD", ".5f"), ("L/D", ".2f"), ("structural_mass_kg", ".1f")]
    for metric, fmt in metrics:
        row = [metric.replace("_", " ")]
        for role in roles:
            val = final[role].get(metric)
            if val is None and metric == "L/D":
                cl = final[role].get("CL", 0)
                cd = final[role].get("CD")
                val = cl / cd if cd and cd > 1e-12 else None
            row.append(f"{val:{fmt}}" if val is not None else "—")
        rows.append(row)

    table = ax4.table(cellText=rows, colLabels=headers, loc="center",
                      cellLoc="center", edges="horizontal")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)
    ax4.set_title("Summary", fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.93])
    return _fig_to_response(fig, run_id, "multipoint_comparison", save_dir=save_dir)


# ---------------------------------------------------------------------------
# N2 / DSM diagram (HTML saved to disk)
# ---------------------------------------------------------------------------


from hangar.sdk.artifacts.store import _NumpyEncoder as _ArtifactsEncoder


class _NumpyEncoder(_ArtifactsEncoder):
    """JSON encoder for numpy types; extends artifacts encoder with OTel/complex support."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.ndarray):
            if np.issubdtype(obj.dtype, np.complexfloating):
                return obj.real.tolist()
            return obj.tolist()
        if isinstance(obj, np.complexfloating):
            return float(obj.real)
        if isinstance(obj, complex):
            return obj.real
        # Catch-all: type objects, enums, or other unserializable values from
        # OpenMDAO viewer data — convert to string rather than crash.
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def generate_n2(
    prob,
    run_id: str,
    case_name: str = "",
    output_dir: str | Path | None = None,
) -> N2Result:
    """Generate an interactive N2 (Design Structure Matrix) diagram saved to disk.

    Calls ``openmdao.api.n2()`` to write a self-contained HTML file and
    extracts compressed viewer data for lightweight metadata delivery.

    Parameters
    ----------
    prob:
        A set-up (and ideally run) ``openmdao.api.Problem`` instance.
    run_id:
        Artifact run ID — used to name the file and included in metadata.
    case_name:
        Optional human-readable label used as the diagram title.
    output_dir:
        Directory to write the HTML file.  Falls back to ``./oas_data/n2/``.

    Returns
    -------
    N2Result
        ``metadata`` dict (small, ~15 KB) with ``file_path``, ``size_bytes``,
        ``image_hash``, and ``viewer_data_compressed`` (base64 zlib ~11 KB).
        ``file_path`` is the absolute path to the saved HTML file.
    """
    import openmdao.api as om
    from openmdao.visualization.n2_viewer.n2_viewer import _get_viewer_data

    out_dir = Path(output_dir) if output_dir is not None else Path("./oas_data/n2")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"n2_{run_id}.html"

    title = case_name or run_id
    om.n2(prob, outfile=str(output_path), show_browser=False, embeddable=False, title=title)

    html_bytes = output_path.read_bytes()
    sha = "sha256-" + hashlib.sha256(html_bytes).hexdigest()[:16]

    # Extract model data dict and compress it for lightweight delivery
    viewer_data = _get_viewer_data(prob, values=True)
    compressed = base64.b64encode(
        zlib.compress(json.dumps(viewer_data, cls=_NumpyEncoder).encode())
    ).decode()

    metadata = {
        "plot_type": "n2",
        "run_id": run_id,
        "format": "html_file",
        "file_path": str(output_path.resolve()),
        "size_bytes": len(html_bytes),
        "image_hash": sha,
        "viewer_data_compressed": compressed,
        "note": (
            f"Interactive N2 diagram saved to {output_path.resolve()}. "
            "Open in a browser to explore."
        ),
    }
    return N2Result(metadata=metadata, file_path=str(output_path.resolve()))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def generate_plot(
    plot_type: str,
    run_id: str,
    results: dict,
    convergence_data: dict | None = None,
    mesh_data: dict | None = None,
    case_name: str = "",
    optimization_history: dict | None = None,
    save_dir: str | Path | None = None,
) -> PlotResult:
    """Generate a plot and return a PlotResult (Image + metadata).

    Parameters
    ----------
    plot_type:
        One of the values in ``PLOT_TYPES``.
    run_id:
        Artifact run ID — included in the plot title.
    results:
        Analysis results dict (from extract_*_results).
    convergence_data:
        Convergence dict — required for "convergence" plot type.
    mesh_data:
        Mesh dict — required for "planform" plot type.
    case_name:
        Human-readable label for the plot title.
    optimization_history:
        Optimization history dict — required for opt_history, opt_dv_evolution,
        and opt_comparison plot types.
    save_dir:
        If provided, the PNG is also saved to
        ``{save_dir}/plots/{run_id}_{plot_type}.png`` and ``file_path`` is
        added to the metadata.

    Returns
    -------
    PlotResult — contains ``image`` (MCP Image, converts to ImageContent) and
    ``metadata`` (plain dict for TextContent / text-only clients).
    """
    if plot_type not in PLOT_TYPES:
        raise ValueError(
            f"Unknown plot_type {plot_type!r}. "
            f"Supported types: {sorted(PLOT_TYPES)}"
        )

    if plot_type == "n2":
        raise ValueError(
            "plot_type='n2' must be handled in server.py via generate_n2(), "
            "not through generate_plot()."
        )

    if plot_type == "lift_distribution":
        return plot_lift_distribution(run_id, results, case_name, save_dir=save_dir)
    elif plot_type == "drag_polar":
        return plot_drag_polar(run_id, results, case_name, save_dir=save_dir)
    elif plot_type == "stress_distribution":
        return plot_stress_distribution(run_id, results, case_name, save_dir=save_dir)
    elif plot_type == "convergence":
        return plot_convergence(run_id, convergence_data or {}, case_name, save_dir=save_dir)
    elif plot_type == "planform":
        return plot_planform(run_id, mesh_data or {}, case_name, save_dir=save_dir)
    elif plot_type == "opt_history":
        return plot_opt_history(run_id, optimization_history or {}, case_name, save_dir=save_dir)
    elif plot_type == "opt_dv_evolution":
        return plot_opt_dv_evolution(run_id, optimization_history or {}, case_name, save_dir=save_dir)
    elif plot_type == "opt_comparison":
        return plot_opt_comparison(run_id, optimization_history or {}, case_name, save_dir=save_dir)
    elif plot_type == "deflection_profile":
        return plot_deflection_profile(run_id, results, case_name, save_dir=save_dir)
    elif plot_type == "weight_breakdown":
        return plot_weight_breakdown(run_id, results, case_name, save_dir=save_dir)
    elif plot_type == "failure_heatmap":
        return plot_failure_heatmap(run_id, results, mesh_data, case_name, save_dir=save_dir)
    elif plot_type == "twist_chord_overlay":
        return plot_twist_chord_overlay(run_id, results, mesh_data, case_name, save_dir=save_dir)
    elif plot_type == "mesh_3d":
        return plot_mesh_3d(run_id, mesh_data or {}, case_name, save_dir=save_dir)
    elif plot_type == "multipoint_comparison":
        return plot_multipoint_comparison(run_id, results, case_name, save_dir=save_dir)
    else:
        raise ValueError(f"Unhandled plot_type: {plot_type!r}")
