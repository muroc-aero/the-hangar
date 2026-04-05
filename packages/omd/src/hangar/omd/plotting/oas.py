"""OAS-specific plot types for aero and aerostructural analyses.

Reads data from OpenMDAO recorder files and produces matplotlib
figures matching the upstream OpenAeroStruct plot_wing.py and
plot_wingbox.py visualization capabilities.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from hangar.omd.plotting._common import (
    find_first_output,
    find_outputs,
    get_reader_and_final_case,
    mirror_spanwise,
    compute_elliptical_lift,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Planform
# ---------------------------------------------------------------------------


def plot_planform(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot a top-down view of the wing mesh.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror half-span mesh for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    patterns = [
        f"*{surface_name}.def_mesh" if surface_name else "*def_mesh",
        f"*{surface_name}*.mesh" if surface_name else "*.mesh",
    ]
    name, mesh = find_first_output(case, *patterns)

    if mesh is None:
        raise ValueError("Could not find mesh data in recorder")

    mesh = np.array(mesh)
    logger.info("Planform plot using variable: %s, shape: %s", name, mesh.shape)

    if mirror and mesh.ndim == 3:
        mesh = _mirror_mesh(mesh)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    if mesh.ndim == 3:
        for j in range(mesh.shape[1]):
            ax.plot(mesh[:, j, 1], mesh[:, j, 0], "b-", linewidth=0.5)
        for i in range(mesh.shape[0]):
            ax.plot(mesh[i, :, 1], mesh[i, :, 0], "b-", linewidth=0.5)

    ax.set_xlabel("Span (m)")
    ax.set_ylabel("Chord (m)")
    ax.set_title("Wing Planform")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Lift distribution
# ---------------------------------------------------------------------------


def plot_lift_distribution(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise lift distribution with elliptical reference.

    Shows half-span by default (root to tip, matching upstream OAS
    plot_wing.py convention). Set mirror=True for full-span view.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    # Try sec_forces first (gives actual force distribution)
    name, values = find_first_output(
        case,
        f"*aero_states.{surf}_sec_forces",
        f"*{surf}*sec_forces",
    )

    # Also get mesh for span coordinates and widths for normalization
    _, mesh = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    _, widths = find_first_output(case, f"*{surf}.widths", f"*{surf}*widths")
    _, alpha_val = find_first_output(case, "*alpha*")
    _, rho_val = find_first_output(case, "prob_vars.rho", "*rho*")
    _, v_val = find_first_output(case, "prob_vars.v", "*v*")

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    if values is not None and name and "sec_forces" in name:
        values = np.array(values)
        if values.ndim == 3:
            forces = np.sum(values, axis=0)  # sum over chordwise stations
        elif values.ndim == 2:
            forces = values
        else:
            forces = values

        # Compute lift coefficient per panel (following upstream OAS)
        if (alpha_val is not None and rho_val is not None
                and v_val is not None and widths is not None
                and forces.ndim == 2 and forces.shape[1] >= 3):
            alpha_rad = float(np.atleast_1d(alpha_val).flat[0]) * np.pi / 180.0
            rho = float(np.atleast_1d(rho_val).flat[0])
            v = float(np.atleast_1d(v_val).flat[0])
            w = np.asarray(widths).flatten()

            lift = (
                (-forces[:, 0] * np.sin(alpha_rad) + forces[:, 2] * np.cos(alpha_rad))
                / w / (0.5 * rho * v ** 2)
            )

            # Build span fractions from mesh (normalized to 0=root, 1=tip)
            if mesh is not None:
                m = np.array(mesh)
                if m.ndim == 3:
                    span_coords = np.abs(m[0, :, 1])
                    span_half = span_coords.max()
                    if span_half > 1e-10:
                        eta = span_coords / span_half  # 0=root, 1=tip
                        # Panel midpoints
                        span_mid = 0.5 * (eta[:-1] + eta[1:])
                        # If mesh goes tip-to-root, reverse to root-to-tip
                        if span_mid[0] > span_mid[-1]:
                            span_mid = span_mid[::-1]
                            lift = lift[::-1]
                    else:
                        span_mid = np.linspace(0, 1, len(lift))
                else:
                    span_mid = np.linspace(0, 1, len(lift))
            else:
                span_mid = np.linspace(0, 1, len(lift))

            # Compute elliptical on half-span BEFORE mirroring
            # (matches upstream plot_wing.py approach)
            ell_half = compute_elliptical_lift(lift, span_mid)

            if mirror:
                span_mid_full, lift_full = mirror_spanwise(span_mid, lift)
                _, ell_full = mirror_spanwise(span_mid, ell_half)
            else:
                span_mid_full, lift_full = span_mid, lift
                ell_full = ell_half

            ax.plot(span_mid_full, lift_full, "b-o", markersize=3, linewidth=1.5, label="lift")
            ax.plot(span_mid_full, ell_full, "g--", linewidth=1.5, label="elliptical")

            ax.set_ylabel("Normalised lift  l(y)/q  [m]")
            ax.legend(fontsize=8)
        else:
            # Fallback: raw z-force
            if forces.ndim == 2:
                lift = forces[:, 2] if forces.shape[1] >= 3 else forces[:, 0]
            else:
                lift = forces.flatten()
            span_frac = np.linspace(0, 1, len(lift))
            if mirror:
                span_frac, lift = mirror_spanwise(span_frac, lift)
            ax.plot(span_frac, lift, "b-o", markersize=3)
            ax.set_ylabel("Section Lift Force (N)")
    else:
        # Try CL1 as fallback
        name, cl = find_first_output(
            case,
            f"*{surf}_perf.CL1",
            f"*{surf}*CL1",
        )
        if cl is None:
            raise ValueError("Could not find lift distribution data in recorder")

        cl = np.array(cl).flatten()
        span_frac = np.linspace(0, 1, len(cl))
        if mirror:
            span_frac, cl = mirror_spanwise(span_frac, cl)
        ax.plot(span_frac, cl, "b-o", markersize=3)
        ax.set_ylabel("Sectional CL")

    if mirror:
        ax.set_xlabel("Span Fraction")
    else:
        ax.set_xlabel("Normalised spanwise station  eta = 2y/b  (0 = root, 1 = tip)")
        ax.set_xlim(0, 1)
    ax.set_title("Lift Distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Structural deformation
# ---------------------------------------------------------------------------


def plot_structural_deformation(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot structural deformation (initial vs deformed mesh).

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    _, def_mesh = find_first_output(
        case,
        f"*{surf}.def_mesh",
        f"*{surf}*def_mesh",
    )
    _, orig_mesh = find_first_output(
        case,
        f"*{surf}.mesh",
        f"{surf}.mesh",
    )

    if def_mesh is None:
        raise ValueError("Could not find deformed mesh in recorder")

    def_mesh = np.array(def_mesh)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    if def_mesh.ndim == 3:
        span = def_mesh[0, :, 1]
        z_def = def_mesh[0, :, 2]

        if mirror:
            span_def, z_def = mirror_spanwise(span, z_def)
        else:
            span_def = span

        ax.plot(span_def, z_def, "r-o", markersize=3, label="Deformed")

        if orig_mesh is not None:
            orig_mesh = np.array(orig_mesh)
            if orig_mesh.ndim == 3:
                z_orig = orig_mesh[0, :, 2]
                if mirror:
                    span_orig, z_orig = mirror_spanwise(span, z_orig)
                else:
                    span_orig = span
                ax.plot(span_orig, z_orig, "b--o", markersize=3, label="Undeformed")

    ax.set_xlabel("Span (m)")
    ax.set_ylabel("Vertical Displacement (m)")
    ax.set_title("Structural Deformation")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Twist
# ---------------------------------------------------------------------------


def plot_twist(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise twist distribution.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    name, twist = find_first_output(
        case,
        f"*{surf}.geometry.twist",
        f"*{surf}*twist_cp",
        f"*{surf}*twist",
    )

    if twist is None:
        raise ValueError("Could not find twist data in recorder")

    twist = np.array(twist).flatten()
    logger.info("Twist plot using variable: %s, shape: %s", name, twist.shape)

    # Try to get chord from mesh for dual-axis plot
    _, mesh = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    chord = None
    if mesh is not None:
        m = np.array(mesh)
        if m.ndim == 3:
            le = m[0, :, 0]
            te = m[-1, :, 0]
            chord = np.abs(te - le)

    span_frac = np.linspace(0, 1, len(twist))
    if mirror:
        span_frac, twist = mirror_spanwise(span_frac, twist)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    ax.plot(span_frac, twist, "b-o", markersize=4, label="Twist")
    ax.set_xlabel("Span Fraction (root to tip)")
    ax.set_ylabel("Twist (deg)", color="b")
    ax.tick_params(axis="y", labelcolor="b")
    ax.set_title("Twist & Chord Distribution")
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

    # Chord on secondary axis
    if chord is not None:
        chord_frac = np.linspace(0, 1, len(chord))
        if mirror:
            chord_frac, chord = mirror_spanwise(chord_frac, chord)
        ax2 = ax.twinx()
        ax2.plot(chord_frac, chord, "r-s", markersize=3, label="Chord")
        ax2.set_ylabel("Chord (m)", color="r")
        ax2.tick_params(axis="y", labelcolor="r")
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="best")

    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Thickness (tube model)
# ---------------------------------------------------------------------------


def plot_thickness(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise spar thickness distribution (tube model).

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    name, thickness = find_first_output(
        case,
        f"{surf}.thickness_cp",
        f"*{surf}*thickness_cp",
        f"*{surf}*thickness",
    )

    if thickness is None:
        raise ValueError("Could not find thickness data in recorder")

    thickness = np.array(thickness).flatten()
    logger.info("Thickness plot using variable: %s, shape: %s", name, thickness.shape)

    span_frac = np.linspace(0, 1, len(thickness))
    if mirror:
        span_frac, thickness = mirror_spanwise(span_frac, thickness)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    ax.plot(span_frac, thickness * 1000, "b-o", markersize=4)
    ax.set_xlabel("Span Fraction (root to tip)")
    ax.set_ylabel("Thickness (mm)")
    ax.set_title("Spanwise Spar Thickness Distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Von Mises stress (new)
# ---------------------------------------------------------------------------


def plot_vonmises(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    yield_stress: float | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise von Mises stress with yield limit.

    Shows the peak von Mises stress across the cross-section at each
    spanwise station. Adds a horizontal dashed line at the yield stress
    if provided.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        yield_stress: Yield stress in Pa for limit line. Auto-detected
            from model options if not provided.
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    name, vm = find_first_output(
        case,
        f"*{surf}_perf.vonmises",
        f"*vonmises",
    )

    if vm is None:
        raise ValueError("Could not find von Mises data in recorder")

    vm = np.array(vm)
    logger.info("Von Mises plot using variable: %s, shape: %s", name, vm.shape)

    # Take max across cross-section (axis=1) following upstream
    if vm.ndim == 2:
        vm_peak = np.max(vm, axis=1)
    else:
        vm_peak = vm.flatten()

    span_frac = np.linspace(0, 1, len(vm_peak))
    if mirror:
        span_frac, vm_peak = mirror_spanwise(span_frac, vm_peak)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    ax.plot(span_frac, vm_peak, "b-o", markersize=4, label="Von Mises")

    # Yield stress limit line
    if yield_stress is None:
        # Try to auto-detect from model options
        try:
            sys_options = reader.list_model_options(out_stream=None)
            for key in sys_options:
                try:
                    surface = sys_options[key].get("surface", {})
                    ys = surface.get("yield")
                    if ys is not None:
                        yield_stress = float(ys)
                        break
                except (TypeError, AttributeError):
                    pass
        except Exception:
            pass

    if yield_stress is not None:
        ax.axhline(
            y=yield_stress, color="r", linewidth=2, linestyle="--",
            label=f"Yield stress ({yield_stress:.0e} Pa)",
        )
        ax.set_ylim(0, yield_stress * 1.1)

    ax.set_xlabel("Span Fraction")
    ax.set_ylabel("Von Mises Stress (Pa)")
    ax.set_title("Spanwise Von Mises Stress")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Skin + spar thickness (wingbox model, new)
# ---------------------------------------------------------------------------


def plot_skin_spar(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise skin and spar thickness (wingbox models).

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    _, skin = find_first_output(
        case,
        f"*{surf}.skin_thickness",
        f"*skin_thickness*",
    )
    _, spar = find_first_output(
        case,
        f"*{surf}.spar_thickness",
        f"*spar_thickness*",
    )

    if skin is None and spar is None:
        raise ValueError("Could not find skin/spar thickness data in recorder")

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    if skin is not None:
        skin = np.array(skin).flatten()
        span_frac = np.linspace(0, 1, len(skin))
        if mirror:
            sf, sk = mirror_spanwise(span_frac, skin)
        else:
            sf, sk = span_frac, skin
        ax.plot(sf, sk * 1000, "b-o", markersize=4, label="Skin")

    if spar is not None:
        spar = np.array(spar).flatten()
        span_frac = np.linspace(0, 1, len(spar))
        if mirror:
            sf, sp = mirror_spanwise(span_frac, spar)
        else:
            sf, sp = span_frac, spar
        ax.plot(sf, sp * 1000, "g-s", markersize=4, label="Spar")

    ax.set_xlabel("Span Fraction")
    ax.set_ylabel("Thickness (mm)")
    ax.set_title("Skin and Spar Thickness")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Thickness-to-chord ratio (new)
# ---------------------------------------------------------------------------


def plot_t_over_c(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = True,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise thickness-to-chord ratio distribution.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"
    name, toc = find_first_output(
        case,
        f"*{surf}.t_over_c",
        f"*t_over_c",
    )

    if toc is None:
        raise ValueError("Could not find t/c data in recorder")

    toc = np.array(toc).flatten()
    logger.info("t/c plot using variable: %s, shape: %s", name, toc.shape)

    span_frac = np.linspace(0, 1, len(toc))
    if mirror:
        span_frac, toc = mirror_spanwise(span_frac, toc)

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    ax.plot(span_frac, toc, "k-o", markersize=4)
    ax.set_xlabel("Span Fraction")
    ax.set_ylabel("Thickness to Chord Ratio")
    ax.set_title("Spanwise t/c Distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


# ---------------------------------------------------------------------------
# Mesh mirroring helper
# ---------------------------------------------------------------------------


def _mirror_mesh(mesh: np.ndarray) -> np.ndarray:
    """Mirror a half-span mesh to produce a full-span mesh.

    Args:
        mesh: Array of shape (num_x, num_y, 3).

    Returns:
        Full-span mesh array.
    """
    # Check if this looks like a half-span mesh (all y same sign)
    y_vals = mesh[0, :, 1]
    if np.all(y_vals >= -1e-8) or np.all(y_vals <= 1e-8):
        mirror = mesh.copy()
        mirror[:, :, 1] *= -1.0
        mirror = mirror[:, ::-1, :][:, 1:, :]  # remove duplicate at symmetry plane
        return np.concatenate([mirror, mesh], axis=1)
    return mesh


# ---------------------------------------------------------------------------
# Plot provider dicts
# ---------------------------------------------------------------------------


OAS_AERO_PLOTS: dict[str, callable] = {
    "planform": plot_planform,
    "lift": plot_lift_distribution,
    "twist": plot_twist,
}

OAS_AEROSTRUCT_PLOTS: dict[str, callable] = {
    **OAS_AERO_PLOTS,
    "struct": plot_structural_deformation,
    "thickness": plot_thickness,
    "vonmises": plot_vonmises,
    "skin_spar": plot_skin_spar,
    "t_over_c": plot_t_over_c,
}
