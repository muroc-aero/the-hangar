"""Aviary run lifecycle management.

Every Aviary run is a driver run (dymos collocation + optimizer), and the
upstream problem has two process-global hazards for a long-lived server:

- OpenMDAO problem names collide across repeated runs in one process, so
  ``_clear_problem_names()`` must be called before each run;
- reports, recorder files, and off-design ``*_out`` directories land in the
  *current working directory*, so each run executes inside a managed
  per-run scratch directory under the artifact area.

``os.chdir`` is process-global, so runs are serialized behind a lock. All
aviary imports are lazy (see the dependency note in pyproject.toml).

Off-design and payload-range analyses need a live sized AviaryProblem, and
no live Problem is cached in the session (same policy as hangar-pyc, whose
off-design rebuilds and re-solves the design point every call) -- so those
entry points re-run the sizing inside the same scratch/lock block and then
fly the off-design mission(s) from it.
"""

from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

_RUN_LOCK = threading.Lock()

# os.chdir is process-global, so while a run holds the lock every relative
# path in the process resolves against that run's scratch dir. Anchor
# scratch paths to the cwd at import time (server/CLI startup, before any
# run) so a queued run's scratch never resolves inside the active run's.
_LAUNCH_CWD = Path.cwd()

VALID_OPTIMIZERS = ("SLSQP", "IPOPT", "SNOPT")

# Tool-facing mission_type -> Aviary ProblemType value
OFF_DESIGN_TYPES = {
    "max_range": "off_design_max_range",
    "min_fuel": "off_design_min_fuel",
}


def require_aviary():
    """Import and return the aviary package, with an actionable error if absent."""
    try:
        import aviary  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "The 'aviary' package is not installed in this environment. "
            "Aviary requires openmdao>=3.43 (numpy>=2) and cannot share the "
            "main hangar venv; run `bash scripts/setup-avy-venv.sh` and use "
            ".venv-avy (avy-server / avy-cli run from it), or use the "
            "hangar-avy Docker image."
        ) from exc
    return aviary


def check_optimizer_available(optimizer: str) -> None:
    """Raise if the requested optimizer cannot run in this environment."""
    if optimizer not in VALID_OPTIMIZERS:
        raise ValueError(
            f"Unknown optimizer {optimizer!r}. Valid: {', '.join(VALID_OPTIMIZERS)}"
        )
    if optimizer in ("IPOPT", "SNOPT"):
        try:
            from pyoptsparse import OPT  # noqa: F401
        except ImportError:
            raise ValueError(
                f"Optimizer {optimizer!r} requires pyoptsparse, which is not "
                "installed (it is not pip-installable; see "
                "https://github.com/OpenMDAO/build_pyoptsparse). Use "
                "optimizer='SLSQP' instead."
            ) from None


@contextlib.contextmanager
def _scratch_run(scratch_dir: str | Path | None):
    """Serialize the run and execute it inside the scratch cwd.

    The scratch path is anchored to the launch cwd, and created only after
    the lock is held -- doing either against the *current* cwd would race
    with the run that holds the lock (its chdir is process-global).
    """
    from openmdao.core.problem import _clear_problem_names

    scratch = Path(scratch_dir) if scratch_dir else _LAUNCH_CWD
    if not scratch.is_absolute():
        scratch = _LAUNCH_CWD / scratch

    with _RUN_LOCK:
        old_cwd = os.getcwd()
        scratch.mkdir(parents=True, exist_ok=True)
        os.chdir(scratch)
        try:
            _clear_problem_names()
            yield
        finally:
            os.chdir(old_cwd)


def _solve_sizing(aircraft_data, phase_info, optimizer, max_iter, subsystems=()):
    """Run the sizing optimization; caller must hold the scratch context."""
    from aviary.interface.run_aviary import run_aviary

    return run_aviary(
        aircraft_data,
        phase_info,
        optimizer=optimizer,
        max_iter=max_iter,
        subsystems=list(subsystems),
        make_plots=False,
        verbosity=0,
    )


