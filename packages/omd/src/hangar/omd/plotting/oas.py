"""OAS-specific plot types for aero and aerostructural analyses.

Reads data from OpenMDAO recorder files and produces matplotlib
figures matching the oas-cli (sdk/viz/plotting.py) style and
data presentation conventions.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from hangar.omd.plotting._common import (
    detect_surface_name,
    find_first_output,
    find_outputs,
    get_reader_and_final_case,
    get_span_eta,
    mirror_spanwise,
    compute_elliptical_lift,
)

logger = logging.getLogger(__name__)

# Match oas-cli figure sizing (sdk/viz/plotting.py constants)
_FIG_WIDTH = 6.0   # inches -> 900 px at 150 DPI
_FIG_HEIGHT = 3.6  # inches -> 540 px at 150 DPI


def _make_fig(title: str, run_id: str = "", **fig_kwargs) -> tuple:
    """Create a figure with suptitle and run_id subtitle matching oas-cli."""
    fig_kwargs.setdefault("figsize", (_FIG_WIDTH, _FIG_HEIGHT))
    fig, ax = plt.subplots(**fig_kwargs)
    suptitle = title
    if run_id:
        suptitle += f"\n({run_id})"
    fig.suptitle(suptitle, fontsize=9, y=0.98)
    return fig, ax


# ---------------------------------------------------------------------------
# Planform
# ---------------------------------------------------------------------------


def plot_planform(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
    **kwargs,
) -> plt.Figure:
    """Plot a top-down view of the wing planform (LE/TE outline).

    Matches the oas-cli planform style: LE and TE as separate traces
    with root/tip chord connecting lines and optional deformed overlay.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror half-span mesh for full-span view.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    # Try deformed mesh first (aerostruct), then undeformed
    _, def_mesh_raw = find_first_output(
        case,
        f"*{surf}.def_mesh",
        f"*{surf}*def_mesh",
    )
    _, mesh_raw = find_first_output(
        case,
        f"*{surf}*.mesh",
        "*.mesh",
    )

    # Use deformed as primary display if available, else undeformed
    primary_raw = mesh_raw
    if primary_raw is None:
        raise ValueError("Could not find mesh data in recorder")

    mesh = np.array(primary_raw)
    logger.info("Planform plot using mesh shape: %s", mesh.shape)

    if mirror and mesh.ndim == 3:
        mesh = _mirror_mesh(mesh)

    fig, ax = _make_fig("Wing Planform", run_id)

    if mesh.ndim == 3:
        nx, ny, _ = mesh.shape

        # Leading edge and trailing edge outlines
        le = mesh[0, :, :]   # shape (ny, 3)
        te = mesh[-1, :, :]

        ax.plot(le[:, 1], le[:, 0], "b-", linewidth=1.5, label="LE (undeformed)")
        ax.plot(te[:, 1], te[:, 0], "b--", linewidth=1.0, label="TE (undeformed)")
        # Root chord
        ax.plot([le[0, 1], te[0, 1]], [le[0, 0], te[0, 0]], "b-", linewidth=0.8)
        # Tip chord
        ax.plot([le[-1, 1], te[-1, 1]], [le[-1, 0], te[-1, 0]], "b-", linewidth=0.8)

        # Deformed mesh overlay
        if def_mesh_raw is not None:
            def_mesh = np.array(def_mesh_raw)
            if mirror and def_mesh.ndim == 3:
                def_mesh = _mirror_mesh(def_mesh)
            if def_mesh.ndim == 3:
                def_le = def_mesh[0, :, :]
                def_te = def_mesh[-1, :, :]
                ax.plot(def_le[:, 1], def_le[:, 0], "r-", linewidth=1.5,
                        label="LE (deformed)", alpha=0.7)
                ax.plot(def_te[:, 1], def_te[:, 0], "r--", linewidth=1.0, alpha=0.7)

        ax.set_title(f"Mesh: {nx}x{ny} nodes", fontsize=8)

    ax.set_xlabel("Spanwise y  [m]")
    ax.set_ylabel("Chordwise x  [m]")
    if not mirror:
        ax.text(0.02, 0.02, "Half-span shown (symmetry)", transform=ax.transAxes,
                fontsize=7, color="gray", va="bottom")
    ax.legend(fontsize=7, loc="upper left")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

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
    plot_wing.py and oas-cli convention).

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    # Try sec_forces first (gives actual force distribution)
    name, values = find_first_output(
        case,
        f"*aero_states.{surf}_sec_forces",
        f"*{surf}*sec_forces",
    )

    # Also get mesh for span coordinates and widths for normalization
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    _, widths = find_first_output(case, f"*{surf}.widths", f"*{surf}*widths")
    _, alpha_val = find_first_output(case, "*alpha*")
    _, rho_val = find_first_output(case, "prob_vars.rho", "*rho*")
    _, v_val = find_first_output(case, "prob_vars.v", "*v*")

    fig, ax = _make_fig("Lift Distribution", run_id)

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
            if mesh_raw is not None:
                m = np.array(mesh_raw)
                if m.ndim == 3:
                    _, span_mid, was_reversed = get_span_eta(m)
                    if was_reversed:
                        lift = lift[::-1]
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
            ax.plot(span_mid_full, ell_full, "--", color="g", linewidth=1.5, label="elliptical")

            ax.set_ylabel("Normalised lift  l(y)/q  [m]")
            ax.legend(fontsize=7)

            # Subtitle with data range
            d_min, d_max = float(lift.min()), float(lift.max())
            ax.set_title(f"[{d_min:.3f}, {d_max:.3f}]", fontsize=8)
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
        ax.set_xlabel("Normalised spanwise station eta = 2y/b  [--]   (0 = root, 1 = tip)")
        ax.set_xlim(0, 1)

    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


