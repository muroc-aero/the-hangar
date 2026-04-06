"""Drag polar computation by sweeping angle of attack.

Builds an analysis problem from a plan YAML, then sweeps alpha to produce
CL-CD tables, L/D curves, and the best L/D operating point.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from hangar.omd.materializer import materialize, apply_solvers_post_setup
from hangar.omd.plan_schema import load_and_validate

logger = logging.getLogger(__name__)


def run_polar(
    plan_path: Path,
    alpha_start: float = -5.0,
    alpha_end: float = 15.0,
    num_alpha: int = 21,
) -> dict:
    """Compute a drag polar by sweeping angle of attack.

    Loads the plan, materializes the problem in analysis mode (no optimizer),
    then sweeps alpha and extracts CL, CD, CM at each point.

    Args:
        plan_path: Path to plan YAML or assembled plan directory.
        alpha_start: Starting angle of attack in degrees.
        alpha_end: Ending angle of attack in degrees.
        num_alpha: Number of alpha points to evaluate.

    Returns:
        Dict with alpha_deg, CL, CD, CM, L_over_D arrays and best_L_over_D.
    """
    if num_alpha < 2:
        raise ValueError("num_alpha must be >= 2")

    # Load plan -- handle both file and directory
    plan_file = plan_path
    if plan_path.is_dir():
        from hangar.omd.assemble import assemble_plan
        result = assemble_plan(plan_path)
        if result["errors"]:
            raise ValueError(f"Plan assembly errors: {result['errors']}")
        plan = result["plan"]
    else:
        plan, errors = load_and_validate(plan_path)
        if errors:
            raise ValueError(f"Plan validation errors: {errors}")

    # Strip optimization config so materialize builds analysis-only
    plan.pop("design_variables", None)
    plan.pop("objective", None)
    plan.pop("constraints", None)

    prob, metadata = materialize(plan, recording_level="minimal")
    apply_solvers_post_setup(prob, metadata)

    # Determine extraction paths
    point_name = metadata.get("point_name", "AS_point_0")
    surface_names = metadata.get("surface_names", [])
    components = plan.get("components", [])
    component_type = components[0].get("type") if components else None

    is_aero_only = (
        component_type == "oas/AeroPoint"
        or point_name.startswith("aero_")
    )

    if is_aero_only:
        cl_path = f"{point_name}.CL"
        cd_path = f"{point_name}.CD"
        cm_path = f"{point_name}.CM"
    elif surface_names:
        surf = surface_names[0]
        cl_path = f"{point_name}.{surf}_perf.CL"
        cd_path = f"{point_name}.CD"
        cm_path = f"{point_name}.CM"
    else:
        cl_path = f"{point_name}.CL"
        cd_path = f"{point_name}.CD"
        cm_path = f"{point_name}.CM"

    alphas = np.linspace(alpha_start, alpha_end, num_alpha)
    CLs, CDs, CMs = [], [], []

    for a in alphas:
        prob.set_val("alpha", a, units="deg")
        prob.run_model()
        CLs.append(float(np.asarray(prob.get_val(cl_path)).ravel()[0]))
        CDs.append(float(np.asarray(prob.get_val(cd_path)).ravel()[0]))
        cm = np.asarray(prob.get_val(cm_path)).ravel()
        CMs.append(float(cm[1]) if len(cm) > 1 else float(cm[0]))

    prob.cleanup()

    # Compute L/D and find best point
    LoDs = [cl / cd if cd > 0 else None for cl, cd in zip(CLs, CDs)]
    valid_LoDs = [(i, v) for i, v in enumerate(LoDs) if v is not None]
    if valid_LoDs:
        best_idx, best_LoD = max(valid_LoDs, key=lambda x: x[1])
    else:
        best_idx, best_LoD = 0, None

    return {
        "alpha_deg": [round(float(a), 4) for a in alphas],
        "CL": [round(v, 6) for v in CLs],
        "CD": [round(v, 6) for v in CDs],
        "CM": [round(v, 6) for v in CMs],
        "L_over_D": [round(v, 4) if v is not None else None for v in LoDs],
        "best_L_over_D": {
            "alpha_deg": round(float(alphas[best_idx]), 4),
            "CL": round(CLs[best_idx], 6),
            "CD": round(CDs[best_idx], 6),
            "L_over_D": round(best_LoD, 4) if best_LoD else None,
        },
    }
