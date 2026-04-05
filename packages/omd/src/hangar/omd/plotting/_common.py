"""Shared helpers for plotting modules.

Variable discovery via CaseReader and common data transforms
used across domain-specific plot modules.
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


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