def run_sizing_problem(
    aircraft_data,
    phase_info: dict,
    optimizer: str = "SLSQP",
    max_iter: int = 50,
    scratch_dir: str | Path | None = None,
    subsystems=(),
):
    """Run an Aviary sizing problem in a managed scratch cwd; return the problem.

    ``aircraft_data`` is a deck path (str) or AviaryValues. ``subsystems``
    are materialized SubsystemBuilders joining the problem (the coupled
    external-subsystem path). Blocking -- call from a worker thread (the
    tools use ``asyncio.to_thread``).
    """
    require_aviary()
    with _scratch_run(scratch_dir):
        return _solve_sizing(aircraft_data, phase_info, optimizer, max_iter, subsystems)


def run_precompute_sizing_problem(
    aircraft_data,
    phase_info: dict,
    subsystem_specs: list[dict],
    optimizer: str = "SLSQP",
    max_iter: int = 50,
    scratch_dir: str | Path | None = None,
    feedback: str = "none",
    fixed_point_max_iter: int = 4,
    fixed_point_tol: float = 1e-3,
):
    """Sequential (fixed-point) external-subsystem sizing -- W3.2.

    Runs the OAS wing-mass sub-optimization *outside* the Aviary problem,
    applies the result as a plain deck override on ``Aircraft.Wing.MASS``
    (Aviary's ``override_aviary_vars`` renames the FLOPS output away when
    the deck provides the value), and runs a standard sizing. Convergence
    properties equal plain sizing's.

    With the default config the sub-opt's inputs are constants, so a single
    pass IS the fixed point -- exactly equivalent to the coupled mode
    (whose wing mass also never moves; its extra sub-opts are re-solves at
    unchanged inputs). ``feedback="mission_fuel"`` opts into feeding the
    *sized* mission fuel back into the wing load-relief input and
    iterating -- a deliberate semantic departure from upstream's
    capacity-driven coupling, for studies that want the wing sized by
    actual fuel load.

    Returns ``(prob, meta)`` where ``meta`` records mode, per-pass history
    (wing mass, fuel, sub-opt seconds, sizing success), and convergence of
    the fixed point. Only ``oas_wing_mass`` specs are supported.
    """
    import copy as _copy
    import time as _time

    from hangar.avy.subsystems.oas_wing_mass import resolve_config, run_wing_mass_sub_opt

    if feedback not in ("none", "mission_fuel"):
        raise ValueError(f"Unknown feedback mode {feedback!r}; use 'none' or 'mission_fuel'")
    names = [spec.get("name") for spec in subsystem_specs]
    if names != ["oas_wing_mass"]:
        raise ValueError(
            "precompute mode currently supports exactly one 'oas_wing_mass' "
            f"subsystem, got {names!r}. Use coupled mode for other combinations."
        )
    config = dict(subsystem_specs[0].get("config") or {})
    resolved = resolve_config(config)
    require_aviary()

    from aviary.variable_info.variables import Aircraft, Mission

    if isinstance(aircraft_data, (str, Path)):
        from aviary.utils.process_input_decks import create_vehicle

        aircraft_values, _guesses = create_vehicle(str(aircraft_data))
    else:
        aircraft_values = aircraft_data

    fuel_lbm = resolved["fuel_lbm"]
    if fuel_lbm is None:
        # deck-driven semantics: load relief from the wing fuel capacity
        fuel_lbm = float(
            aircraft_values.get_val(Aircraft.Fuel.WING_FUEL_MASS_CAPACITY, "lbm")
        )

    passes = []
    n_passes = fixed_point_max_iter if feedback == "mission_fuel" else 1
    converged_fp = feedback == "none"
    prob = None
    with _scratch_run(scratch_dir):
        from openmdao.core.problem import _clear_problem_names

        for i in range(n_passes):
            t0 = _time.time()
            wing_mass_lbm = run_wing_mass_sub_opt(
                {**config, "fuel_lbm": fuel_lbm}, aviary_values=aircraft_values
            )
            sub_opt_s = _time.time() - t0

            data = _copy.deepcopy(aircraft_values)
            data.set_val(Aircraft.Wing.MASS, wing_mass_lbm, "lbm")
            _clear_problem_names()
            prob = _solve_sizing(
                data, _copy.deepcopy(phase_info), optimizer, max_iter
            )
            new_fuel_lbm = float(prob.get_val(Mission.TOTAL_FUEL_MASS, units="lbm").ravel()[0])
            passes.append(
                {
                    "pass": i + 1,
                    "fuel_input_lbm": fuel_lbm,
                    "wing_mass_lbm": wing_mass_lbm,
                    "sized_total_fuel_lbm": new_fuel_lbm,
                    "sub_opt_seconds": round(sub_opt_s, 1),
                    "sizing_success": bool(prob.result.success),
                }
            )
            if feedback != "mission_fuel":
                break
            if abs(new_fuel_lbm - fuel_lbm) <= fixed_point_tol * max(abs(fuel_lbm), 1.0):
                converged_fp = True
                break
            fuel_lbm = new_fuel_lbm

    meta = {
        "mode": "precompute",
        "feedback": feedback,
        "passes": passes,
        "fixed_point_converged": converged_fp,
        "wing_mass_lbm": passes[-1]["wing_mass_lbm"],
    }
    return prob, meta


