"""Aviary sizing component factory (``avy/Sizing``) -- native composition.

Aviary's model is an ordinary OpenMDAO Group (``AviaryGroup``); the
``AviaryProblem`` class upstream is a thin ``om.Problem`` wrapper whose
level-2 API delegates every model-building step to that group. This factory
runs the same sequence on a bare ``AviaryGroup`` and adds it to the omd
problem as subsystem ``aviary`` with ``promotes=["*"]``, so Aviary's promoted
names (``aircraft:*``, ``mission:*``, ``traj.*``) ARE the component's
namespace. Other plan components connect to them directly, with analytic
derivatives flowing through one driver:

- Aviary's own design variables, constraints and objective are declared
  inside the group and collected by omd's driver (OpenMDAO re-keys them
  under the component path), so the sizing runs as part of whatever
  optimization the plan defines. Every Aviary run is an optimization
  (dymos collocation) -- there is no evaluate-only path -- so plans with
  this component run in ``mode: optimize``.
- Deck values reach the model as promoted-input defaults. A variable that
  Aviary would otherwise COMPUTE (e.g. ``aircraft:wing:mass`` from the FLOPS
  mass build-up) becomes a plain boundary input when the deck provides it,
  which is Aviary's own override mechanism. So ``overrides`` doubles as the
  coupling seam: give the variable a deck value, then connect another
  component's output to ``<comp_id>.<aviary name>`` in the plan
  (see ``examples/oas_avy_wing_mass``).
- ``external_subsystems`` are Aviary SubsystemBuilders from the hangar.avy
  registry (e.g. ``oas_wing_mass``), materialized INSIDE the group -- the
  seam for components that must live inside the mission phases.

What the factory hands the materializer through metadata (all generic
hooks, nothing Aviary-specific in the materializer): ``self_optimizing`` /
``requires_driver`` (drive even when the plan declares no DVs; refuse
mode=analysis), ``driver_defaults`` + ``driver_coloring`` (Aviary's SLSQP
settings: tol 1e-9, max_iter, total coloring -- the same driver
``run_aviary`` builds), ``model_options`` (Aviary options routed by
OpenMDAO model_options, path-prefixed by the materializer in composites),
``post_setup`` (dymos initial guesses must be set after ``setup()``) and
``setup_warning_filters`` (the promotion warnings AviaryProblem.setup
suppresses).
"""

from __future__ import annotations

import copy
import importlib
import logging
from typing import Any

import openmdao.api as om

from hangar.avy.runner import check_optimizer_available, load_deck
from hangar.avy.subsystems import build_external_subsystems
from hangar.avy.validators import validate_deck_overrides
from hangar.omd.factory_metadata import FactoryMetadata

logger = logging.getLogger(__name__)

DEFAULT_PHASE_INFO_MODULE = "aviary.models.missions.energy_state_default"

# Objective choices. "fuel" is what ``run_aviary`` uses for a sizing problem
# (Mission.Objectives.FUEL = fuel/1e4 + ascent_duration/30, ref=1); the
# others are Aviary's explicit objective_type options with Aviary's default
# refs. "none" leaves the objective to the plan (composite objectives).
_OBJECTIVES = ("fuel", "fuel_burned", "mass", "time", "none")
_OBJECTIVE_REFS = {"fuel": 1.0, "fuel_burned": 1e4, "mass": 5e4, "time": 1.0}

# Summary outputs: short name -> (Aviary promoted name, units). The short
# names are stable across the subprocess-era plans/tests; ``var_paths``
# exposes them for DVs/constraints/objectives in plans.
_OUTPUTS: dict[str, tuple[str, str]] = {
    "gross_mass_lbm": ("mission:gross_mass", "lbm"),
    "total_fuel_mass_lbm": ("mission:total_fuel_mass", "lbm"),
    "operating_mass_lbm": ("mission:operating_mass", "lbm"),
    "wing_mass_lbm": ("aircraft:wing:mass", "lbm"),
    "range_nmi": ("mission:range", "nmi"),
    "final_time_min": ("mission:final_time", "min"),
}

_LEGACY_KEYS = {
    "override_inputs": (
        "'override_inputs' is gone: give the deck variable a value in "
        "'overrides' (e.g. overrides: {'aircraft:wing:mass': [15000, 'lbm']}) "
        "-- a deck-provided variable is a boundary input -- and connect to it "
        "in the plan (tgt: <comp_id>.aircraft:wing:mass)."
    ),
    "avy_python": "'avy_python' is gone: Aviary runs natively in the omd process.",
    "run_timeout_s": (
        "'run_timeout_s' is gone: use the plan-level "
        "optimizer.options.timeout_seconds."
    ),
}


