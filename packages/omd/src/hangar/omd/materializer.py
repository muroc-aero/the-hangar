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
        prob, metadata = _materialize_composite(
            components, operating_points, plan,
        )

    setup_done = metadata.get("_setup_done", False)

    # Configure solvers (skip if factory already configured them)
    if not setup_done:
        _configure_solvers(prob, plan, metadata)

    # Configure optimization
    has_optimization = (
        plan.get("design_variables")
        and plan.get("objective")
    )
    if has_optimization:
        _configure_driver(prob, plan, metadata)

    # Setup the problem (skip if factory already called setup)
    if not setup_done:
        prob.setup()

    # Validate connection units for composite problems
    if metadata.get("_composite"):
        _validate_connection_units(prob, plan)

    # Set initial values from metadata (factory-provided)
    for name, val in metadata.get("initial_values", {}).items():
        try:
            prob.set_val(name, val)
        except Exception:
            pass

    # Set initial values with units (OCP factories provide these)
    for name, spec in metadata.get("initial_values_with_units", {}).items():
        try:
            units = spec.get("units") if isinstance(spec, dict) else None
            val = spec.get("val") if isinstance(spec, dict) else spec
            if units:
                prob.set_val(name, val, units=units)
            else:
                prob.set_val(name, val)
        except Exception:
            pass

    # Configure recorder after setup
    rec_path = _configure_recorder(prob, recording_level, recorder_path)
    metadata["recorder_path"] = rec_path

    return prob, metadata


# ---------------------------------------------------------------------------
# Multi-component composition
# ---------------------------------------------------------------------------


def _materialize_composite(
    components: list[dict],
    operating_points: dict,
    plan: dict,
) -> tuple[om.Problem, dict]:
    """Compose multiple components into a single OpenMDAO Problem.

    Each factory is called to build a Problem. The model Group is
    extracted (before setup) and added as a subsystem named by the
    component ID. Connections from the plan wire outputs to inputs
    across components. Components are NOT promoted, so each lives
    under its own namespace.

    Returns (problem, metadata) where setup has NOT been called.
    """
    prob = om.Problem(reports=False)
    component_metadata: dict[str, dict] = {}
    component_types: dict[str, str] = {}
    component_ids: list[str] = []
    all_initial_values: dict[str, object] = {}
    all_initial_values_with_units: dict[str, dict] = {}

    for comp in components:
        comp_id = comp["id"]
        comp_type = comp["type"]
        component_ids.append(comp_id)
        component_types[comp_id] = comp_type

        factory = get_factory(comp_type)

        # Inject _defer_setup so OCP factories skip their internal setup
        config = dict(comp["config"])
        config["_defer_setup"] = True

        inner_prob, inner_meta = factory(config, operating_points)

        if inner_meta.get("_setup_done"):
            raise RuntimeError(
                f"Factory for '{comp_type}' (component '{comp_id}') called "
                f"setup() despite _defer_setup=True. Cannot compose "
                f"post-setup components."
            )

        # Extract the model Group and add as a subsystem
        prob.model.add_subsystem(comp_id, inner_prob.model)

        # Collect deferred initial values, prefixed with component ID
        for path, val in inner_meta.get("initial_values", {}).items():
            all_initial_values[f"{comp_id}.{path}"] = val

        for path, spec in inner_meta.get("initial_values_with_units", {}).items():
            all_initial_values_with_units[f"{comp_id}.{path}"] = spec

        component_metadata[comp_id] = inner_meta

    # Wire explicit connections from the plan
    for conn in plan.get("connections", []):
        prob.model.connect(conn["src"], conn["tgt"])

    # Build composite metadata
    metadata: dict = {
        "_composite": True,
        "component_ids": component_ids,
        "component_types": component_types,
        "component_metadata": component_metadata,
        "initial_values": all_initial_values,
        "initial_values_with_units": all_initial_values_with_units,
    }

    return prob, metadata


