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

from hangar.omd.op_points import normalize_operating_points
from hangar.omd.registry import get_factory, get_factory_contract

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
    # Resolve {value, units} entries to plain values in canonical units
    # so factories never see raw unit-tagged dicts.
    operating_points = normalize_operating_points(
        plan.get("operating_points", {})
    )

    if not components:
        raise ValueError("Plan must contain at least one component")

    # If optimization is configured, defer factory setup so the materializer
    # can register design vars / constraints / objective before setup() runs.
    has_optimization = (
        plan.get("design_variables")
        and plan.get("objective")
    )

    # For single-component plans, the factory builds the full problem
    if len(components) == 1:
        comp = components[0]
        factory = get_factory(comp["type"])
        config = dict(comp["config"])
        if has_optimization:
            config["_defer_setup"] = True
        prob, metadata = factory(config, operating_points)
    else:
        prob, metadata = _materialize_composite(
            components, operating_points, plan,
        )

    setup_done = metadata.get("_setup_done", False)

    # Configure solvers (skip if factory already configured them)
    if not setup_done:
        _configure_solvers(prob, plan, metadata)

    # Configure optimization
    if has_optimization:
        _configure_driver(prob, plan, metadata)

    # Setup the problem (skip if factory already called setup). Components that
    # declare complex-step partials (e.g. the native evt model) need complex
    # vectors allocated; the factory signals this via ``force_alloc_complex``.
    if not setup_done:
        prob.setup(force_alloc_complex=bool(metadata.get("force_alloc_complex")))

    # Validate connection units for composite problems
    if metadata.get("_composite"):
        _validate_connection_units(prob, plan)

    # Set initial values from metadata (factory-provided). Failures
    # here are silent by design -- a factory may publish a name that
    # got hoisted to the root shared IVC and thus has a different
    # absolute path -- but we record what was skipped in metadata so
    # tests and the CLI can surface it when debugging a misconfigured
    # plan.
    skipped_initial_values: list[dict] = []
    for name, val in metadata.get("initial_values", {}).items():
        try:
            prob.set_val(name, val)
        except Exception as exc:  # noqa: BLE001 -- OpenMDAO raises many types
            logger.debug(
                "initial_values: could not set '%s' (%s)", name, exc,
            )
            skipped_initial_values.append(
                {"name": name, "error": str(exc), "source": "initial_values"},
            )

    for name, spec in metadata.get("initial_values_with_units", {}).items():
        units = spec.get("units") if isinstance(spec, dict) else None
        val = spec.get("val") if isinstance(spec, dict) else spec
        try:
            if units:
                prob.set_val(name, val, units=units)
            else:
                prob.set_val(name, val)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "initial_values_with_units: could not set '%s' (%s)",
                name, exc,
            )
            skipped_initial_values.append(
                {
                    "name": name,
                    "error": str(exc),
                    "source": "initial_values_with_units",
                },
            )

    if skipped_initial_values:
        metadata["skipped_initial_values"] = skipped_initial_values

    # Values that must take effect: factory options that set model
    # constants (e.g. OCP structural_fudge) and everything the plan sets
    # itself (initial_values, design_variables[].initial). Applied last,
    # so the plan wins over factory defaults, in analysis and optimize
    # mode alike; a name that does not exist is an error, not a skip.
    strict = dict(metadata.get("strict_initial_values") or {})
    strict.update(_plan_values(plan, metadata))
    metadata["applied_plan_values"] = _apply_strict_values(prob, strict)

    # Configure recorder after setup
    rec_path = _configure_recorder(prob, recording_level, recorder_path)
    metadata["recorder_path"] = rec_path

    return prob, metadata


# ---------------------------------------------------------------------------
# Multi-component composition
# ---------------------------------------------------------------------------