def _load_phase_info(module_name: str, target_range_nm: float | None) -> dict:
    """Deep-copy ``phase_info`` from an importable module; apply target range.

    Aviary mutates phase_info in place during preprocessing, so never hand it
    the module's own dict.
    """
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(
            f"avy/Sizing phase_info_module {module_name!r} is not importable: "
            f"{exc}. Use an aviary.models.missions.* module or a hangar.avy."
            "config.missions* module exposing 'phase_info'."
        ) from exc
    if not hasattr(mod, "phase_info"):
        raise ValueError(
            f"avy/Sizing phase_info_module {module_name!r} has no 'phase_info'."
        )
    phase_info = copy.deepcopy(mod.phase_info)
    if target_range_nm is not None:
        post = phase_info.setdefault("post_mission", {})
        post["constrain_range"] = True
        post["target_range"] = (float(target_range_nm), "nmi")
    return phase_info


def _add_objective(grp, objective: str) -> None:
    """Replicate ``AviaryProblem.add_objective`` on the bare group.

    Upstream adds the two regularized ExecComps from the Problem class; they
    are part of the model, so they are added here for topology parity with
    ``run_aviary`` (the range one only matters for off-design).
    """
    from aviary.variable_info.variables import Dynamic, Mission

    grp.add_subsystem(
        "fuel_obj",
        om.ExecComp(
            "reg_objective = overall_fuel/10000 + ascent_duration/30.",
            reg_objective={"val": 0.0, "units": "unitless"},
            ascent_duration={"units": "s", "shape": 1},
            overall_fuel={"units": "lbm"},
        ),
        promotes_inputs=[
            ("ascent_duration", Mission.Takeoff.ASCENT_DURATION),
            ("overall_fuel", Mission.TOTAL_FUEL_MASS),
        ],
        promotes_outputs=[("reg_objective", Mission.Objectives.FUEL)],
    )
    target_range = getattr(grp, "target_range", None)
    if target_range is not None:
        grp.add_subsystem(
            "range_obj",
            om.ExecComp(
                "reg_objective = -actual_range/1000 + ascent_duration/30.",
                reg_objective={"val": 0.0, "units": "unitless"},
                ascent_duration={"units": "s", "shape": 1},
                actual_range={"val": target_range, "units": "NM"},
            ),
            promotes_inputs=[
                ("actual_range", Mission.RANGE),
                ("ascent_duration", Mission.Takeoff.ASCENT_DURATION),
            ],
            promotes_outputs=[("reg_objective", Mission.Objectives.RANGE)],
        )

    if objective == "none":
        return
    ref = _OBJECTIVE_REFS[objective]
    if objective == "fuel":
        grp.add_objective(Mission.Objectives.FUEL, ref=ref)
    elif objective == "fuel_burned":
        grp.add_objective(Mission.FUEL_MASS, ref=ref)
    else:
        final_phase = grp.regular_phases[-1]
        if objective == "mass":
            grp.add_objective(
                f"traj.{final_phase}.timeseries.{Dynamic.Vehicle.MASS}", index=-1, ref=ref
            )
        else:  # time
            grp.add_objective(f"traj.{final_phase}.timeseries.time", index=-1, ref=ref)