def run_off_design_problem(
    aircraft_data,
    phase_info: dict,
    mission_type: str,
    optimizer: str = "SLSQP",
    max_iter: int = 50,
    scratch_dir: str | Path | None = None,
    subsystems=(),
    **off_design_kwargs,
):
    """Size the aircraft, then fly an off-design mission from the sized design.

    ``mission_type`` is a key of ``OFF_DESIGN_TYPES``. ``off_design_kwargs``
    are forwarded to ``AviaryProblem.run_off_design_mission`` (e.g.
    ``mission_range``, ``mission_gross_mass``, ``cargo_mass``, ``num_pax``).
    Returns ``(sizing_prob, off_design_prob)``. Blocking.
    """
    require_aviary()
    problem_type = OFF_DESIGN_TYPES[mission_type]

    with _scratch_run(scratch_dir):
        sizing_prob = _solve_sizing(
            aircraft_data, phase_info, optimizer, max_iter, subsystems
        )
        od_prob = sizing_prob.run_off_design_mission(
            problem_type=problem_type,
            optimizer=optimizer,
            verbosity=0,
            **off_design_kwargs,
        )
    return sizing_prob, od_prob


def run_payload_range_problem(
    aircraft_data,
    phase_info: dict,
    optimizer: str = "SLSQP",
    max_iter: int = 50,
    scratch_dir: str | Path | None = None,
    subsystems=(),
):
    """Size the aircraft, then run the payload-range off-design missions.

    Returns ``(sizing_prob, (max_fuel_payload_prob, ferry_prob))``; the
    inner tuple is empty when the sizing did not converge (a diagram from
    an unconverged design is meaningless -- and upstream's own skip is
    verbosity-gated away at QUIET, plus it returns None rather than () when
    an off-design mission fails, so both cases are normalized here).
    Blocking; roughly 3x a plain sizing run.
    """
    require_aviary()
    with _scratch_run(scratch_dir):
        sizing_prob = _solve_sizing(
            aircraft_data, phase_info, optimizer, max_iter, subsystems
        )
        if sizing_prob.result.success:
            pr_probs = sizing_prob.run_payload_range(verbosity=0) or ()
        else:
            pr_probs = ()
    return sizing_prob, pr_probs


def load_deck(deck_path: str, overrides: dict | None = None):
    """Load an aircraft deck into AviaryValues and apply variable overrides.

    ``overrides`` maps Aviary variable names (``aircraft:wing:span`` style)
    to either a bare value (metadata default units) or a [value, units] pair.
    Returns the AviaryValues when overrides exist, else the deck path itself
    (which keeps Aviary's problem naming from the file stem).
    """
    require_aviary()
    if not overrides:
        return deck_path

    from aviary.utils.process_input_decks import create_vehicle
    from aviary.variable_info.variable_meta_data import _MetaData

    aircraft_values, _guesses = create_vehicle(deck_path)
    for name, spec in overrides.items():
        if isinstance(spec, (list, tuple)) and len(spec) == 2 and isinstance(spec[1], str):
            value, units = spec
        else:
            value, units = spec, _MetaData[name]["units"]
        aircraft_values.set_val(name, value, units)
    return aircraft_values
