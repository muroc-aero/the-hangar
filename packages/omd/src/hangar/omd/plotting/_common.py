"""Shared helpers for plotting modules.

Variable discovery via CaseReader and common data transforms
used across domain-specific plot modules.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence

import numpy as np

if TYPE_CHECKING:
    from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

# A columnar case table: column name -> per-case values. Kept pandas-free so
# the plotting layer adds no heavy dependency to omd core (the study store
# itself writes cases.csv with the stdlib csv module).
Table = Mapping[str, Sequence]


# ---------------------------------------------------------------------------
# Variable discovery
# ---------------------------------------------------------------------------


def find_outputs(case, pattern: str) -> list[tuple[str, object]]:
    """Find outputs matching a glob pattern in a Case.

    Args:
        case: OpenMDAO Case object.
        pattern: Glob pattern to match variable names.

    Returns:
        List of (name, value) tuples for matching outputs.
    """
    matches = []
    try:
        outputs = case.list_outputs(out_stream=None, return_format="dict")
        for name, info in outputs.items():
            if fnmatch.fnmatch(name, pattern):
                val = info.get("val", info.get("value"))
                matches.append((name, val))
    except Exception as exc:
        logger.debug("Could not list outputs: %s", exc)
    return matches


def find_first_output(case, *patterns: str) -> tuple[str | None, object]:
    """Find the first output matching any of the given patterns.

    Args:
        case: OpenMDAO Case object.
        *patterns: Glob patterns to try in order.

    Returns:
        (name, value) tuple, or (None, None) if nothing matched.
    """
    for pattern in patterns:
        matches = find_outputs(case, pattern)
        if matches:
            return matches[0]
    return None, None


def get_reader_and_final_case(recorder_path: Path):
    """Open a CaseReader and return (reader, final_case).

    Tries problem cases first, then falls back to driver cases.
    """
    import openmdao.api as om
    reader = om.CaseReader(str(recorder_path))

    problem_cases = reader.list_cases("problem", recurse=False, out_stream=None)
    if problem_cases:
        return reader, reader.get_case(problem_cases[-1])

    driver_cases = reader.list_cases("driver", recurse=False, out_stream=None)
    if driver_cases:
        return reader, reader.get_case(driver_cases[-1])

    raise ValueError(f"No cases found in recorder: {recorder_path}")


# ---------------------------------------------------------------------------
# Surface name detection
# ---------------------------------------------------------------------------


def detect_surface_name(case) -> str | None:
    """Detect the surface name from a Case's outputs.

    Looks for mesh variables and extracts the surface name from
    the variable path (e.g., ``wing.mesh`` -> ``wing``).
    """
    try:
        outputs = case.list_outputs(out_stream=None, return_format="dict")
        for name in outputs:
            # Pattern: {surface}.mesh or {surface}.geometry.mesh.*
            if name.endswith(".mesh") and ".geometry.mesh." not in name:
                parts = name.rsplit(".", 1)
                if parts:
                    return parts[0].split(".")[-1]
        # Fallback: look for {surface}.geometry.twist
        for name in outputs:
            if ".geometry.twist" in name:
                return name.split(".geometry.twist")[0].split(".")[-1]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Span coordinate extraction
# ---------------------------------------------------------------------------


def get_span_eta(
    mesh: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Extract normalized span coordinates from a mesh and detect ordering.

    OAS symmetric meshes have y-coords from negative (tip) to 0 (root).
    This function normalizes to eta in [0, 1] with 0=root, 1=tip, and
    reports whether the original data was reversed.

    Args:
        mesh: Array of shape (num_x, num_y, 3).

    Returns:
        node_eta: Normalized [0,1] span coords at nodes (root=0, tip=1).
        elem_eta: Midpoints for element-based quantities (length ny-1).
        was_reversed: True if the raw ordering was tip-to-root and was flipped.
    """
    y_coords = mesh[0, :, 1]
    y_abs = np.abs(y_coords)
    y_max = y_abs.max()
    if y_max < 1e-10:
        n = len(y_coords)
        node_eta = np.linspace(0, 1, n)
        elem_eta = 0.5 * (node_eta[:-1] + node_eta[1:])
        return node_eta, elem_eta, False

    node_eta = y_abs / y_max

    # Detect if ordering is tip-to-root (descending eta)
    was_reversed = node_eta[0] > node_eta[-1]
    if was_reversed:
        node_eta = node_eta[::-1]

    elem_eta = 0.5 * (node_eta[:-1] + node_eta[1:])
    return node_eta, elem_eta, was_reversed


# ---------------------------------------------------------------------------
# Data transforms
# ---------------------------------------------------------------------------


