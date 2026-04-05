"""Generic plot types that work for any OpenMDAO problem.

These plots rely only on standard OpenMDAO CaseReader data
(driver cases, objectives, design variables, constraints) and
do not assume any specific component type.

Matches the oas-cli opt_history and opt_dv_evolution style:
constraint traces on secondary axis, initial/final/change%
subtitle, proper figure sizing.
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

# Match oas-cli figure sizing
_FIG_WIDTH = 6.0
_FIG_HEIGHT = 3.6


def plot_convergence(
    recorder_path: Path,
    **kwargs,
) -> plt.Figure:
    """Plot optimization convergence with constraint traces.

    Matches the oas-cli opt_history style:
    - Objective on primary y-axis
    - Constraint traces on secondary y-axis (dashed, colored)
    - Subtitle with initial, final, and percent change

    Args:
        recorder_path: Path to OpenMDAO recorder file.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")

    import openmdao.api as om
    reader = om.CaseReader(str(recorder_path))

    driver_cases = reader.list_cases("driver", recurse=False, out_stream=None)
    if len(driver_cases) < 2:
        raise ValueError(
            f"Need at least 2 driver cases for convergence plot, "
            f"got {len(driver_cases)}"
        )

    # Extract objective and constraint histories
    iterations = []
    obj_values = []
    obj_name = None
    constraint_history: dict[str, list[float]] = {}

    for i, case_id in enumerate(driver_cases):
        case = reader.get_case(case_id)

        # Auto-detect objective
        if obj_name is None:
            try:
                objectives = case.get_objectives(scaled=False)
                if objectives:
                    obj_name = list(objectives.keys())[0]
            except Exception:
                pass

            # Fallback: pattern match
            if obj_name is None:
                outputs = case.list_outputs(out_stream=None, return_format="dict")
                for pattern in ["*structural_mass*", "*fuel_burn*", "*CD*", "*drag*"]:
                    for name, info in outputs.items():
                        if fnmatch.fnmatch(name, pattern):
                            val = info.get("val", info.get("value"))
                            if val is not None and np.atleast_1d(val).size == 1:
                                obj_name = name
                                break
                    if obj_name:
                        break

                if obj_name is None:
                    for name, info in outputs.items():
                        val = info.get("val", info.get("value"))
                        if val is not None and np.atleast_1d(val).size == 1:
                            obj_name = name
                            break

        # Get objective value
        if obj_name:
            try:
                objectives = case.get_objectives(scaled=False)
                val = objectives.get(obj_name)
                if val is not None:
                    iterations.append(i)
                    obj_values.append(float(np.atleast_1d(val).flat[0]))
            except Exception:
                pass

        # Get constraint values
        try:
            constraints = case.get_constraints(scaled=False)
            for con_name, con_val in constraints.items():
                short_name = con_name.split(".")[-1]
                v = float(np.atleast_1d(con_val).flat[0])
                constraint_history.setdefault(short_name, []).append(v)
        except Exception:
            pass

    logger.info("Convergence plot: %d iterations, objective: %s", len(iterations), obj_name)

    fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))

    # Short name for y-axis label
    obj_short = obj_name.split(".")[-1] if obj_name else "Objective"

    if obj_values and len(obj_values) > 1:
        ax.plot(iterations, obj_values, "b-o", markersize=4, linewidth=1.5)
        ax.set_xlabel("Optimizer iteration")
        ax.set_ylabel(obj_short)

        # Subtitle with initial/final/change%
        pct = 100.0 * (obj_values[-1] - obj_values[0]) / max(abs(obj_values[0]), 1e-300)
        ax.set_title(
            f"Initial: {obj_values[0]:.4g}   Final: {obj_values[-1]:.4g}   "
            f"Change: {pct:+.1f}%",
            fontsize=8,
        )
    elif obj_values:
        ax.plot([0], obj_values[:1], "bo", markersize=8)
        ax.set_xlabel("Optimizer iteration")
        ax.set_ylabel(obj_short)
        ax.set_title(f"Recorded: {obj_values[0]:.4g}", fontsize=8)
    else:
        ax.text(0.5, 0.5, "No objective trace captured.",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=10, color="gray")
        ax.axis("off")

    # Constraint traces on secondary y-axis
    if constraint_history and obj_values and len(obj_values) > 1:
        _CON_COLORS = {
            "CL": "steelblue", "CD": "orange", "CM": "purple",
            "failure": "red", "L_equals_W": "green", "S_ref": "teal",
        }
        ax2 = ax.twinx()
        for con_name, con_vals in constraint_history.items():
            color = _CON_COLORS.get(con_name, "gray")
            citers = list(range(len(con_vals)))
            ax2.plot(citers, con_vals, "--", linewidth=1.2, color=color,
                     label=con_name, alpha=0.7)
        ax2.set_ylabel("Constraint value", fontsize=8)
        ax2.legend(fontsize=6, loc="center right")

    ax.grid(True, alpha=0.3)
    title = "Optimization Convergence"
    if run_id:
        title += f"\n({run_id})"
    fig.suptitle(title, fontsize=9, y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


def plot_dv_evolution(
    recorder_path: Path,
    **kwargs,
) -> plt.Figure:
    """Plot design variable values across optimization iterations.

    Shows individual elements for vector DVs plus a mean trace (dashed).
    Scalar DVs get a single line. All plotted as actual values.

    Args:
        recorder_path: Path to OpenMDAO recorder file.

    Keyword Args:
        vector_dv_mode: How to display vector DVs. ``"all"`` (default)
            shows individual elements plus the mean. ``"mean"`` shows
            only the mean of the vector.

    Returns:
        matplotlib Figure.
    """
    run_id = kwargs.get("run_id", "")
    vector_dv_mode = kwargs.get("vector_dv_mode", "all")

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

    # Collect DV values across iterations, tracking which are vector DVs
    # element_traces: individual elements for vector DVs
    # mean_traces: mean for vector DVs (dashed overlay)
    # scalar_traces: scalar DVs
    element_traces: dict[str, list[float]] = {}
    mean_traces: dict[str, list[float]] = {}
    scalar_traces: dict[str, list[float]] = {}
    vector_dv_names: set[str] = set()
    iterations = list(range(len(driver_cases)))

    for case_id in driver_cases:
        case = reader.get_case(case_id)
        try:
            dvs = case.get_design_vars(scaled=False)
        except Exception:
            break

        for dv_name, val in dvs.items():
            arr = np.atleast_1d(val)
            short = dv_name.split(".")[-1]
            if arr.size == 1:
                scalar_traces.setdefault(short, []).append(float(arr.flat[0]))
            else:
                vector_dv_names.add(short)
                # Individual elements (cap at 10)
                for idx in range(min(arr.size, 10)):
                    key = f"{short}[{idx}]"
                    element_traces.setdefault(key, []).append(float(arr.flat[idx]))
                # Mean
                mean_traces.setdefault(short, []).append(float(arr.mean()))

    all_traces = {**element_traces, **scalar_traces}
    if not all_traces:
        raise ValueError("Could not extract DV history from recorder")

    fig, ax = plt.subplots(figsize=(_FIG_WIDTH, _FIG_HEIGHT))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    color_idx = 0

    # Plot vector DV elements with their mean
    for dv_name in sorted(vector_dv_names):
        if vector_dv_mode == "all":
            # Individual elements (solid, thin)
            elem_keys = [k for k in element_traces if k.startswith(f"{dv_name}[")]
            for key in sorted(elem_keys):
                values = element_traces[key]
                color = colors[color_idx % len(colors)]
                ax.plot(iterations[:len(values)], values, "-o", markersize=2,
                        linewidth=1.0, label=key, color=color)
                color_idx += 1

        # Mean trace
        if dv_name in mean_traces:
            values = mean_traces[dv_name]
            if vector_dv_mode == "all":
                # Dashed overlay when elements are also shown
                ax.plot(iterations[:len(values)], values, "--", markersize=0,
                        linewidth=2.0, label=f"{dv_name} (mean)", color="black",
                        alpha=0.6)
            else:
                # Primary trace when mean-only
                color = colors[color_idx % len(colors)]
                ax.plot(iterations[:len(values)], values, "-o", markersize=3,
                        linewidth=1.5, label=f"{dv_name} (mean)", color=color)
                color_idx += 1

    # Plot scalar DVs
    for label, values in sorted(scalar_traces.items()):
        color = colors[color_idx % len(colors)]
        ax.plot(iterations[:len(values)], values, "-o", markersize=3,
                linewidth=1.5, label=label, color=color)
        color_idx += 1

    n_dvs = len(vector_dv_names) + len(scalar_traces)
    n_total = len(element_traces) + len(scalar_traces)

    ax.set_xlabel("Optimizer iteration")
    ax.set_ylabel("Design Variable Value")
    ax.set_title(f"{n_dvs} design variable(s), {n_total} trace(s)", fontsize=8)
    ax.legend(fontsize=6, loc="best")
    ax.grid(True, alpha=0.3)

    title = "Design Variable Evolution"
    if run_id:
        title += f"\n({run_id})"
    fig.suptitle(title, fontsize=9, y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return fig


GENERIC_PLOTS: dict[str, callable] = {
    "convergence": plot_convergence,
    "dv_evolution": plot_dv_evolution,
}