def build_avy_sizing(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an Aviary sizing problem from plan config (``avy/Sizing``).

    Config keys: ``deck`` (required; aviary-relative CSV path or absolute),
    ``phase_info_module`` (importable module exposing ``phase_info``),
    ``target_range_nm`` (sets post_mission constrain_range/target_range; the
    operating point may override it), ``overrides`` ({aviary name: value or
    [value, units]} deck overrides -- also how a computed variable becomes a
    connectable boundary input), ``external_subsystems`` ([{"name": ...,
    "config": {...}}] from the hangar.avy registry, built inside the group),
    ``optimizer`` (SLSQP -- omd drives with ScipyOptimizeDriver), ``max_iter``,
    ``objective`` (fuel | fuel_burned | mass | time | none).

    Returns (problem, metadata). Problem has setup NOT called; the plan runs
    in ``mode: optimize`` (metadata ``requires_driver``).
    """
    config = dict(component_config)
    config.pop("_defer_setup", None)
    # skip_fields (shared vars) needs nothing here: a shared var connects to
    # the promoted Aviary input, which is otherwise fed by the auto-IVC.
    config.pop("skip_fields", None)

    for key, msg in _LEGACY_KEYS.items():
        if key in config:
            raise ValueError(f"avy/Sizing config {msg}")

    if "deck" not in config:
        raise ValueError(
            "avy/Sizing requires a 'deck' config key (aviary-relative CSV "
            "path, e.g. 'models/aircraft/advanced_single_aisle/"
            "advanced_single_aisle_FLOPS.csv')."
        )

    optimizer = config.get("optimizer", "SLSQP")
    check_optimizer_available(optimizer)
    if optimizer != "SLSQP":
        raise ValueError(
            f"avy/Sizing optimizer {optimizer!r}: omd drives plans with "
            "OpenMDAO's ScipyOptimizeDriver, so only SLSQP is available here. "
            "Use the Aviary server (avy-cli / avy-server) for IPOPT or SNOPT."
        )
    max_iter = int(config.get("max_iter", 50))

    objective = config.get("objective", "fuel")
    if objective not in _OBJECTIVES:
        raise ValueError(
            f"avy/Sizing objective {objective!r} must be one of {_OBJECTIVES}."
        )

    subsystem_specs = config.get("external_subsystems", []) or []
    for entry in subsystem_specs:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ValueError(
                "avy/Sizing external_subsystems entries must be dicts with a "
                f"'name' key (optional 'config'), got {entry!r}."
            )

    target_range_nm = operating_points.get(
        "target_range_nm", config.get("target_range_nm")
    )
    phase_info = _load_phase_info(
        config.get("phase_info_module", DEFAULT_PHASE_INFO_MODULE), target_range_nm
    )

    overrides = dict(config.get("overrides") or {})
    validate_deck_overrides(overrides)
    aircraft_data = load_deck(config["deck"], overrides)
    builders = build_external_subsystems(subsystem_specs)

    # -- the level-2 sequence, on the bare group ------------------------------
    from aviary.core.aviary_group import AviaryGroup
    from aviary.variable_info.enums import Verbosity
    from aviary.variable_info.functions import setup_model_options
    from aviary.variable_info.variable_meta_data import CoreMetaData
    from aviary.variable_info.variables import Settings

    verbosity = Verbosity.QUIET
    grp = AviaryGroup()
    grp.meta_data = CoreMetaData.copy()
    grp.load_inputs(aircraft_data, phase_info, verbosity=verbosity)
    grp.load_external_subsystems(builders, verbosity=verbosity)
    grp.check_and_preprocess_inputs(verbosity=verbosity)

    prob = om.Problem(reports=False)
    grp.add_pre_mission_systems(verbosity=verbosity)
    grp.add_phases(verbosity=verbosity, comm=prob.comm)
    grp.add_post_mission_systems(verbosity=verbosity)
    grp.link_phases(verbosity=verbosity, comm=prob.comm)

    problem_type = grp.aviary_inputs.get_val(Settings.PROBLEM_TYPE)
    grp.add_design_variables(problem_type=problem_type, verbosity=verbosity)
    _add_objective(grp, objective)

    prob.model.add_subsystem("aviary", grp, promotes=["*"])

    # Aviary options travel by OpenMDAO model_options keyed on the group's
    # path. Computed on this problem, and republished in metadata so the
    # materializer can re-key them under the component id in a composite.
    setup_model_options(
        prob, grp.aviary_inputs, grp.meta_data, prefix="aviary", group=grp
    )
    model_options = {pattern: opts for pattern, opts in prob.model_options.items()}

    def _post_setup(problem: om.Problem) -> None:
        # dymos initial guesses are set_val calls relative to the group --
        # valid at any depth, but only after setup().
        grp.set_initial_guesses(verbosity=verbosity)
        problem.set_solver_print(0)

    var_paths = {short: path for short, (path, _units) in _OUTPUTS.items()}
    metadata: FactoryMetadata = {
        "point_name": "aviary",
        "output_names": [path for path, _units in _OUTPUTS.values()],
        "var_paths": var_paths,
        "initial_values": {},
        "component_family": "avy",
        # generic materializer hooks (see module docstring)
        "self_optimizing": objective != "none",
        "requires_driver": True,
        "driver_defaults": {
            "type": optimizer,
            "options": {"maxiter": max_iter, "tol": 1e-9},
        },
        "driver_coloring": True,
        "model_options": model_options,
        "post_setup": [_post_setup],
        "setup_warning_filters": [om.OpenMDAOWarning, om.PromotionWarning],
        # result extraction (run.py)
        "avy_outputs": dict(_OUTPUTS),
        "avy_objective": objective,
        "avy_external_subsystems": [e["name"] for e in subsystem_specs],
    }
    return prob, metadata


# Plan-level marker (read by run.py before materialization): this component
# brings its own DVs/constraints/objective, so mode=optimize needs no
# plan-level design_variables/objective.
build_avy_sizing.self_optimizing = True  # type: ignore[attr-defined]

__all__ = ["build_avy_sizing", "DEFAULT_PHASE_INFO_MODULE"]