def mirror_spanwise(y: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mirror half-span data to produce a full-span view.

    Assumes the input is one half of a symmetric wing. Mirrors by
    negating y-coordinates and reversing/concatenating the values.

    Args:
        y: Spanwise coordinates (1D array).
        values: Data values at each station (1D array, same length as y).

    Returns:
        Tuple of (full_y, full_values) arrays.
    """
    y = np.asarray(y).flatten()
    values = np.asarray(values).flatten()

    # Mirror the y-coordinates
    y_mirror = -y[::-1]
    v_mirror = values[::-1]

    # Remove the duplicate at the symmetry plane (y=0)
    if len(y) > 0 and np.abs(y_mirror[-1] - y[0]) < 1e-10:
        y_mirror = y_mirror[:-1]
        v_mirror = v_mirror[:-1]

    full_y = np.concatenate([y_mirror, y])
    full_v = np.concatenate([v_mirror, values])
    return full_y, full_v


def compute_elliptical_lift(
    lift: np.ndarray,
    span_frac: np.ndarray,
) -> np.ndarray:
    """Compute the ideal elliptical lift distribution for reference.

    Given an actual lift distribution and normalized span positions,
    compute the elliptical distribution with the same total lift area.
    Matches the upstream OAS plot_wing.py approach: l(eta) = l_0 * sqrt(1 - eta^2)
    where eta goes from 0 (root) to 1 (tip).

    Args:
        lift: Actual lift values at each spanwise station.
        span_frac: Normalized span positions in [0, 1] (half-span, root to tip).

    Returns:
        Elliptical lift values at the same span positions.
    """
    lift = np.asarray(lift).flatten()
    span_frac = np.asarray(span_frac).flatten()

    # Normalize to [0, 1] (root=0, tip=1)
    s_min, s_max = span_frac.min(), span_frac.max()
    s_range = s_max - s_min
    if s_range < 1e-10:
        return np.zeros_like(lift)
    eta = (span_frac - s_min) / s_range

    # Total lift area (trapezoidal integration over half-span)
    d_eta = np.diff(eta)
    lift_area = np.sum(0.5 * (lift[:-1] + lift[1:]) * np.abs(d_eta))

    # Elliptical: l(eta) = (4 * area / pi) * sqrt(1 - eta^2)
    # Integral of sqrt(1-eta^2) from 0 to 1 = pi/4, so total area = l_0 * pi/4
    # => l_0 = 4 * area / pi
    arg = np.clip(1.0 - eta ** 2, 0.0, None)
    lift_ell = 4.0 * lift_area / np.pi * np.sqrt(arg)

    return lift_ell


# ---------------------------------------------------------------------------
# Study-level 2-axis grid rendering
# ---------------------------------------------------------------------------
#
# These helpers render one heatmap panel per output column over a two-axis
# study grid (e.g. the Brelje 2018a Fig 5/6 design-range x specific-energy
# trade space). They are tool-independent: a per-tool study-plot provider
# (see ``OCP_STUDY_PLOTS`` in ``plotting/ocp.py``) decides which columns and
# labels to plot and calls ``render_grid``. The mechanism is ported from the
# bespoke ``brelje_2018a/pipeline/plotting.py`` so the paper-style figure is
# reproducible from a study's ``cases.csv``.


@dataclass
class PanelSpec:
    """One heatmap panel in a study grid figure.

    Attributes:
        column: case-table column to plot (raw output or a derived column).
        label: colorbar label; falls back to ``column`` when None.
        vmin, vmax: colorbar limits; auto-ranged from the data when None.
        overlay_contours: draw thin contour lines on top (paper style only).
    """

    column: str
    label: str | None = None
    vmin: float | None = None
    vmax: float | None = None
    overlay_contours: bool = False


def to_float_array(values: Sequence) -> np.ndarray:
    """Coerce a column of mixed values to a float ndarray (NaN on failure)."""
    out = np.full(len(values), np.nan, dtype=float)
    for i, val in enumerate(values):
        if val is None or val == "":
            continue
        try:
            out[i] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def _cell_edges(centers: np.ndarray) -> np.ndarray:
    """Convert N cell-center coordinates to N+1 cell-edge coordinates so
    pcolormesh draws each grid cell as a rectangle centered on its (x, y).
    Edges are placed at midpoints with end-cell extrapolation."""
    centers = np.asarray(centers, dtype=float)
    if len(centers) < 2:
        d = 1.0
        return np.array([centers[0] - d / 2, centers[0] + d / 2])
    mids = 0.5 * (centers[:-1] + centers[1:])
    first = centers[0] - (mids[0] - centers[0])
    last = centers[-1] + (centers[-1] - mids[-1])
    return np.concatenate([[first], mids, [last]])


def pivot_grid(
    table: Table, x_col: str, y_col: str, value_col: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pivot a long case table into a grid for one value column.

    Returns ``(x_axis, y_axis, grid)`` with ``grid`` of shape
    ``(n_y, n_x)``. Non-numeric or missing cells stay NaN; duplicate
    (x, y) coordinates keep the last row (so a manual case at a grid
    coordinate overrides the matrix cell).
    """
    x = to_float_array(table[x_col])
    y = to_float_array(table[y_col])
    v = to_float_array(table[value_col])

    x_centers = np.array(sorted({xv for xv in x if np.isfinite(xv)}))
    y_centers = np.array(sorted({yv for yv in y if np.isfinite(yv)}))
    xi = {val: i for i, val in enumerate(x_centers)}
    yi = {val: i for i, val in enumerate(y_centers)}

    grid = np.full((len(y_centers), len(x_centers)), np.nan)
    for k in range(len(v)):
        if np.isfinite(x[k]) and np.isfinite(y[k]):
            grid[yi[y[k]], xi[x[k]]] = v[k]
    return x_centers, y_centers, grid


def render_grid(
    table: Table,
    x_axis: str,
    y_axis: str,
    panels: list[PanelSpec],
    *,
    style: str = "paper",
    x_label: str | None = None,
    y_label: str | None = None,
    suptitle: str | None = None,
    ncols: int = 2,
) -> "Figure":
    """Render a grid of heatmap panels over a two-axis study trade space.

    Args:
        table: columnar case table (column name -> per-case values) with
            ``x_axis``, ``y_axis``, and each panel's column.
        x_axis, y_axis: column names of the two numeric grid axes.
        panels: one PanelSpec per panel.
        style: ``"paper"`` (pcolormesh per-cell rectangles) or
            ``"contour"`` (smooth contourf).
        x_label, y_label: axis labels (default to the axis column names).
        suptitle: figure title.
        ncols: panels per row.

    Returns:
        The matplotlib Figure (caller saves/closes it).
    """
    import matplotlib.pyplot as plt

    if not panels:
        raise ValueError("render_grid requires at least one panel")
    if style not in ("paper", "contour"):
        raise ValueError(f"style must be 'paper' or 'contour', got {style!r}")

    n = len(panels)
    ncols = max(1, min(ncols, n))
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(5.25 * ncols, 4.5 * nrows), squeeze=False,
    )
    flat = axes.flatten()

    for ax, panel in zip(flat, panels):
        x, y, z = pivot_grid(table, x_axis, y_axis, panel.column)
        _render_panel(ax, x, y, z, panel, style)
    for ax in flat[n:]:
        ax.axis("off")

    for ax in flat[:n]:
        ax.set_xlabel(x_label or x_axis)
        ax.set_ylabel(y_label or y_axis)

    if suptitle:
        fig.suptitle(suptitle, fontsize=12)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
    else:
        fig.tight_layout()
    return fig