def _validate_connection_units(prob: om.Problem, plan: dict) -> None:
    """Warn when explicit connections have incompatible units.

    Called after setup for composite problems. Uses OpenMDAO's unit
    system to check that connected source and target variables have
    compatible units.
    """
    connections = plan.get("connections", [])
    if not connections:
        return

    try:
        from openmdao.utils.units import unit_conversion
    except ImportError:
        return

    for conn in connections:
        src, tgt = conn["src"], conn["tgt"]
        try:
            src_meta = prob.model.get_io_metadata(
                iotypes="output", includes=[src],
            )
            tgt_meta = prob.model.get_io_metadata(
                iotypes="input", includes=[tgt],
            )
        except Exception:
            continue

        if not src_meta or not tgt_meta:
            continue

        src_units = next(iter(src_meta.values())).get("units")
        tgt_units = next(iter(tgt_meta.values())).get("units")

        if src_units and tgt_units:
            try:
                unit_conversion(src_units, tgt_units)
            except Exception:
                logger.warning(
                    "Connection '%s' -> '%s': incompatible units "
                    "(%s vs %s). OpenMDAO may fail at runtime.",
                    src, tgt, src_units, tgt_units,
                )


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

    The ``solvers`` key in a plan can be either a single dict or a list
    of dicts. Each dict may include an optional ``target`` key naming the
    subsystem to apply the solvers to (e.g., ``"mission.coupled"``).
    When ``target`` is absent, solvers apply to the default location
    (the coupled group for OAS, or the model root as fallback).

    Examples::

        # Single solver scope (backward compatible)
        solvers:
          nonlinear: {type: NewtonSolver, options: {maxiter: 20}}
          linear: {type: DirectSolver}

        # Multiple solver scopes
        solvers:
          - target: mission.analysis
            nonlinear: {type: NewtonSolver, options: {maxiter: 20}}
            linear: {type: DirectSolver}
          - target: oas_wing.aero_point_0.coupled
            nonlinear: {type: NonlinearBlockGS, options: {maxiter: 50}}
    """
    solver_config = plan.get("solvers")
    if not solver_config:
        return

    # Normalize to list-of-dicts
    if isinstance(solver_config, dict):
        solver_entries = [solver_config]
    elif isinstance(solver_config, list):
        solver_entries = solver_config
    else:
        return

    # Store all entries for post-setup application
    solver_specs = []
    for entry in solver_entries:
        spec: dict = {}
        target = entry.get("target")
        if target:
            spec["target"] = target

        nl_config = entry.get("nonlinear")
        if nl_config:
            solver_type = nl_config["type"]
            options = nl_config.get("options", {})
            if solver_type in _NONLINEAR_SOLVERS:
                spec["nl"] = {"type": solver_type, "options": options}

        lin_config = entry.get("linear")
        if lin_config:
            solver_type = lin_config["type"]
            options = lin_config.get("options", {})
            if solver_type in _LINEAR_SOLVERS:
                spec["lin"] = {"type": solver_type, "options": options}

        if spec:
            solver_specs.append(spec)

    if solver_specs:
        metadata["_solver_specs"] = solver_specs

    # Backward compatibility: also populate the old keys for specs
    # without an explicit target (default behavior)
    default_specs = [s for s in solver_specs if "target" not in s]
    if default_specs:
        ds = default_specs[0]
        if "nl" in ds:
            metadata["_nl_solver"] = ds["nl"]
        if "lin" in ds:
            metadata["_lin_solver"] = ds["lin"]


def apply_solvers_post_setup(prob: om.Problem, metadata: dict) -> None:
    """Apply solver configuration after setup().

    For OAS aerostruct problems, the coupled group exists only after
    setup(). This function applies the configured solvers to the
    correct subsystem.

    For multipoint problems, solvers are applied to each point's
    coupled group independently.

    Important: OAS sets default solvers on the coupled group during
    setup() (NonlinearBlockGS with Aitken, err_on_non_converge=True).
    When replacing these, we must preserve safe defaults -- in particular,
    Newton must have err_on_non_converge=False so that unconverged
    iterations return an approximate answer rather than raising an
    exception, which lets gradient-based optimizers proceed.
    """
    # Handle targeted solver specs (new list-of-dicts format)
    solver_specs = metadata.pop("_solver_specs", None)
    if solver_specs:
        for spec in solver_specs:
            target_path = spec.get("target")
            if target_path:
                # Explicit target path
                try:
                    target_groups = [prob.model._get_subsystem(target_path)]
                except Exception:
                    logger.warning(
                        "Solver target '%s' not found after setup; skipping",
                        target_path,
                    )
                    continue
            else:
                # Default: use the OAS coupled group or model root
                target_groups = _resolve_default_solver_targets(prob, metadata)

            _apply_solver_spec_to_targets(spec, target_groups)

        # Clean up old-style keys if they were also populated
        metadata.pop("_nl_solver", None)
        metadata.pop("_lin_solver", None)
        return

    # Backward-compatible path: old-style single solver config
    targets = _resolve_default_solver_targets(prob, metadata)

    nl_config = metadata.pop("_nl_solver", None)
    if nl_config:
        for target in targets:
            _apply_nl_solver(nl_config, target)

    lin_config = metadata.pop("_lin_solver", None)
    if lin_config:
        for target in targets:
            _apply_lin_solver(lin_config, target)


def _resolve_default_solver_targets(
    prob: om.Problem, metadata: dict,
) -> list:
    """Find default solver targets (coupled groups or model root)."""
    point_names = metadata.get("point_names")
    if point_names is None:
        point_names = [metadata.get("point_name", "AS_point_0")]

    targets = []
    for pt in point_names:
        try:
            coupled = prob.model._get_subsystem(f"{pt}.coupled")
        except Exception:
            coupled = None
        if coupled is not None:
            targets.append(coupled)

    if not targets:
        targets = [prob.model]
    return targets


def _apply_solver_spec_to_targets(spec: dict, targets: list) -> None:
    """Apply a solver spec dict to a list of target groups."""
    nl = spec.get("nl")
    if nl:
        for t in targets:
            _apply_nl_solver(nl, t)
    lin = spec.get("lin")
    if lin:
        for t in targets:
            _apply_lin_solver(lin, t)


def _apply_nl_solver(config: dict, target) -> None:
    """Apply a nonlinear solver config to a target group."""
    solver_cls = _NONLINEAR_SOLVERS[config["type"]]
    solver = solver_cls()
    if config["type"] == "NewtonSolver":
        if "solve_subsystems" not in config["options"]:
            solver.options["solve_subsystems"] = True
        if "err_on_non_converge" not in config["options"]:
            solver.options["err_on_non_converge"] = False
    for key, val in config["options"].items():
        solver.options[key] = val
    target.nonlinear_solver = solver


def _apply_lin_solver(config: dict, target) -> None:
    """Apply a linear solver config to a target group."""
    solver_cls = _LINEAR_SOLVERS[config["type"]]
    solver = solver_cls()
    for key, val in config["options"].items():
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
        if key in ("maxiter", "maxfev"):
            driver.options[key] = val
        elif key == "ftol":
            driver.options["tol"] = val
        elif key == "timeout_seconds":
            pass  # Handled by run.py, not the driver
        else:
            driver.options[key] = val
    prob.driver = driver

    # Design variables
    point_name = metadata.get("point_name", "AS_point_0")
    surface_names = metadata.get("surface_names", [])
    components = plan.get("components", [])
    component_type = components[0].get("type") if components else None

    # Build var_paths: factory-provided mappings take precedence
    var_paths = metadata.get("var_paths")
    if metadata.get("_composite"):
        # For composite problems, merge var_paths from each component,
        # prefixed by component_id. Also keep unprefixed entries for
        # single-component shorthand (first-wins).
        merged_var_paths: dict[str, str] = {}
        for comp_id, comp_meta in metadata.get("component_metadata", {}).items():
            for short_name, full_path in comp_meta.get("var_paths", {}).items():
                merged_var_paths[f"{comp_id}.{short_name}"] = f"{comp_id}.{full_path}"
                if short_name not in merged_var_paths:
                    merged_var_paths[short_name] = f"{comp_id}.{full_path}"
        var_paths = merged_var_paths or var_paths

    for dv in plan.get("design_variables", []):
        dv_name = dv["name"]
        path = _resolve_var_path(dv_name, point_name, surface_names,
                                 component_type, var_paths=var_paths)
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
        if "units" in dv:
            kwargs["units"] = dv["units"]
        prob.model.add_design_var(path, **kwargs)

    # Constraints
    point_names = metadata.get("point_names")
    for con in plan.get("constraints", []):
        con_name = con["name"]
        # For multipoint, use per-point constraint targeting
        if point_names and "point" in con:
            pt_idx = con["point"]
            pt = point_names[pt_idx] if pt_idx < len(point_names) else point_names[0]
        else:
            pt = point_name
        path = _resolve_var_path(con_name, pt, surface_names, component_type,
                                 var_paths=var_paths)
        kwargs = {}
        if "upper" in con:
            kwargs["upper"] = con["upper"]
        if "lower" in con:
            kwargs["lower"] = con["lower"]
        if "equals" in con:
            kwargs["equals"] = con["equals"]
        if "scaler" in con:
            kwargs["scaler"] = con["scaler"]
        if "units" in con:
            kwargs["units"] = con["units"]
        prob.model.add_constraint(path, **kwargs)

    # Objective
    obj = plan.get("objective", {})
    if obj:
        obj_name = obj["name"]
        path = _resolve_var_path(obj_name, point_name, surface_names,
                                 component_type, var_paths=var_paths)
        kwargs = {}
        if "scaler" in obj:
            kwargs["scaler"] = obj["scaler"]
        if "units" in obj:
            kwargs["units"] = obj["units"]
        prob.model.add_objective(path, **kwargs)


def _resolve_var_path(
    name: str,
    point_name: str,
    surface_names: list[str],
    component_type: str | None = None,
    var_paths: dict[str, str] | None = None,
) -> str:
    """Resolve a short variable name to a full OpenMDAO path.

    If the name already contains dots (looks like a full path),
    return as-is. Otherwise, check factory-provided var_paths first,
    then fall back to common OAS/OCP conventions.

    Args:
        name: Short variable name (e.g. "CL", "twist_cp").
        point_name: Analysis point subsystem name.
        surface_names: List of surface names from metadata.
        component_type: Component type string (e.g. "oas/AeroPoint").
            Used to distinguish aero-only vs aerostruct path patterns.
        var_paths: Factory-provided mapping of short names to full paths.
            Takes precedence over hardcoded tables when present.
    """
    # Pipe-separated paths (OpenConcept convention) pass through as-is
    if "|" in name:
        return name

    if "." in name:
        return name

    # Factory-provided mapping takes precedence
    if var_paths and name in var_paths:
        return var_paths[name]

    # OCP short names
    _OCP_SHORT_NAMES = {
        "fuel_burn": "descent.fuel_used_final",
        "OEW": "climb.OEW",
        "MTOW": "ac|weights|MTOW",
        "TOFL": "rotate.range_final",
    }
    if component_type and component_type.startswith("ocp/"):
        if name in _OCP_SHORT_NAMES:
            return _OCP_SHORT_NAMES[name]

    # Simple names that are promoted to top level
    if name in ("alpha", "v", "rho", "Mach_number", "re", "load_factor",
                "beta", "CT", "R", "W0", "speed_of_sound",
                "alpha_maneuver", "fuel_mass", "W0_without_point_masses",
                "point_masses", "point_mass_locations"):
        return name

    # Top-level multipoint constraints (no point prefix)
    if name == "fuel_vol_delta":
        return "fuel_vol_delta.fuel_vol_delta"
    if name == "fuel_diff":
        return "fuel_diff"

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

        # Performance outputs (constraints/objectives)
        perf_outputs = {"CL", "CD", "CDi", "CDv", "CDw", "CM"}
        if name in perf_outputs:
            # Aero-only: promoted directly to {point}.{name}
            # Aerostruct: nested under {point}.{surf}_perf.{name}
            is_aero_only = (
                component_type == "oas/AeroPoint"
                or point_name.startswith("aero_")
            )
            if is_aero_only:
                return f"{point_name}.{name}"
            return f"{point_name}.{surf}_perf.{name}"

        # Surface-level outputs: {point}.{surf}.{name}
        surface_outputs = {"S_ref"}
        if name in surface_outputs:
            return f"{point_name}.{surf}.{name}"

    # Aerostruct-specific outputs
    aerostruct_outputs = {
        "failure": f"{point_name}.{surface_names[0]}_perf.failure" if surface_names else name,
        "tsaiwu_sr": f"{point_name}.{surface_names[0]}_perf.tsaiwu_sr" if surface_names else name,
        "fuelburn": "fuelburn",
        "structural_mass": f"{surface_names[0]}.structural_mass" if surface_names else name,
        "L_equals_W": f"{point_name}.L_equals_W" if point_name else name,
    }
    if name in aerostruct_outputs:
        return aerostruct_outputs[name]

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
