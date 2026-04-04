"""Plotting functions for OAS analysis results.

Reads data from OpenMDAO recorder files via CaseReader and produces
matplotlib figures for planform, lift distribution, structural
deformation, twist, thickness, and convergence plots.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Variable discovery
# ---------------------------------------------------------------------------


def _find_outputs(case, pattern: str) -> list[tuple[str, object]]:
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


def _find_first_output(case, *patterns: str) -> tuple[str | None, object]:
    """Find the first output matching any of the given patterns.

    Args:
        case: OpenMDAO Case object.
        *patterns: Glob patterns to try in order.

    Returns:
        (name, value) tuple, or (None, None) if nothing matched.
    """
    for pattern in patterns:
        matches = _find_outputs(case, pattern)
        if matches:
            return matches[0]
    return None, None


def _get_reader_and_final_case(recorder_path: Path):
    """Open a CaseReader and return (reader, final_case).

    Tries problem cases first, then falls back to driver cases.
    """
    import openmdao.api as om
    reader = om.CaseReader(str(recorder_path))

    # Try problem (final) cases first
    problem_cases = reader.list_cases("problem", recurse=False, out_stream=None)
    if problem_cases:
        return reader, reader.get_case(problem_cases[-1])

    # Fall back to last driver case
    driver_cases = reader.list_cases("driver", recurse=False, out_stream=None)
    if driver_cases:
        return reader, reader.get_case(driver_cases[-1])

    raise ValueError(f"No cases found in recorder: {recorder_path}")


# ---------------------------------------------------------------------------
# Plot functions
# ---------------------------------------------------------------------------


def plot_planform(
    recorder_path: Path,
    surface_name: str | None = None,
) -> plt.Figure:
    """Plot a top-down view of the wing mesh.

    Args:
        recorder_path: Path to OpenMDAO recorder .sql/.db file.
        surface_name: Surface name (auto-detected if None).

    Returns:
        matplotlib Figure.
    """
    reader, case = _get_reader_and_final_case(recorder_path)

    # Find the mesh variable
    patterns = [
        f"*{surface_name}.def_mesh" if surface_name else "*def_mesh",
        f"*{surface_name}*.mesh" if surface_name else "*.mesh",
    ]
    name, mesh = _find_first_output(case, *patterns)

    if mesh is None:
        raise ValueError("Could not find mesh data in recorder")

    mesh = np.array(mesh)
    logger.info("Planform plot using variable: %s, shape: %s", name, mesh.shape)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    # mesh shape: (num_x+1, num_y, 3) -- x, y, z coordinates
    if mesh.ndim == 3:
        # Plot chordwise lines (constant spanwise station)
        for j in range(mesh.shape[1]):
            ax.plot(mesh[:, j, 1], mesh[:, j, 0], "b-", linewidth=0.5)
        # Plot spanwise lines (constant chordwise station)
        for i in range(mesh.shape[0]):
            ax.plot(mesh[i, :, 1], mesh[i, :, 0], "b-", linewidth=0.5)

    ax.set_xlabel("Span (m)")
    ax.set_ylabel("Chord (m)")
    ax.set_title("Wing Planform")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


def plot_lift_distribution(
    recorder_path: Path,
    surface_name: str | None = None,
) -> plt.Figure:
    """Plot spanwise lift distribution.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).

    Returns:
        matplotlib Figure.
    """
    reader, case = _get_reader_and_final_case(recorder_path)

    # Try to find sectional CL or sec_forces
    surf = surface_name or "*"
    name, values = _find_first_output(
        case,
        f"*{surf}_perf.sec_forces",
        f"*{surf}*sec_forces",
        f"*{surf}_perf.CL1",
        f"*{surf}*CL1",
    )

    if values is None:
        raise ValueError("Could not find lift distribution data in recorder")

    values = np.array(values)
    logger.info("Lift plot using variable: %s, shape: %s", name, values.shape)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    if "sec_forces" in (name or ""):
        # sec_forces shape: (num_y-1, 3) -- force vector per panel
        # Use the z-component (lift) normalized by panel count
        if values.ndim == 3:
            values = values[0]  # first chordwise station
        if values.ndim == 2:
            lift = values[:, 2]  # z-component
        else:
            lift = values
        span_frac = np.linspace(0, 1, len(lift))
        ax.plot(span_frac, lift, "b-o", markersize=3)
        ax.set_ylabel("Section Lift Force (N)")
    else:
        span_frac = np.linspace(0, 1, len(values))
        ax.plot(span_frac, values, "b-o", markersize=3)
        ax.set_ylabel("Sectional CL")

    ax.set_xlabel("Span Fraction")
    ax.set_title("Spanwise Lift Distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


def plot_convergence(
    recorder_path: Path,
) -> plt.Figure:
    """Plot optimization convergence history.

    Args:
        recorder_path: Path to OpenMDAO recorder file.

    Returns:
        matplotlib Figure.
    """
    import openmdao.api as om
    reader = om.CaseReader(str(recorder_path))

    driver_cases = reader.list_cases("driver", recurse=False, out_stream=None)
    if len(driver_cases) < 2:
        raise ValueError(
            f"Need at least 2 driver cases for convergence plot, "
            f"got {len(driver_cases)}"
        )

    # Extract objective values from each driver case
    iterations = []
    obj_values = []
    obj_name = None

    for i, case_id in enumerate(driver_cases):
        case = reader.get_case(case_id)
        outputs = case.list_outputs(out_stream=None, return_format="dict")

        if obj_name is None:
            # Find objective: look for known names, or pick the first scalar
            for pattern in ["*structural_mass*", "*fuel_burn*", "*CD*", "*drag*"]:
                for name, info in outputs.items():
                    if fnmatch.fnmatch(name, pattern):
                        val = info.get("val", info.get("value"))
                        if val is not None:
                            v = np.atleast_1d(val)
                            if v.size == 1:
                                obj_name = name
                                break
                if obj_name:
                    break

            if obj_name is None:
                # Fallback: first scalar output
                for name, info in outputs.items():
                    val = info.get("val", info.get("value"))
                    if val is not None:
                        v = np.atleast_1d(val)
                        if v.size == 1:
                            obj_name = name
                            break

        if obj_name and obj_name in outputs:
            val = outputs[obj_name].get("val", outputs[obj_name].get("value"))
            if val is not None:
                iterations.append(i)
                obj_values.append(float(np.atleast_1d(val).flat[0]))

    logger.info("Convergence plot: %d iterations, objective: %s", len(iterations), obj_name)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    ax.plot(iterations, obj_values, "b-o", markersize=4)
    ax.set_xlabel("Iteration")
    ax.set_ylabel(obj_name or "Objective")
    ax.set_title("Optimization Convergence")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


def plot_structural_deformation(
    recorder_path: Path,
    surface_name: str | None = None,
) -> plt.Figure:
    """Plot structural deformation (initial vs deformed mesh).

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).

    Returns:
        matplotlib Figure.
    """
    reader, case = _get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    # Find deformed mesh
    _, def_mesh = _find_first_output(
        case,
        f"*{surf}.def_mesh",
        f"*{surf}*def_mesh",
    )

    # Find undeformed mesh
    _, orig_mesh = _find_first_output(
        case,
        f"*{surf}.mesh",
        f"{surf}.mesh",
    )

    if def_mesh is None:
        raise ValueError("Could not find deformed mesh in recorder")

    def_mesh = np.array(def_mesh)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    # Plot deformed mesh z-displacement vs span
    if def_mesh.ndim == 3:
        # Use the leading edge (first chordwise station)
        span = def_mesh[0, :, 1]
        z_def = def_mesh[0, :, 2]
        ax.plot(span, z_def, "r-o", markersize=3, label="Deformed")

        if orig_mesh is not None:
            orig_mesh = np.array(orig_mesh)
            if orig_mesh.ndim == 3:
                z_orig = orig_mesh[0, :, 2]
                ax.plot(span, z_orig, "b--o", markersize=3, label="Undeformed")

    ax.set_xlabel("Span (m)")
    ax.set_ylabel("Vertical Displacement (m)")
    ax.set_title("Structural Deformation")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


def plot_twist(
    recorder_path: Path,
    surface_name: str | None = None,
) -> plt.Figure:
    """Plot spanwise twist distribution.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).

    Returns:
        matplotlib Figure.
    """
    reader, case = _get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    name, twist = _find_first_output(
        case,
        f"{surf}.twist_cp",
        f"*{surf}*twist_cp",
        f"*{surf}*twist",
    )

    if twist is None:
        raise ValueError("Could not find twist data in recorder")

    twist = np.array(twist).flatten()
    logger.info("Twist plot using variable: %s, shape: %s", name, twist.shape)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    span_frac = np.linspace(0, 1, len(twist))
    ax.plot(span_frac, twist, "b-o", markersize=4)
    ax.set_xlabel("Span Fraction (root to tip)")
    ax.set_ylabel("Twist (deg)")
    ax.set_title("Spanwise Twist Distribution")
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")
    fig.tight_layout()

    return fig


def plot_thickness(
    recorder_path: Path,
    surface_name: str | None = None,
) -> plt.Figure:
    """Plot spanwise spar thickness distribution.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).

    Returns:
        matplotlib Figure.
    """
    reader, case = _get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    name, thickness = _find_first_output(
        case,
        f"{surf}.thickness_cp",
        f"*{surf}*thickness_cp",
        f"*{surf}*thickness",
    )

    if thickness is None:
        raise ValueError("Could not find thickness data in recorder")

    thickness = np.array(thickness).flatten()
    logger.info("Thickness plot using variable: %s, shape: %s", name, thickness.shape)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    span_frac = np.linspace(0, 1, len(thickness))
    ax.plot(span_frac, thickness * 1000, "b-o", markersize=4)  # convert m to mm
    ax.set_xlabel("Span Fraction (root to tip)")
    ax.set_ylabel("Thickness (mm)")
    ax.set_title("Spanwise Spar Thickness Distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Plot dispatcher
# ---------------------------------------------------------------------------

# Map plot type names to functions
PLOT_TYPES = {
    "planform": plot_planform,
    "lift": plot_lift_distribution,
    "convergence": plot_convergence,
    "struct": plot_structural_deformation,
    "twist": plot_twist,
    "thickness": plot_thickness,
}

# Plot types that need a surface_name kwarg
_SURFACE_PLOTS = {"planform", "lift", "struct", "twist", "thickness"}

# Plot types only relevant for aerostruct runs
_AEROSTRUCT_PLOTS = {"struct", "thickness"}


def generate_plots(
    recorder_path: Path,
    plot_types: list[str] | None = None,
    surface_name: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Generate one or more plot types and save as PNG files.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        plot_types: List of plot type names, or None for all.
        surface_name: Surface name (auto-detected if None).
        output_dir: Directory to save PNGs. Uses current dir if None.

    Returns:
        Dict mapping plot type to saved file path.
    """
    if plot_types is None:
        plot_types = list(PLOT_TYPES.keys())

    if output_dir is None:
        output_dir = Path(".")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    for ptype in plot_types:
        if ptype not in PLOT_TYPES:
            logger.warning("Unknown plot type: %s", ptype)
            continue

        try:
            func = PLOT_TYPES[ptype]
            kwargs: dict = {}
            if ptype in _SURFACE_PLOTS:
                kwargs["surface_name"] = surface_name

            fig = func(recorder_path, **kwargs)
            out_path = output_dir / f"{ptype}.png"
            fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
            plt.close(fig)
            saved[ptype] = out_path
            logger.info("Saved %s plot to %s", ptype, out_path)
        except Exception as exc:
            logger.warning("Skipping %s plot: %s", ptype, exc)

    return saved