# ---------------------------------------------------------------------------
# Structural deformation (deflection profile)
# ---------------------------------------------------------------------------


def plot_structural_deformation(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
    **kwargs,
) -> plt.Figure:
    """Plot structural deflection profile (z-displacement vs normalized span).

    Matches oas-cli deflection_profile: shows vertical displacement from
    undeformed reference, not absolute z-position.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    _, def_mesh_raw = find_first_output(
        case,
        f"*{surf}.def_mesh",
        f"*{surf}*def_mesh",
    )
    _, orig_mesh_raw = find_first_output(
        case,
        f"*{surf}.mesh",
        f"{surf}.mesh",
    )

    if def_mesh_raw is None:
        raise ValueError("Could not find deformed mesh in recorder")

    def_mesh = np.array(def_mesh_raw)

    fig, ax = _make_fig("Deflection Profile", run_id)

    if def_mesh.ndim == 3:
        # Compute displacement from reference (not absolute position)
        z_def = def_mesh[0, :, 2]
        if orig_mesh_raw is not None:
            orig_mesh = np.array(orig_mesh_raw)
            if orig_mesh.ndim == 3:
                z_orig = orig_mesh[0, :, 2]
                deflection = z_def - z_orig
            else:
                deflection = z_def
        else:
            deflection = z_def

        # Use normalized span coordinates
        mesh_for_eta = np.array(orig_mesh_raw) if orig_mesh_raw is not None else def_mesh
        if mesh_for_eta.ndim == 3:
            node_eta, _, was_reversed = get_span_eta(mesh_for_eta)
            if was_reversed:
                deflection = deflection[::-1]
        else:
            node_eta = np.linspace(0, 1, len(deflection))

        if mirror:
            node_eta, deflection = mirror_spanwise(node_eta, deflection)

        # Use detected surface name for legend (not the glob pattern)
        label = surface_name or detect_surface_name(case) or "wing"
        ax.plot(node_eta, deflection, "-o", markersize=3, linewidth=1.5, label=label)

    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
    ax.set_ylabel("Vertical deflection  [m]")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


# ---------------------------------------------------------------------------
# Twist & Chord overlay
# ---------------------------------------------------------------------------


def plot_twist(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise twist and chord distribution on dual y-axes.

    Matches oas-cli twist_chord_overlay style.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
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

    # Get mesh for span coordinates and chord
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")

    chord = None
    span_twist = np.linspace(0, 1, len(twist))
    span_chord = None

    if mesh_raw is not None:
        m = np.array(mesh_raw)
        if m.ndim == 3:
            node_eta, _, was_reversed = get_span_eta(m)

            # Chord from mesh
            le_x = m[0, :, 0]
            te_x = m[-1, :, 0]
            chord = np.abs(te_x - le_x)
            if was_reversed:
                chord = chord[::-1]
            span_chord = node_eta

            # Twist span: use node_eta if twist length matches nodes,
            # otherwise linspace
            if len(twist) == len(node_eta):
                span_twist = node_eta
                if was_reversed:
                    twist = twist[::-1]

    if mirror:
        span_twist, twist = mirror_spanwise(span_twist, twist)

    suptitle = "Twist & Chord Distribution"
    if run_id:
        suptitle += f"\n({run_id})"
    fig, ax1 = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    fig.suptitle(suptitle, fontsize=9, y=0.98)

    color_tw = "tab:blue"
    ax1.plot(span_twist, twist, color=color_tw, linewidth=1.5,
             marker="o", markersize=3, label="Twist")
    ax1.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
    ax1.set_ylabel("Twist  [deg]", color=color_tw)
    ax1.tick_params(axis="y", labelcolor=color_tw)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

    # Chord on secondary axis
    ax2 = ax1.twinx()
    color_ch = "tab:red"
    if chord is not None and span_chord is not None:
        c_plot = chord
        s_plot = span_chord
        if mirror:
            s_plot, c_plot = mirror_spanwise(span_chord, chord)
        ax2.plot(s_plot, c_plot, color=color_ch, linewidth=1.5,
                 marker="s", markersize=3, label="Chord")
        ax2.set_ylabel("Chord  [m]", color=color_ch)
        ax2.tick_params(axis="y", labelcolor=color_ch)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    if lines1 or lines2:
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="best")

    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


# ---------------------------------------------------------------------------
# Thickness (tube model)
# ---------------------------------------------------------------------------


def plot_thickness(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
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
    run_id = kwargs.get("run_id", "")
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

    # Get mesh for span coordinates
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    if mesh_raw is not None:
        m = np.array(mesh_raw)
        if m.ndim == 3:
            _, elem_eta, was_reversed = get_span_eta(m)
            if len(thickness) == len(elem_eta):
                span_frac = elem_eta
                if was_reversed:
                    thickness = thickness[::-1]
            else:
                span_frac = np.linspace(0, 1, len(thickness))
        else:
            span_frac = np.linspace(0, 1, len(thickness))
    else:
        span_frac = np.linspace(0, 1, len(thickness))

    if mirror:
        span_frac, thickness = mirror_spanwise(span_frac, thickness)

    fig, ax = _make_fig("Spanwise Spar Thickness", run_id)
    ax.plot(span_frac, thickness * 1000, "b-o", markersize=4)
    ax.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
    ax.set_ylabel("Thickness (mm)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


# ---------------------------------------------------------------------------
# Von Mises stress
# ---------------------------------------------------------------------------


def plot_vonmises(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    yield_stress: float | None = None,
    mirror: bool = False,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise von Mises stress with yield limit.

    Shows the peak von Mises stress across the cross-section at each
    spanwise station. Units in MPa matching oas-cli convention.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        yield_stress: Yield stress in Pa for limit line. Auto-detected
            from model options if not provided.
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
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

    # Convert to MPa
    vm_peak_mpa = vm_peak / 1e6

    # Get mesh for span coordinates
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    if mesh_raw is not None:
        m = np.array(mesh_raw)
        if m.ndim == 3:
            _, elem_eta, was_reversed = get_span_eta(m)
            if len(vm_peak_mpa) == len(elem_eta):
                span_frac = elem_eta
                if was_reversed:
                    vm_peak_mpa = vm_peak_mpa[::-1]
            else:
                span_frac = np.linspace(0, 1, len(vm_peak_mpa))
        else:
            span_frac = np.linspace(0, 1, len(vm_peak_mpa))
    else:
        span_frac = np.linspace(0, 1, len(vm_peak_mpa))

    if mirror:
        span_frac, vm_peak_mpa = mirror_spanwise(span_frac, vm_peak_mpa)

    fig, ax = _make_fig("Stress Distribution", run_id)
    vm_label = surface_name or detect_surface_name(case) or "wing"
    ax.plot(span_frac, vm_peak_mpa, linewidth=2, label=vm_label)

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
        yield_mpa = yield_stress / 1e6
        # Try to read safety_factor from the model; fall back to kwargs or 1.5
        safety_factor = kwargs.get("safety_factor", None)
        if safety_factor is None:
            try:
                sys_options = reader.list_model_options(out_stream=None)
                for key in sys_options:
                    try:
                        surface = sys_options[key].get("surface", {})
                        sf = surface.get("safety_factor")
                        if sf is not None:
                            safety_factor = float(sf)
                            break
                    except (TypeError, AttributeError):
                        pass
            except Exception:
                pass
        if safety_factor is None:
            safety_factor = 1.5
        allowable_mpa = yield_mpa / safety_factor
        ax.axhline(
            y=allowable_mpa, color="r", linewidth=2, linestyle="--",
        )
        ax.set_ylim(0, max(float(vm_peak_mpa.max()), allowable_mpa) * 1.1)
        ax.text(0.075, 1.03, "failure limit", transform=ax.transAxes,
                color="r", fontsize=8)

    ax.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
    ax.set_ylabel("von Mises stress  [MPa]")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


def plot_failure(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
    **kwargs,
) -> plt.Figure:
    """Plot spanwise failure metric, auto-detecting composite vs isotropic.

    For composite surfaces (Tsai-Wu), plots dimensionless strength ratio
    with failure limit at 1.0/safety_factor. For isotropic (von Mises),
    delegates to plot_vonmises().

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        mirror: If True, mirror for full-span view.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    reader, case = get_reader_and_final_case(recorder_path)
    surf = surface_name or "*"

    # Try Tsai-Wu first (composite)
    _, tw = find_first_output(
        case,
        f"*{surf}_perf.tsaiwu_sr",
        f"*tsaiwu_sr",
    )

    if tw is not None:
        tw = np.array(tw)
        logger.info("Failure plot using Tsai-Wu, shape: %s", tw.shape)

        # Take max across plies/critical points per element (axis=1)
        if tw.ndim == 2:
            tw_peak = np.max(tw, axis=1)
        else:
            tw_peak = tw.flatten()

        # Get mesh for span coordinates
        _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
        if mesh_raw is not None:
            m = np.array(mesh_raw)
            if m.ndim == 3:
                _, elem_eta, was_reversed = get_span_eta(m)
                if len(tw_peak) == len(elem_eta):
                    span_frac = elem_eta
                    if was_reversed:
                        tw_peak = tw_peak[::-1]
                else:
                    span_frac = np.linspace(0, 1, len(tw_peak))
            else:
                span_frac = np.linspace(0, 1, len(tw_peak))
        else:
            span_frac = np.linspace(0, 1, len(tw_peak))

        if mirror:
            span_frac, tw_peak = mirror_spanwise(span_frac, tw_peak)

        fig, ax = _make_fig("Failure (Tsai-Wu)", run_id)
        label = surface_name or detect_surface_name(case) or "wing"
        ax.plot(span_frac, tw_peak, linewidth=2, label=label)

        # Failure limit: SR / safety_factor = 1.0 at failure
        safety_factor = kwargs.get("safety_factor", None)
        if safety_factor is None:
            try:
                sys_options = reader.list_model_options(out_stream=None)
                for key in sys_options:
                    try:
                        surface = sys_options[key].get("surface", {})
                        sf = surface.get("safety_factor")
                        if sf is not None:
                            safety_factor = float(sf)
                            break
                    except (TypeError, AttributeError):
                        pass
            except Exception:
                pass
        if safety_factor is None:
            safety_factor = 1.5

        limit = 1.0 / safety_factor
        ax.axhline(y=limit, color="r", linewidth=2, linestyle="--")
        ax.set_ylim(0, max(float(tw_peak.max()), limit) * 1.1)
        ax.text(0.075, 1.03, "failure limit", transform=ax.transAxes,
                color="r", fontsize=8)

        ax.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
        ax.set_ylabel("Tsai-Wu Strength Ratio  [--]")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        fig.tight_layout(rect=[0, 0, 1, 0.93])

        return fig

    # Fall back to von Mises (isotropic)
    return plot_vonmises(
        recorder_path,
        surface_name=surface_name,
        mirror=mirror,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Skin + spar thickness (wingbox model)
# ---------------------------------------------------------------------------


def plot_skin_spar(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
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
    run_id = kwargs.get("run_id", "")
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

    # Get mesh for span coordinates
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")

    fig, ax = _make_fig("Skin and Spar Thickness", run_id)

    if skin is not None:
        skin = np.array(skin).flatten()
        if mesh_raw is not None:
            m = np.array(mesh_raw)
            if m.ndim == 3:
                _, elem_eta, was_reversed = get_span_eta(m)
                if len(skin) == len(elem_eta):
                    sf = elem_eta
                    if was_reversed:
                        skin = skin[::-1]
                else:
                    sf = np.linspace(0, 1, len(skin))
            else:
                sf = np.linspace(0, 1, len(skin))
        else:
            sf = np.linspace(0, 1, len(skin))

        if mirror:
            sf, skin = mirror_spanwise(sf, skin)
        ax.plot(sf, skin * 1000, "b-o", markersize=4, label="Skin")

    if spar is not None:
        spar = np.array(spar).flatten()
        if mesh_raw is not None:
            m = np.array(mesh_raw)
            if m.ndim == 3:
                _, elem_eta, was_reversed = get_span_eta(m)
                if len(spar) == len(elem_eta):
                    sf = elem_eta
                    if was_reversed:
                        spar = spar[::-1]
                else:
                    sf = np.linspace(0, 1, len(spar))
            else:
                sf = np.linspace(0, 1, len(spar))
        else:
            sf = np.linspace(0, 1, len(spar))

        if mirror:
            sf, spar = mirror_spanwise(sf, spar)
        ax.plot(sf, spar * 1000, "g-s", markersize=4, label="Spar")

    ax.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
    ax.set_ylabel("Thickness (mm)")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


# ---------------------------------------------------------------------------
# Thickness-to-chord ratio
# ---------------------------------------------------------------------------


def plot_t_over_c(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    mirror: bool = False,
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
    run_id = kwargs.get("run_id", "")
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

    # Get mesh for span coordinates
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    if mesh_raw is not None:
        m = np.array(mesh_raw)
        if m.ndim == 3:
            _, elem_eta, was_reversed = get_span_eta(m)
            if len(toc) == len(elem_eta):
                span_frac = elem_eta
                if was_reversed:
                    toc = toc[::-1]
            else:
                span_frac = np.linspace(0, 1, len(toc))
        else:
            span_frac = np.linspace(0, 1, len(toc))
    else:
        span_frac = np.linspace(0, 1, len(toc))

    if mirror:
        span_frac, toc = mirror_spanwise(span_frac, toc)

    fig, ax = _make_fig("Spanwise t/c Distribution", run_id)
    ax.plot(span_frac, toc, "k-o", markersize=4)
    ax.set_xlabel("Normalised spanwise station eta  [--]   (0 = root, 1 = tip)")
    ax.set_ylabel("Thickness to Chord Ratio")
    ax.grid(True, alpha=0.3)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


# ---------------------------------------------------------------------------
# 3D Mesh visualization
# ---------------------------------------------------------------------------

# Figure sizing for 3D (matches oas-cli _FIG_3D constants)
_FIG_3D_WIDTH = 8.0    # inches -> 1200 px at 150 DPI
_FIG_3D_HEIGHT = 5.33  # inches -> ~800 px at 150 DPI


def _draw_tube_structure(ax, mesh, radius, thickness, fem_origin):
    """Draw coloured cylindrical FEM tube elements along the spar.

    Adapted from oas-cli sdk/viz/plotting.py and upstream plot_wing.py.
    Each element is a short cylinder segment coloured by normalised thickness.
    """
    import matplotlib.cm as cm

    radius = np.asarray(radius)
    thickness = np.asarray(thickness)
    t_max = float(thickness.max()) if thickness.max() > 0 else 1.0
    colors = thickness / t_max

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
    spar thickness.
    """
    import matplotlib.cm as cm

    spar_t = np.asarray(spar_thickness)
    t_max = float(spar_t.max()) if spar_t.max() > 0 else 1.0
    colors = spar_t / t_max

    chords = mesh[-1, :, 0] - mesh[0, :, 0]
    comp = fem_origin * chords + mesh[0, :, 0]

    for i in range(len(spar_t)):
        half_h = max(chords[i], chords[i + 1]) * 0.08
        x_c0, x_c1 = comp[i], comp[i + 1]
        z0 = fem_origin * (mesh[-1, i, 2] - mesh[0, i, 2]) + mesh[0, i, 2]
        z1 = fem_origin * (mesh[-1, i + 1, 2] - mesh[0, i + 1, 2]) + mesh[0, i + 1, 2]
        y0, y1 = mesh[0, i, 1], mesh[0, i + 1, 1]

        xs = np.array([[x_c0, x_c1], [x_c0, x_c1]])
        ys = np.array([[y0, y1], [y0, y1]])
        zs = np.array([[z0 - half_h, z1 - half_h], [z0 + half_h, z1 + half_h]])

        col = np.full(xs.shape, colors[i])
        ax.plot_surface(xs, ys, zs, rstride=1, cstride=1,
                        facecolors=cm.viridis(col), linewidth=0)


def plot_mesh_3d(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    show_deflection: bool = True,
    deflection_scale: float = 2.0,
    **kwargs,
) -> plt.Figure:
    """Plot 3D wireframe mesh with optional structural FEM overlay.

    Matches the oas-cli mesh_3d plot: wireframe with tube/wingbox
    elements coloured by thickness, optional deformed mesh overlay.

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).
        show_deflection: Whether to overlay the deformed mesh.
        deflection_scale: Exaggeration factor for deflection.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    reader, case = get_reader_and_final_case(recorder_path)

    surf = surface_name or "*"

    # Get undeformed mesh
    _, mesh_raw = find_first_output(case, f"*{surf}*.mesh", "*.mesh")
    if mesh_raw is None:
        raise ValueError("Could not find mesh data in recorder")

    mesh = np.array(mesh_raw)
    if mesh.ndim != 3:
        raise ValueError(f"Expected 3D mesh array, got shape {mesh.shape}")

    # Get deformed mesh (aerostruct only)
    _, def_mesh_raw = find_first_output(
        case,
        f"*{surf}.def_mesh",
        f"*{surf}*def_mesh",
    )

    has_def = show_deflection and def_mesh_raw is not None

    fig = plt.figure(figsize=(_FIG_3D_WIDTH, _FIG_3D_HEIGHT))
    ax = fig.add_subplot(111, projection="3d")
    suptitle = "3D Wing Mesh"
    if run_id:
        suptitle += f"\n({run_id})"
    fig.suptitle(suptitle, fontsize=9, y=0.98)

    x = mesh[:, :, 0]
    y = mesh[:, :, 1]
    z = mesh[:, :, 2]

    if has_def:
        def_mesh = np.array(def_mesh_raw)
        def_mesh_vis = (def_mesh - mesh) * deflection_scale + def_mesh
        x_def = def_mesh_vis[:, :, 0]
        y_def = def_mesh_vis[:, :, 1]
        z_def = def_mesh_vis[:, :, 2]
        ax.plot_wireframe(x_def, y_def, z_def, rstride=1, cstride=1,
                          color="k", linewidth=0.8)
        ax.plot_wireframe(x, y, z, rstride=1, cstride=1, color="k",
                          alpha=0.3, linewidth=0.5)
    else:
        ax.plot_wireframe(x, y, z, rstride=1, cstride=1, color="k",
                          linewidth=0.8)

    # Structural FEM rendering
    struct_mesh = def_mesh_vis if has_def else mesh
    struct_label = None

    # Try to find structural data for tube model
    _, radius_raw = find_first_output(case, f"*{surf}.radius", f"*radius")
    _, thickness_raw = find_first_output(case, f"*{surf}.thickness", f"*thickness")

    if radius_raw is not None:
        radius = np.asarray(radius_raw).flatten()
        thickness = np.asarray(thickness_raw).flatten() if thickness_raw is not None else radius
        fem_origin = 0.35  # OAS default
        _draw_tube_structure(ax, struct_mesh, radius, thickness, fem_origin)
        struct_label = "tube (colour = thickness)"
    else:
        # Try wingbox
        _, spar_raw = find_first_output(case, f"*{surf}.spar_thickness", f"*spar_thickness")
        _, skin_raw = find_first_output(case, f"*{surf}.skin_thickness", f"*skin_thickness")
        if spar_raw is not None:
            spar_t = np.asarray(spar_raw).flatten()
            skin_t = np.asarray(skin_raw).flatten() if skin_raw is not None else spar_t
            fem_origin = 0.35
            _draw_wingbox_structure(ax, struct_mesh, spar_t, skin_t, fem_origin)
            struct_label = "wingbox (colour = spar thickness)"

    # Equal aspect ratio scaling
    all_pts = mesh
    if has_def:
        all_pts = np.concatenate([mesh, def_mesh_vis], axis=0)
    x_min, x_max = float(all_pts[:, :, 0].min()), float(all_pts[:, :, 0].max())
    y_min, y_max = float(all_pts[:, :, 1].min()), float(all_pts[:, :, 1].max())
    z_min, z_max = float(all_pts[:, :, 2].min()), float(all_pts[:, :, 2].max())
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

    # Subtitle
    nx, ny, _ = mesh.shape
    sub = f"Mesh: {nx}x{ny} nodes"
    if struct_label:
        sub += f"  |  {struct_label}"
    if has_def:
        max_defl = float(np.max(np.abs(np.array(def_mesh_raw)[:, :, 2] - mesh[:, :, 2])))
        sub += f"  |  max z-deflection: {max_defl:.4f} m (x{deflection_scale} exaggerated)"
    ax.set_title(sub, fontsize=8, y=-0.02)

    fig.subplots_adjust(left=0, right=1, bottom=0.02, top=0.90)

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
    "mesh_3d": plot_mesh_3d,
}

def plot_multipoint_comparison(
    recorder_path: Path,
    *,
    surface_name: str | None = None,
    **kwargs,
) -> plt.Figure:
    """Plot side-by-side cruise vs maneuver results for multipoint runs.

    Shows CL, failure, and deflection at each flight point. Reads data
    from AS_point_0 (cruise) and AS_point_1 (maneuver).

    Args:
        recorder_path: Path to OpenMDAO recorder file.
        surface_name: Surface name (auto-detected if None).

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    reader, case = get_reader_and_final_case(recorder_path)
    surf = surface_name or detect_surface_name(case) or "wing"

    # Collect per-point data
    point_data = {}
    for pt_idx, pt_label in enumerate(["cruise", "maneuver"]):
        pt = f"AS_point_{pt_idx}"
        data: dict = {}

        # CL
        _, cl_val = find_first_output(case, f"{pt}.{surf}_perf.CL",
                                       f"{pt}.CL")
        if cl_val is not None:
            data["CL"] = float(np.atleast_1d(cl_val).flat[0])

        # CD
        _, cd_val = find_first_output(case, f"{pt}.{surf}_perf.CD",
                                       f"{pt}.CD")
        if cd_val is not None:
            data["CD"] = float(np.atleast_1d(cd_val).flat[0])

        # Failure
        _, fail_val = find_first_output(case, f"{pt}.{surf}_perf.failure")
        if fail_val is not None:
            data["failure"] = float(np.max(fail_val))

        # Deflection
        _, disp_val = find_first_output(case, f"{pt}.{surf}.disp")
        if disp_val is not None:
            data["tip_deflection"] = float(disp_val[-1, 2])

        point_data[pt_label] = data

    if not any(point_data.values()):
        fig, ax = _make_fig("Multipoint Comparison (no data)", run_id)
        ax.text(0.5, 0.5, "No multipoint data found",
                transform=ax.transAxes, ha="center", va="center")
        return fig

    # Build comparison bar chart
    metrics = ["CL", "CD", "failure"]
    labels = list(point_data.keys())
    fig, axes = plt.subplots(1, len(metrics), figsize=(10, 3.6))
    suptitle = f"Multipoint Comparison\n({run_id})" if run_id else "Multipoint Comparison"
    fig.suptitle(suptitle, fontsize=9, y=0.98)

    colors = ["#2196F3", "#FF5722"]  # blue = cruise, orange = maneuver

    for ax, metric in zip(axes, metrics):
        vals = []
        for label in labels:
            vals.append(point_data[label].get(metric, 0.0))
        bars = ax.bar(labels, vals, color=colors[:len(labels)])
        ax.set_ylabel(metric)
        ax.set_title(metric, fontsize=8)
        # Add value labels
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{val:.4f}", ha="center", va="bottom", fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.90])
    return fig


def plot_drag_polar(
    polar_data: dict,
    *,
    output_path: Path | None = None,
    **kwargs,
) -> plt.Figure:
    """Plot a drag polar from sweep results.

    Creates three subplots: CL vs CD, CL vs alpha, and L/D vs alpha.

    Args:
        polar_data: Dict with alpha_deg, CL, CD, L_over_D, best_L_over_D.
        output_path: If provided, save the figure to this path.

    Returns:
        matplotlib Figure.
    """
    alpha = polar_data["alpha_deg"]
    CL = polar_data["CL"]
    CD = polar_data["CD"]
    LoD = [v if v is not None else 0 for v in polar_data["L_over_D"]]
    best = polar_data["best_L_over_D"]

    fig, axes = plt.subplots(3, 1, figsize=(6.0, 8.0))

    # CL vs CD (drag polar)
    ax = axes[0]
    ax.plot(CD, CL, "b-o", markersize=3, linewidth=1.5)
    if best.get("CD") and best.get("CL"):
        ax.plot(best["CD"], best["CL"], "r*", markersize=12,
                label=f"Best L/D = {best['L_over_D']:.1f}")
        ax.legend(fontsize=8)
    ax.set_xlabel("CD")
    ax.set_ylabel("CL")
    ax.set_title("Drag Polar")
    ax.grid(True, alpha=0.3)

    # CL vs alpha
    ax = axes[1]
    ax.plot(alpha, CL, "b-o", markersize=3, linewidth=1.5)
    ax.set_xlabel("alpha (deg)")
    ax.set_ylabel("CL")
    ax.set_title("Lift Curve")
    ax.grid(True, alpha=0.3)

    # L/D vs alpha
    ax = axes[2]
    ax.plot(alpha, LoD, "g-o", markersize=3, linewidth=1.5)
    if best.get("alpha_deg") is not None and best.get("L_over_D"):
        ax.plot(best["alpha_deg"], best["L_over_D"], "r*", markersize=12,
                label=f"Best L/D = {best['L_over_D']:.1f}")
        ax.legend(fontsize=8)
    ax.set_xlabel("alpha (deg)")
    ax.set_ylabel("L/D")
    ax.set_title("Lift-to-Drag Ratio")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")

    return fig


OAS_AEROSTRUCT_PLOTS: dict[str, callable] = {
    **OAS_AERO_PLOTS,
    "struct": plot_structural_deformation,
    "thickness": plot_thickness,
    "vonmises": plot_vonmises,
    "failure": plot_failure,
    "skin_spar": plot_skin_spar,
    "t_over_c": plot_t_over_c,
    "multipoint_comparison": plot_multipoint_comparison,
}