def _derive_auto_shared_vars(
    components: list[dict],
    plan: dict,
    user_shared: list[dict],
) -> list[dict]:
    """Derive shared_vars entries from overlapping factory contracts.

    Walks each component's FactoryContract.produces; any name declared by
    two or more components becomes an auto-hoisted shared_vars entry with
    ``_auto=True``. User-declared names (``user_shared``) and names listed
    in ``plan["no_auto_share"]`` are excluded. Returns an empty list when
    ``composition_policy`` is not ``"auto"`` or when no overlap exists.
    """
    policy = plan.get("composition_policy", "explicit")
    if policy != "auto":
        return []

    no_auto = set(plan.get("no_auto_share") or [])
    user_shared_names = {
        sv["name"] for sv in user_shared if isinstance(sv, dict) and "name" in sv
    }

    # name -> list[(comp_id, VarSpec)] for producers; name -> set[comp_id] for consumers
    producers: dict[str, list[tuple[str, object]]] = {}
    consumers: dict[str, set[str]] = {}
    for comp in components:
        contract = get_factory_contract(comp["type"])
        if contract is None:
            continue
        for name, spec in contract.produces.items():
            producers.setdefault(name, []).append((comp["id"], spec))
        for name in contract.consumes:
            consumers.setdefault(name, set()).add(comp["id"])

    auto: list[dict] = []
    for name in sorted(producers):
        prods = producers[name]
        if len(prods) < 2:
            continue
        if name in user_shared_names or name in no_auto:
            continue
        consumer_ids = sorted(
            {pid for pid, _ in prods} | consumers.get(name, set())
        )
        canonical = prods[0][1]
        entry = {
            "name": name,
            "consumers": consumer_ids,
            "_auto": True,
        }
        # Only emit value/units when the contract actually specifies a
        # default. Fix 2 already handles missing value/units keys.
        default = getattr(canonical, "default", None)
        if default is not None:
            entry["value"] = default
        units = getattr(canonical, "units", None)
        if units is not None:
            entry["units"] = units
        auto.append(entry)
        logger.info(
            "Auto-sharing '%s' across %s (default from '%s')",
            name, consumer_ids, prods[0][0],
        )
    return auto


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
    all_strict_values: dict[str, dict] = {}

    # Shared DVs (plan-level) injected as `skip_fields` per consumer so
    # each factory omits the named inputs from its internal IVC. The
    # root `shared_ivc` subsystem drives them instead.
    #
    # Fix 3 (Phase 3a): when `composition_policy == "auto"`, walk each
    # factory's FactoryContract.produces; any name declared by >=2
    # components is hoisted into shared_vars automatically. User-declared
    # shared_vars win (by name) and `no_auto_share` blocks individual
    # names from auto-hoisting. Policy defaults to "explicit" so the
    # behavior is identical to Fix 2 when unspecified.
    user_shared = list(plan.get("shared_vars") or [])
    auto_shared = _derive_auto_shared_vars(components, plan, user_shared)
    shared_vars = user_shared + auto_shared

    consumer_skip_fields: dict[str, list[str]] = {}
    for sv in shared_vars:
        for consumer_id in sv.get("consumers", []):
            consumer_skip_fields.setdefault(consumer_id, []).append(sv["name"])

    for comp in components:
        comp_id = comp["id"]
        comp_type = comp["type"]
        component_ids.append(comp_id)
        component_types[comp_id] = comp_type

        factory = get_factory(comp_type)

        # Inject _defer_setup so OCP factories skip their internal setup
        config = dict(comp["config"])
        config["_defer_setup"] = True

        # Merge shared-var driven skip_fields with any user-provided list
        if comp_id in consumer_skip_fields:
            user_skip = list(config.get("skip_fields") or [])
            merged = list(dict.fromkeys(user_skip + consumer_skip_fields[comp_id]))
            config["skip_fields"] = merged

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

        for path, spec in inner_meta.get("strict_initial_values", {}).items():
            all_strict_values[f"{comp_id}.{path}"] = spec

        component_metadata[comp_id] = inner_meta

        # Store active slot config for result extraction
        slots_cfg = comp.get("config", {}).get("slots", {})
        if slots_cfg:
            component_metadata[comp_id]["active_slots"] = slots_cfg

    # Root shared IVC: one independent variable per shared_vars entry,
    # fanned out to each declared consumer subsystem. DV registration
    # for these names resolves to `shared_ivc.{name}` (see
    # `_resolve_var_path`) so the DV is registered once at the root.
    shared_var_paths: dict[str, str] = {}
    if shared_vars:
        shared_ivc = om.IndepVarComp()
        for sv in shared_vars:
            name = sv["name"]
            kw: dict = {}
            if "value" in sv and sv["value"] is not None:
                kw["val"] = sv["value"]
            if sv.get("units"):
                kw["units"] = sv["units"]
            shared_ivc.add_output(name, **kw)
            # The shared IVC is promoted so its outputs are accessible
            # at the model root by their promoted names (no prefix).
            # DVs, constraints, and objectives reference the shared
            # value by that promoted name.
            shared_var_paths[name] = name
        shared_names = [sv["name"] for sv in shared_vars]
        prob.model.add_subsystem(
            "shared_ivc", shared_ivc, promotes_outputs=shared_names,
        )
        for sv in shared_vars:
            name = sv["name"]
            for consumer_id in sv.get("consumers", []):
                # Source uses the promoted root-level name (since the
                # shared IVC's outputs are promoted above). Target
                # uses the consumer subsystem's component-root input.
                prob.model.connect(name, f"{consumer_id}.{name}")

    # Wire explicit connections from the plan
    for conn in plan.get("connections", []):
        prob.model.connect(conn["src"], conn["tgt"])

    # Merge per-component var_paths with component-id prefix + shared
    # vars so downstream consumers (tests, run.py) can resolve names
    # without re-running the driver configuration.
    merged_var_paths: dict[str, str] = {}
    for comp_id, comp_meta in component_metadata.items():
        for short_name, full_path in comp_meta.get("var_paths", {}).items():
            merged_var_paths[f"{comp_id}.{short_name}"] = f"{comp_id}.{full_path}"
            if short_name not in merged_var_paths:
                merged_var_paths[short_name] = f"{comp_id}.{full_path}"
    for sv_name, sv_path in shared_var_paths.items():
        merged_var_paths[sv_name] = sv_path

    # Build composite metadata
    metadata: dict = {
        "_composite": True,
        "component_ids": component_ids,
        "component_types": component_types,
        "component_metadata": component_metadata,
        "initial_values": all_initial_values,
        "initial_values_with_units": all_initial_values_with_units,
        "strict_initial_values": all_strict_values,
        "shared_var_paths": shared_var_paths,
        "var_paths": merged_var_paths,
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
            if solver_type not in _NONLINEAR_SOLVERS:
                from hangar.sdk.errors import UserInputError

                raise UserInputError(
                    f"Unknown nonlinear solver type {solver_type!r}. "
                    f"Options: {sorted(_NONLINEAR_SOLVERS)}",
                    details={
                        "field": "solvers.nonlinear.type",
                        "value": solver_type,
                        "options": sorted(_NONLINEAR_SOLVERS),
                    },
                )
            spec["nl"] = {"type": solver_type, "options": options}

        lin_config = entry.get("linear")
        if lin_config:
            solver_type = lin_config["type"]
            options = lin_config.get("options", {})
            if solver_type not in _LINEAR_SOLVERS:
                from hangar.sdk.errors import UserInputError

                raise UserInputError(
                    f"Unknown linear solver type {solver_type!r}. "
                    f"Options: {sorted(_LINEAR_SOLVERS)}",
                    details={
                        "field": "solvers.linear.type",
                        "value": solver_type,
                        "options": sorted(_LINEAR_SOLVERS),
                    },
                )
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
                # Explicit target path. _get_subsystem returns None (rather
                # than raising) when the path does not exist.
                try:
                    target = prob.model._get_subsystem(target_path)
                except Exception:
                    target = None
                if target is None:
                    logger.warning(
                        "Solver target '%s' not found after setup; skipping",
                        target_path,
                    )
                    continue
                target_groups = [target]
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
    try:
        # Unknown names pass through so any scipy optimizer OpenMDAO accepts
        # still works; OpenMDAO's options validation rejects real typos.
        driver.options["optimizer"] = _OPTIMIZERS.get(opt_type, opt_type)
    except Exception as exc:
        from hangar.sdk.errors import UserInputError

        raise UserInputError(
            f"Unknown optimizer type {opt_type!r}. Plan aliases: "
            f"{sorted(_OPTIMIZERS)}; any scipy optimizer name accepted by "
            f"OpenMDAO's ScipyOptimizeDriver also works.",
            details={
                "field": "optimizer.type",
                "value": opt_type,
                "aliases": sorted(_OPTIMIZERS),
            },
        ) from exc
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

    var_paths = _plan_var_paths(metadata)

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
            if not isinstance(pt_idx, int) or not 0 <= pt_idx < len(point_names):
                from hangar.sdk.errors import UserInputError

                raise UserInputError(
                    f"Constraint {con_name!r}: point index {pt_idx!r} is out of "
                    f"range for this plan's {len(point_names)} analysis point(s) "
                    f"(valid: 0..{len(point_names) - 1}).",
                    details={
                        "field": "constraints.point",
                        "value": pt_idx,
                        "point_names": list(point_names),
                    },
                )
            pt = point_names[pt_idx]
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


def _plan_var_paths(metadata: dict) -> dict[str, str] | None:
    """Short-name -> path map for resolving plan variable names.

    Factory-provided mappings take precedence. For composite problems the
    per-component maps are merged, prefixed by component id, with
    unprefixed entries kept for single-component shorthand (first wins)
    and shared-var names winning over component-local ones, so
    ``design_variables: [{name: ac|geom|wing|AR}]`` registers the DV at
    the root shared_ivc rather than the first component.
    """
    var_paths = metadata.get("var_paths")
    if metadata.get("_composite"):
        merged_var_paths: dict[str, str] = {}
        for comp_id, comp_meta in metadata.get("component_metadata", {}).items():
            for short_name, full_path in comp_meta.get("var_paths", {}).items():
                merged_var_paths[f"{comp_id}.{short_name}"] = f"{comp_id}.{full_path}"
                if short_name not in merged_var_paths:
                    merged_var_paths[short_name] = f"{comp_id}.{full_path}"
        for sv_name, sv_path in metadata.get("shared_var_paths", {}).items():
            merged_var_paths[sv_name] = sv_path
        var_paths = merged_var_paths or var_paths
    return var_paths


def _plan_values(plan: dict, metadata: dict) -> dict[str, dict]:
    """Starting values the plan itself sets, keyed by resolved path.

    Two sources, applied whether or not the plan optimizes:

    1. Top-level ``initial_values: [{name, val, units?}, ...]`` --
       arbitrary paths (aircraft constants, mission params, factory
       inputs) the plan overrides without a factory code change.
    2. ``design_variables[*].initial`` -- per-DV starting points (and
       warm starts, which write here). A DV's own ``initial`` wins over
       an ``initial_values`` entry for the same path, so a warm start is
       never overwritten by the plan's cold-start value.
    """
    point_name = metadata.get("point_name", "AS_point_0")
    surface_names = metadata.get("surface_names", [])
    components = plan.get("components", [])
    component_type = components[0].get("type") if components else None
    var_paths = _plan_var_paths(metadata)

    values: dict[str, dict] = {}
    for i, iv in enumerate(plan.get("initial_values", []) or []):
        path = _resolve_var_path(iv["name"], point_name, surface_names,
                                 component_type, var_paths=var_paths)
        values[path] = {"val": iv["val"], "units": iv.get("units"),
                        "source": f"initial_values[{i}] ({iv['name']})"}
    for dv in plan.get("design_variables", []) or []:
        if "initial" not in dv:
            continue
        path = _resolve_var_path(dv["name"], point_name, surface_names,
                                 component_type, var_paths=var_paths)
        values[path] = {"val": dv["initial"], "units": dv.get("units"),
                        "source": f"design_variables[{dv['name']}].initial"}
    return values


def _leaf(name: str) -> str:
    return name.replace("|", ".").rsplit(".", 1)[-1]


def _apply_strict_values(prob: om.Problem, values: dict[str, dict]) -> list[dict]:
    """Set values that must take effect, or raise UserInputError.

    Unlike factory defaults (best effort), every value here was asked for
    by the plan (or a factory option such as ``structural_fudge``), so a
    name that does not exist -- or names a quantity the model computes,
    where a set value would be overwritten on the first run -- is an
    error that lists what went wrong and the closest real names.
    Returns ``[{name, target, source}]`` for what was applied.
    """
    import difflib

    if not values:
        return []
    model = prob.model
    outputs = model.get_io_metadata(iotypes=("output",), metadata_keys=("tags",),
                                    return_rel_names=False)
    inputs = model.get_io_metadata(iotypes=("input",), return_rel_names=False)
    out_prom: dict[str, list[str]] = {}
    for abs_name, meta in outputs.items():
        out_prom.setdefault(meta["prom_name"], []).append(abs_name)
    in_prom: dict[str, list[str]] = {}
    for abs_name, meta in inputs.items():
        in_prom.setdefault(meta["prom_name"], []).append(abs_name)
    # Connection map is populated by setup(); private, so degrade to "no
    # computed-source check" if a future OpenMDAO renames it.
    conns: dict[str, str] = getattr(model, "_conn_global_abs_in2out", None) or {}

    def indep(abs_out: str) -> bool:
        return "openmdao:indep_var" in (outputs.get(abs_out, {}).get("tags") or ())

    def prom_of(abs_out: str) -> str:
        return outputs.get(abs_out, {}).get("prom_name", abs_out)

    def settable(prom: str) -> bool:
        if prom in out_prom:
            return all(indep(a) for a in out_prom[prom])
        return all((conns.get(a) or "_auto_ivc.").startswith("_auto_ivc.")
                   for a in in_prom.get(prom, ()))

    applied: list[dict] = []
    problems: list[str] = []
    candidates: list[str] | None = None
    for name, spec in values.items():
        units = spec.get("units") if isinstance(spec, dict) else None
        val = spec.get("val") if isinstance(spec, dict) else spec
        source = (spec.get("source") if isinstance(spec, dict) else None) or name

        abs_outs = [name] if name in outputs else out_prom.get(name)
        abs_ins = [name] if name in inputs else in_prom.get(name)
        target, reason = name, None
        if abs_outs:
            if not all(indep(a) for a in abs_outs):
                reason = (f"'{name}' is computed by the model, so a set value "
                          "is overwritten when it runs")
        elif abs_ins:
            srcs = {conns.get(a) for a in abs_ins} - {None}
            srcs = {s for s in srcs if not s.startswith("_auto_ivc.")}
            computed = sorted(s for s in srcs if not indep(s))
            if computed:
                reason = (f"'{name}' is an input connected to "
                          f"'{prom_of(computed[0])}', which the model computes, "
                          "so a set value is overwritten when it runs")
            elif len(srcs) == 1:
                # Fed by an independent variable: setting the input would be
                # overwritten by that source on the first run -- set the source.
                target = prom_of(next(iter(srcs)))
            elif srcs:
                reason = (f"'{name}' is fed by several sources "
                          f"({', '.join(sorted(prom_of(s) for s in srcs))}); set those")
        else:
            if candidates is None:
                candidates = sorted(c for c in set(out_prom) | set(in_prom) if settable(c))
            leaf = _leaf(name)
            same_leaf = [c for c in candidates if _leaf(c) == leaf]
            close = difflib.get_close_matches(name, candidates, n=3, cutoff=0.6)
            hint = list(dict.fromkeys(same_leaf[:8] + close))
            reason = (f"'{name}' does not exist in the model"
                      + (f"; similar settable names: {', '.join(hint)}" if hint else ""))
            if leaf == "structural_fudge":
                reason += (". For an OCP mission set the component's "
                           "config.structural_fudge, which applies it to every "
                           "phase's empty-weight model")
        if reason is None:
            try:
                if units:
                    prob.set_val(target, val, units=units)
                else:
                    prob.set_val(target, val)
            except Exception as exc:  # noqa: BLE001 -- OpenMDAO raises many types
                reason = f"could not set '{target}': {exc}"
        if reason:
            problems.append(f"{source}: {reason}")
        else:
            applied.append({"name": name, "target": target, "source": source})

    if problems:
        from hangar.sdk.errors import UserInputError

        raise UserInputError(
            "Plan values could not be applied (nothing was run):\n  "
            + "\n  ".join(problems),
            details={"problems": problems},
        )
    return applied


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
            "t_over_c_cp": f"{surf}.geometry.t_over_c_cp",
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

    # Record inputs on the final problem case so mission boundary conditions that
    # are prescribed as inputs (fltcond|Ueas, fltcond|vs) are persisted -- without
    # this they are absent from the recording and the mission_profile V/S panel is
    # blank while the airspeed trace falls back to true airspeed.
    try:
        prob.recording_options["record_inputs"] = True
    except (AttributeError, KeyError):
        pass

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
