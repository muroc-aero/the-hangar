"""Generic plot types that work for any OpenMDAO problem.

These plots rely only on standard OpenMDAO CaseReader data
(driver cases, objectives, design variables) and do not
assume any specific component type.
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


def plot_convergence(
    recorder_path: Path,
    **kwargs,
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

    iterations = []
    obj_values = []
    obj_name = None

    for i, case_id in enumerate(driver_cases):
        case = reader.get_case(case_id)
        outputs = case.list_outputs(out_stream=None, return_format="dict")

        if obj_name is None:
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


def plot_dv_evolution(
    recorder_path: Path,
    **kwargs,
) -> plt.Figure:
    """Plot design variable values across optimization iterations.

    Shows one line per DV (or per DV element for arrays). Useful for
    diagnosing whether DVs are active, hitting bounds, or stuck.

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
            f"Need at least 2 driver cases for DV evolution plot, "
            f"got {len(driver_cases)}"
        )

    # Get DV names from the first case
    first_case = reader.get_case(driver_cases[0])
    try:
        desvars = first_case.get_design_vars(scaled=False)
    except Exception:
        raise ValueError("No design variables found in recorder")

    if not desvars:
        raise ValueError("No design variables found in recorder")

    # Collect DV values across iterations
    dv_history: dict[str, list[float]] = {}
    iterations = list(range(len(driver_cases)))

    for case_id in driver_cases:
        case = reader.get_case(case_id)
        try:
            dvs = case.get_design_vars(scaled=False)
        except Exception:
            break

        for dv_name, val in dvs.items():
            arr = np.atleast_1d(val)
            if arr.size == 1:
                key = dv_name.split(".")[-1]
                dv_history.setdefault(key, []).append(float(arr.flat[0]))
            else:
                # Array DV: one line per element
                for idx in range(min(arr.size, 10)):  # cap at 10 elements
                    key = f"{dv_name.split('.')[-1]}[{idx}]"
                    dv_history.setdefault(key, []).append(float(arr.flat[idx]))

    if not dv_history:
        raise ValueError("Could not extract DV history from recorder")

    fig, ax = plt.subplots(1, 1, figsize=(10, 6))

    for label, values in dv_history.items():
        ax.plot(iterations[:len(values)], values, "-o", markersize=3, label=label)

    ax.set_xlabel("Iteration")
    ax.set_ylabel("Design Variable Value")
    ax.set_title("Design Variable Evolution")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    return fig


GENERIC_PLOTS: dict[str, callable] = {
    "convergence": plot_convergence,
    "dv_evolution": plot_dv_evolution,
}
