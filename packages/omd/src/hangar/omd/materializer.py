"""Materialize validated plan dicts into OpenMDAO Problems.

Takes a validated plan dictionary and produces a configured, ready-to-run
OpenMDAO Problem by looking up component factories, wiring connections,
configuring solvers, and setting up the optimizer driver.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import openmdao.api as om

from hangar.omd.registry import get_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recording levels
# ---------------------------------------------------------------------------

RECORDING_LEVELS: dict[str, dict] = {
    "minimal": {
        "record_desvars": False,
        "record_objectives": False,
        "record_constraints": False,
        "record_responses": False,
    },
    "driver": {
        "record_desvars": True,
        "record_objectives": True,
        "record_constraints": True,
        "record_responses": True,
    },
    "solver": {
        "record_desvars": True,
        "record_objectives": True,
        "record_constraints": True,
        "record_responses": True,
    },
    "full": {
        "record_desvars": True,
        "record_objectives": True,
        "record_constraints": True,
        "record_responses": True,
        "record_residuals": True,
    },
}

# Solver type name -> OpenMDAO class mapping
_NONLINEAR_SOLVERS: dict[str, type] = {
    "NewtonSolver": om.NewtonSolver,
    "NonlinearBlockGS": om.NonlinearBlockGS,
}

_LINEAR_SOLVERS: dict[str, type] = {
    "DirectSolver": om.DirectSolver,
    "LinearBlockGS": om.LinearBlockGS,
}

# Optimizer type name -> scipy optimizer name
_OPTIMIZERS: dict[str, str] = {
    "SLSQP": "SLSQP",
    "COBYLA": "COBYLA",
    "L-BFGS-B": "L-BFGS-B",
    "Nelder-Mead": "Nelder-Mead",
}


# ---------------------------------------------------------------------------
# Materializer
# ---------------------------------------------------------------------------


def materialize(
    plan: dict,
    recording_level: str = "driver",
    recorder_path: Path | None = None,
) -> tuple[om.Problem, dict]:
    """Convert a validated plan dict into a ready-to-run OpenMDAO Problem.

    Args:
        plan: Validated plan dictionary.
        recording_level: One of "minimal", "driver", "solver", "full".
        recorder_path: Path for OpenMDAO's SqliteRecorder. If None,
            uses a temp file.

    Returns:
        Tuple of (problem, metadata) where problem has setup() called
        and is ready for run_model() or run_driver(). Metadata contains
        point_name, surface_names, recorder_path, etc.
    """
    components = plan.get("components", [])
    operating_points = plan.get("operating_points", {})

    if not components:
        raise ValueError("Plan must contain at least one component")

    # For single-component plans, the factory builds the full problem
    if len(components) == 1:
        comp = components[0]
        factory = get_factory(comp["type"])
        prob, metadata = factory(comp["config"], operating_points)
    else:
        # Multi-component: each factory builds a problem, we need
        # to compose them. For now, only single-component is supported.
        raise NotImplementedError(
            "Multi-component plan materialization is not yet supported. "
            "Stage 2 will add this capability."
        )

    # Configure solvers
    _configure_solvers(prob, plan, metadata)

    # Configure optimization
    has_optimization = (
        plan.get("design_variables")
        and plan.get("objective")
    )
    if has_optimization:
        _configure_driver(prob, plan, metadata)

    # Setup the problem
    prob.setup()

    # Set initial values from metadata (factory-provided)
    for name, val in metadata.get("initial_values", {}).items():
        try:
            prob.set_val(name, val)
        except Exception:
            pass

    # Configure recorder after setup
    rec_path = _configure_recorder(prob, recording_level, recorder_path)
    metadata["recorder_path"] = rec_path

    return prob, metadata


# ---------------------------------------------------------------------------
# Solver configuration
# ---------------------------------------------------------------------------


def _configure_solvers(
    prob: om.Problem,
    plan: dict,
    metadata: dict,
) -> None:
    """Set nonlinear and linear solvers from plan config.

    For OAS aerostruct, solvers are applied to the coupled group
    inside the analysis point.
    """
    solver_config = plan.get("solvers")
    if not solver_config:
        return

    point_name = metadata.get("point_name", "AS_point_0")

    # Determine the target group for solvers
    # For aerostruct, it's the coupled group inside the point
    # We store the solver config and apply it after setup in a callback,
    # or we apply it to the model and let OAS use its defaults for the coupled group
    nl_config = solver_config.get("nonlinear")
    if nl_config:
        solver_type = nl_config["type"]
        options = nl_config.get("options", {})
        if solver_type in _NONLINEAR_SOLVERS:
            # Store for post-setup application
            metadata["_nl_solver"] = {"type": solver_type, "options": options}

    lin_config = solver_config.get("linear")
    if lin_config:
        solver_type = lin_config["type"]
        options = lin_config.get("options", {})
        if solver_type in _LINEAR_SOLVERS:
            metadata["_lin_solver"] = {"type": solver_type, "options": options}


def apply_solvers_post_setup(prob: om.Problem, metadata: dict) -> None:
    """Apply solver configuration after setup().

    For OAS aerostruct problems, the coupled group exists only after
    setup(). This function applies the configured solvers to the
    correct subsystem.
    """
    point_name = metadata.get("point_name", "AS_point_0")

    # Try to find the coupled group
    try:
        coupled = prob.model._get_subsystem(f"{point_name}.coupled")
    except Exception:
        coupled = None

    target = coupled if coupled is not None else prob.model

    nl_config = metadata.pop("_nl_solver", None)
    if nl_config:
        solver_cls = _NONLINEAR_SOLVERS[nl_config["type"]]
        solver = solver_cls()
        # Newton solver requires solve_subsystems to be explicitly set
        if nl_config["type"] == "NewtonSolver" and "solve_subsystems" not in nl_config["options"]:
            solver.options["solve_subsystems"] = True
        for key, val in nl_config["options"].items():
            solver.options[key] = val
        target.nonlinear_solver = solver

    lin_config = metadata.pop("_lin_solver", None)
    if lin_config:
        solver_cls = _LINEAR_SOLVERS[lin_config["type"]]
        solver = solver_cls()
        for key, val in lin_config["options"].items():
            solver.options[key] = val
        target.linear_solver = solver


# ---------------------------------------------------------------------------
# Optimizer / driver configuration
# ---------------------------------------------------------------------------


def _configure_driver(
    prob: om.Problem,
    plan: dict,
    metadata: dict,
) -> None:
    """Set up optimizer driver with DVs, constraints, and objective.

    Must be called before setup().
    """
    optimizer_config = plan.get("optimizer", {})
    opt_type = optimizer_config.get("type", "SLSQP")
    opt_options = optimizer_config.get("options", {})

    driver = om.ScipyOptimizeDriver()
    driver.options["optimizer"] = _OPTIMIZERS.get(opt_type, opt_type)
    driver.options["disp"] = False
    for key, val in opt_options.items():
        if key in ("maxiter",):
            driver.options[key] = val
        elif key == "ftol":
            driver.options["tol"] = val
        else:
            driver.options[key] = val
    prob.driver = driver

    # Design variables
    point_name = metadata.get("point_name", "AS_point_0")
    surface_names = metadata.get("surface_names", [])

    for dv in plan.get("design_variables", []):
        dv_name = dv["name"]
        path = _resolve_var_path(dv_name, point_name, surface_names)
        kwargs: dict = {}
        if "lower" in dv:
            kwargs["lower"] = dv["lower"]
        if "upper" in dv:
            kwargs["upper"] = dv["upper"]
        if "scaler" in dv:
            kwargs["scaler"] = dv["scaler"]
        if "ref" in dv:
            kwargs["ref"] = dv["ref"]
        if "ref0" in dv:
            kwargs["ref0"] = dv["ref0"]
        prob.model.add_design_var(path, **kwargs)

    # Constraints
    for con in plan.get("constraints", []):
        con_name = con["name"]
        path = _resolve_var_path(con_name, point_name, surface_names)
        kwargs = {}
        if "upper" in con:
            kwargs["upper"] = con["upper"]
        if "lower" in con:
            kwargs["lower"] = con["lower"]
        if "equals" in con:
            kwargs["equals"] = con["equals"]
        if "scaler" in con:
            kwargs["scaler"] = con["scaler"]
        prob.model.add_constraint(path, **kwargs)

    # Objective
    obj = plan.get("objective", {})
    if obj:
        obj_name = obj["name"]
        path = _resolve_var_path(obj_name, point_name, surface_names)
        kwargs = {}
        if "scaler" in obj:
            kwargs["scaler"] = obj["scaler"]
        prob.model.add_objective(path, **kwargs)


def _resolve_var_path(
    name: str,
    point_name: str,
    surface_names: list[str],
) -> str:
    """Resolve a short variable name to a full OpenMDAO path.

    If the name already contains dots (looks like a full path),
    return as-is. Otherwise, try common OAS conventions.
    """
    if "." in name:
        return name

    # Simple names that are promoted to top level
    if name in ("alpha", "v", "rho", "Mach_number", "re", "load_factor",
                "beta", "CT", "R", "W0", "speed_of_sound"):
        return name

    # Surface-specific DVs: try first surface
    if surface_names:
        surf = surface_names[0]
        # Common OAS DV patterns
        dv_map = {
            "twist_cp": f"{surf}.twist_cp",
            "thickness_cp": f"{surf}.thickness_cp",
            "chord_cp": f"{surf}.chord_cp",
            "spar_thickness_cp": f"{surf}.spar_thickness_cp",
            "skin_thickness_cp": f"{surf}.skin_thickness_cp",
            "t_over_c_cp": f"{surf}.t_over_c_cp",
        }
        if name in dv_map:
            return dv_map[name]

    return name


# ---------------------------------------------------------------------------
# Recorder configuration
# ---------------------------------------------------------------------------


def _configure_recorder(
    prob: om.Problem,
    recording_level: str,
    recorder_path: Path | None,
) -> Path:
    """Attach an SqliteRecorder to the problem.

    Args:
        prob: Problem (must have setup() called).
        recording_level: One of the RECORDING_LEVELS keys.
        recorder_path: Where to write. None uses a temp file.

    Returns:
        Path to the recorder database.
    """
    if recorder_path is None:
        fd, tmp = tempfile.mkstemp(suffix=".sql", prefix="omd_recorder_")
        import os
        os.close(fd)
        recorder_path = Path(tmp)
    else:
        recorder_path = Path(recorder_path)

    recorder = om.SqliteRecorder(str(recorder_path))

    level_opts = RECORDING_LEVELS.get(recording_level, RECORDING_LEVELS["driver"])

    if recording_level in ("driver", "solver", "full"):
        # Recording options are set on the driver, not the recorder
        for opt_key in ("record_desvars", "record_objectives",
                        "record_constraints", "record_responses"):
            if opt_key in level_opts:
                try:
                    prob.driver.recording_options[opt_key] = level_opts[opt_key]
                except (AttributeError, KeyError):
                    pass
        prob.driver.add_recorder(recorder)

    if recording_level in ("solver", "full"):
        try:
            prob.model.nonlinear_solver.add_recorder(recorder)
        except AttributeError:
            pass

    # Always record final state on the problem
    prob.add_recorder(recorder)

    return recorder_path
