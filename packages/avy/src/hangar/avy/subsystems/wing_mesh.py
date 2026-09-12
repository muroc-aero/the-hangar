"""Parametric wing mesh for the OAS wing-mass subsystem (WP4).

Upstream's ``user_mesh()`` is already a parameterized two-segment (kink)
planform builder -- with the advanced-single-aisle constants baked in.
``parametric_mesh`` lifts those constants into arguments, executing the
same operations in the same order so that with ``UPSTREAM_PLANFORM`` it
reproduces the upstream mesh bit-for-bit (regression-tested at 1e-10).

``planform_from_deck`` derives a *simple-trapezoid* planform from a
FLOPS deck's ``Aircraft.Wing.{SPAN, AREA, TAPER_RATIO, SWEEP}``: the kink
chord sits on the straight taper line (a degenerate kink), and the deck
sweep -- nominally quarter-chord in FLOPS -- is applied as leading-edge
sweep. Cruder than a real multi-segment FLOPS planform definition, and
said so in the run's mesh-source finding; it makes the wingbox mass
*planform-consistent* with the deck rather than always the
advanced-single-aisle wing.

Pure numpy -- importable in any venv (deck reads happen in the caller).
"""

from __future__ import annotations

import numpy as np

# The constants upstream bakes into user_mesh() (advanced single aisle).
UPSTREAM_PLANFORM: dict[str, float] = {
    "half_span_m": 17.9573,
    "kink_location_m": 4.9544,
    "root_chord_m": 5.5668,
    "kink_chord_m": 4.1302,
    "tip_chord_m": 1.5084,
    "inboard_LE_sweep_deg": 25.0,
    "outboard_LE_sweep_deg": 25.0,
}

PLANFORM_KEYS = tuple(UPSTREAM_PLANFORM)


def parametric_mesh(
    half_span_m: float,
    kink_location_m: float,
    root_chord_m: float,
    kink_chord_m: float,
    tip_chord_m: float,
    inboard_LE_sweep_deg: float,
    outboard_LE_sweep_deg: float,
    nx: int = 2,
    ny_inboard: int = 3,
    ny_outboard: int = 5,
) -> np.ndarray:
    """Upstream ``user_mesh()`` with the planform constants as arguments.

    Same array operations in the same order as upstream (v1.0.1), so
    identical inputs give an identical mesh. Right half only (symmetry),
    indexing [chordwise, spanwise, xyz], z=0 (no dihedral).
    """
    half_span = half_span_m
    kink_location = kink_location_m
    root_chord = root_chord_m
    kink_chord = kink_chord_m
    tip_chord = tip_chord_m
    inboard_LE_sweep = inboard_LE_sweep_deg
    outboard_LE_sweep = outboard_LE_sweep_deg

    mesh = np.zeros((nx, ny_inboard + ny_outboard - 1, 3))
    mesh[:, :, 2] = 0.0

    mesh[:, :ny_outboard, 1] = np.linspace(half_span, kink_location, ny_outboard)
    mesh[:, ny_outboard : ny_outboard + ny_inboard, 1] = np.linspace(
        kink_location, 0, ny_inboard
    )[1:]

    x_LE = np.zeros(ny_inboard + ny_outboard - 1)
    array_for_inboard_leading_edge_x_coord = np.linspace(
        0, kink_location, ny_inboard
    ) * np.tan(inboard_LE_sweep / 180.0 * np.pi)
    array_for_outboard_leading_edge_x_coord = (
        np.linspace(0, half_span - kink_location, ny_outboard)
        * np.tan(outboard_LE_sweep / 180.0 * np.pi)
        + np.ones(ny_outboard) * array_for_inboard_leading_edge_x_coord[-1]
    )
    x_LE[:ny_inboard] = array_for_inboard_leading_edge_x_coord
    x_LE[ny_inboard : ny_inboard + ny_outboard] = array_for_outboard_leading_edge_x_coord[1:]

    x_TE = np.zeros(ny_inboard + ny_outboard - 1)
    array_for_inboard_trailing_edge_x_coord = np.linspace(
        array_for_inboard_leading_edge_x_coord[0] + root_chord,
        array_for_inboard_leading_edge_x_coord[-1] + kink_chord,
        ny_inboard,
    )
    array_for_outboard_trailing_edge_x_coord = np.linspace(
        array_for_outboard_leading_edge_x_coord[0] + kink_chord,
        array_for_outboard_leading_edge_x_coord[-1] + tip_chord,
        ny_outboard,
    )
    x_TE[:ny_inboard] = array_for_inboard_trailing_edge_x_coord
    x_TE[ny_inboard : ny_inboard + ny_outboard] = array_for_outboard_trailing_edge_x_coord[1:]

    for i in range(0, ny_inboard + ny_outboard - 1):
        mesh[:, i, 0] = np.linspace(np.flip(x_LE)[i], np.flip(x_TE)[i], nx)

    return mesh


def trapezoid_planform(
    span_m: float,
    area_m2: float,
    taper_ratio: float,
    sweep_deg: float,
    kink_eta: float = 0.3,
) -> dict[str, float]:
    """Simple-trapezoid planform parameters from headline wing quantities.

    The kink chord sits on the straight taper line (degenerate kink), and
    the given sweep is applied to both segments as LE sweep. Pure math --
    usable with values from any source.
    """
    if not (0.0 < kink_eta < 1.0):
        raise ValueError(f"kink_eta must be in (0, 1), got {kink_eta}")
    if span_m <= 0 or area_m2 <= 0 or not (0.0 < taper_ratio <= 1.0):
        raise ValueError(
            f"Implausible planform: span={span_m} m, area={area_m2} m^2, "
            f"taper_ratio={taper_ratio}"
        )
    half_span = span_m / 2.0
    root_chord = 2.0 * area_m2 / (span_m * (1.0 + taper_ratio))
    tip_chord = taper_ratio * root_chord
    kink_chord = root_chord + (tip_chord - root_chord) * kink_eta
    return {
        "half_span_m": half_span,
        "kink_location_m": kink_eta * half_span,
        "root_chord_m": root_chord,
        "kink_chord_m": kink_chord,
        "tip_chord_m": tip_chord,
        "inboard_LE_sweep_deg": sweep_deg,
        "outboard_LE_sweep_deg": sweep_deg,
    }


def planform_from_deck(aviary_values, kink_eta: float = 0.3) -> dict[str, float]:
    """Derive the simple-trapezoid planform from a deck's AviaryValues."""
    from aviary.variable_info.variables import Aircraft

    return trapezoid_planform(
        span_m=float(aviary_values.get_val(Aircraft.Wing.SPAN, "m")),
        area_m2=float(aviary_values.get_val(Aircraft.Wing.AREA, "m**2")),
        taper_ratio=float(aviary_values.get_val(Aircraft.Wing.TAPER_RATIO, "unitless")),
        sweep_deg=float(aviary_values.get_val(Aircraft.Wing.SWEEP, "deg")),
        kink_eta=kink_eta,
    )


def mesh_sanity_issues(mesh: np.ndarray) -> list[str]:
    """Structural sanity checks for a generated mesh; empty list == sane."""
    issues = []
    if not np.all(np.isfinite(mesh)):
        issues.append("mesh contains non-finite values")
        return issues
    spanwise = mesh[0, :, 1]
    if not np.all(np.diff(spanwise) < 0):
        issues.append("spanwise stations not monotonically decreasing (tip -> root)")
    chords = mesh[-1, :, 0] - mesh[0, :, 0]
    if not np.all(chords > 0):
        issues.append("non-positive chord lengths")
    return issues
