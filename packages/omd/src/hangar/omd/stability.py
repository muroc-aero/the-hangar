"""Stability derivative computation via finite differencing.

Computes CL_alpha, CM_alpha, and static margin by perturbing alpha
on an already-converged OpenMDAO problem.
"""

from __future__ import annotations

import logging

import numpy as np
import openmdao.api as om

logger = logging.getLogger(__name__)


def compute_stability(
    prob: om.Problem,
    metadata: dict,
    delta_alpha: float = 1e-4,
) -> dict:
    """Compute longitudinal stability derivatives via forward finite difference.

    Perturbs alpha by delta_alpha degrees, re-runs the model, and computes
    CL_alpha and CM_alpha. Static margin is computed as -CM_alpha / CL_alpha.

    The problem is restored to its original state after computation.

    Args:
        prob: Converged OpenMDAO Problem (run_model or run_driver completed).
        metadata: Factory metadata with point_name, surface_names.
        delta_alpha: Perturbation in degrees (default 1e-4).

    Returns:
        Dict with CL_alpha_per_deg, CM_alpha_per_deg, CL_alpha_per_rad,
        CM_alpha_per_rad, static_margin, and baseline values.
    """
    point_name = metadata.get("point_name", "AS_point_0")
    surface_names = metadata.get("surface_names", [])

    # Determine CL/CM extraction paths
    is_aero_only = point_name.startswith("aero_")
    if is_aero_only:
        cl_path = f"{point_name}.CL"
        cm_path = f"{point_name}.CM"
    elif surface_names:
        surf = surface_names[0]
        cl_path = f"{point_name}.{surf}_perf.CL"
        cm_path = f"{point_name}.CM"
    else:
        cl_path = f"{point_name}.CL"
        cm_path = f"{point_name}.CM"

    # Read baseline values
    alpha_0 = float(prob.get_val("alpha", units="deg")[0])
    CL_0 = float(np.asarray(prob.get_val(cl_path)).ravel()[0])
    cm_arr = np.asarray(prob.get_val(cm_path)).ravel()
    CM_0 = float(cm_arr[1]) if len(cm_arr) > 1 else float(cm_arr[0])

    # Perturb and re-run
    prob.set_val("alpha", alpha_0 + delta_alpha, units="deg")
    prob.run_model()

    CL_1 = float(np.asarray(prob.get_val(cl_path)).ravel()[0])
    cm_arr = np.asarray(prob.get_val(cm_path)).ravel()
    CM_1 = float(cm_arr[1]) if len(cm_arr) > 1 else float(cm_arr[0])

    # Compute derivatives (per degree)
    CL_alpha_deg = (CL_1 - CL_0) / delta_alpha
    CM_alpha_deg = (CM_1 - CM_0) / delta_alpha

    # Convert to per radian
    CL_alpha_rad = CL_alpha_deg * 180.0 / np.pi
    CM_alpha_rad = CM_alpha_deg * 180.0 / np.pi

    # Static margin
    if abs(CL_alpha_deg) > 1e-12:
        static_margin = -CM_alpha_deg / CL_alpha_deg
    else:
        static_margin = None

    # Restore original state
    prob.set_val("alpha", alpha_0, units="deg")
    prob.run_model()

    return {
        "alpha_deg": alpha_0,
        "CL": CL_0,
        "CM": CM_0,
        "CL_alpha_per_deg": round(CL_alpha_deg, 8),
        "CM_alpha_per_deg": round(CM_alpha_deg, 8),
        "CL_alpha_per_rad": round(CL_alpha_rad, 6),
        "CM_alpha_per_rad": round(CM_alpha_rad, 6),
        "static_margin": round(static_margin, 6) if static_margin is not None else None,
    }