def _render_panel(ax, x, y, z, panel: PanelSpec, style: str) -> None:
    import matplotlib.pyplot as plt

    zmasked = np.ma.masked_invalid(np.asarray(z, dtype=float))
    label = panel.label or panel.column
    if zmasked.count() == 0:
        ax.set_facecolor("#eeeeee")
        ax.text(0.5, 0.5, "no converged cells", ha="center", va="center",
                transform=ax.transAxes, color="#888888")
        ax.set_title(label, fontsize=10)
        return

    vmin = panel.vmin if panel.vmin is not None else float(zmasked.min())
    vmax = panel.vmax if panel.vmax is not None else float(zmasked.max())
    if vmax <= vmin:
        vmax = vmin + 1.0

    if style == "paper":
        xe = _cell_edges(x)
        ye = _cell_edges(y)
        pm = ax.pcolormesh(xe, ye, zmasked, cmap="viridis",
                           vmin=vmin, vmax=vmax, shading="flat")
        cbar = plt.colorbar(pm, ax=ax, pad=0.02)
        cbar.set_label(label)
        # Contour overlay needs at least a 2x2 grid; skip on thin grids.
        if panel.overlay_contours and zmasked.shape[0] >= 2 and zmasked.shape[1] >= 2:
            levels = np.linspace(vmin, vmax, 18)
            ax.contour(x, y, zmasked, levels=levels, colors="white",
                       linewidths=0.4, alpha=0.85)
        ax.set_xlim(xe[0], xe[-1])
        ax.set_ylim(ye[0], ye[-1])
    else:
        levels = np.linspace(vmin, vmax, 11)
        cf = ax.contourf(x, y, zmasked, levels=levels, cmap="viridis",
                         extend="both")
        cbar = plt.colorbar(cf, ax=ax, pad=0.02)
        cbar.set_label(label)
    ax.set_title(label, fontsize=10)
