"""Analysis tools -- run_sizing, run_off_design, run_payload_range.

Every Aviary run solves the mission trajectory (dymos collocation) and the
aircraft sizing together under a driver -- there is no cheap evaluate-only
path. That is why the primary tool is named run_sizing and not
run_mission_analysis: the mission IS the sizing optimization.

Off-design and payload-range need a live sized problem; no Problem is
cached in the session (same policy as hangar-pyc), so those tools re-run
the sizing internally -- expect ~2x / ~3x the run_sizing wall-clock.
"""

from __future__ import annotations

import asyncio
import copy
import shutil
import time
from typing import Annotated

from hangar.sdk.helpers import _suppress_output
from hangar.avy.state import sessions as _sessions

from hangar.avy.config.defaults import DEFAULT_MAX_ITER, DEFAULT_OPTIMIZER
from hangar.avy.missions import MISSION_METHODS, build_phase_info, summarize_phase_info
from hangar.avy.results import (
    extract_payload_range_points,
    extract_sizing_results,
)
from hangar.avy.runner import (
    OFF_DESIGN_TYPES,
    check_optimizer_available,
    load_deck,
    require_aviary,
    run_off_design_problem,
    run_payload_range_problem,
    run_precompute_sizing_problem,
    run_sizing_problem,
)
from hangar.avy.subsystems import build_external_subsystems
from hangar.avy.validation import (
    design_point_finding,
    external_subsystem_findings,
    payload_range_findings,
    validate_sizing_results,
)
from hangar.avy.validators import validate_aircraft_exists, validate_max_iter
from hangar.avy.tools._helpers import _finalize_analysis, _make_run_id, _run_scratch_dir

_TOP_LEVEL = ("pre_mission", "post_mission")


def _prepare_run(session, aircraft_name: str, optimizer: str, max_iter: int):
    """Shared preflight for the analysis tools.

    Validates inputs and returns ``(aircraft_cfg, phase_info, phase_names,
    target_range_nm, phases_summary)``. The returned phase_info is a DEEP
    COPY of the session-stored mission: Aviary mutates the dict it is given
    in place (load_inputs replaces each phase's user_options with the fully
    defaulted expansion, and run_payload_range widens the cruise duration
    bounds), so handing over the stored dict would make repeat runs solve a
    different problem. The summary is taken before the copy is run, so the
    envelope records the *configured* mission, not the mutated one.
    """
    aircraft_cfg = validate_aircraft_exists(session, aircraft_name)
    if aircraft_cfg["mission_method"] not in MISSION_METHODS:
        raise ValueError(
            f"Aircraft '{aircraft_name}' uses a "
            f"{aircraft_cfg['mission_method']!r} deck, which this server "
            f"cannot run yet. Load an energy_state template instead."
        )
    check_optimizer_available(optimizer)
    validate_max_iter(max_iter)
    require_aviary()

    mission = aircraft_cfg.get("mission")
    if mission is None:
        phase_info = build_phase_info(mission_method="energy_state")
        target_range_nm = None
    else:
        phase_info = copy.deepcopy(mission["phase_info"])
        target_range_nm = mission.get("target_range_nm")

    # The default mission's target range lives in the phase_info even when
    # configure_mission was never called; recover it for the range check.
    if target_range_nm is None:
        target = phase_info.get("post_mission", {}).get("target_range")
        if target is not None and phase_info["post_mission"].get("constrain_range"):
            value, units = target
            if units in ("nmi", "NM"):
                target_range_nm = float(value)
            else:
                from openmdao.utils.units import convert_units

                target_range_nm = float(convert_units(value, units, "nmi"))

    phase_names = [p for p in phase_info if p not in _TOP_LEVEL]
    phases_summary = summarize_phase_info(phase_info)
    return aircraft_cfg, phase_info, phase_names, target_range_nm, phases_summary


def _cleanup_scratch(scratch_dir: str, results: dict) -> None:
    """Remove the per-run scratch dir after a converged run.

    Scratch dirs (dymos recorders, off-design ``*_out`` dirs) are several MB
    per run and are never read back by the tools; keep them only for failed
    runs, where they are the debugging evidence.
    """
    if results.get("optimizer", {}).get("success"):
        shutil.rmtree(scratch_dir, ignore_errors=True)


async def run_sizing(
    aircraft_name: Annotated[str, "Name of aircraft loaded by load_aircraft_template"] = "aircraft",
    optimizer: Annotated[
        str,
        "Optimizer: 'SLSQP' (default, always available), 'IPOPT' or 'SNOPT' "
        "(require pyoptsparse; rejected with instructions when absent).",
    ] = DEFAULT_OPTIMIZER,
    max_iter: Annotated[int, "Maximum optimizer iterations"] = DEFAULT_MAX_ITER,
    subsystem_mode: Annotated[
        str,
        "How attached external subsystems couple: 'coupled' (inside the "
        "Aviary problem, upstream semantics) or 'precompute' (sub-opt runs "
        "once up front, result applied as a deck override -- equivalent "
        "for the feed-forward oas_wing_mass and cheaper across repeat "
        "runs). Ignored when no subsystem is attached.",
    ] = "coupled",
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Run the coupled aircraft-sizing + mission optimization (ProblemType SIZING).

    Sizes the aircraft (gross mass, fuel) while optimizing the mission
    trajectory against the configured phase_info (default: the 3-phase
    energy_state climb/cruise/descent mission). Takes tens of seconds to
    minutes depending on mission complexity; an attached oas_wing_mass
    subsystem adds a ~40 s nested wingbox sub-optimization.

    ALWAYS check validation.passed (the 'optimizer.success' finding) before
    trusting results: optimizer non-convergence does not raise, it returns
    the last iterate with a failed flag.

    Returns a versioned response envelope with performance (gross mass, fuel,
    range, mission time), design summary, and a downsampled mission timeseries.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)

    if subsystem_mode not in ("coupled", "precompute"):
        raise ValueError(
            f"Unknown subsystem_mode {subsystem_mode!r}; use 'coupled' or 'precompute'."
        )

    aircraft_cfg, phase_info, phase_names, target_range_nm, phases_summary = _prepare_run(
        session, aircraft_name, optimizer, max_iter
    )
    subsystem_specs = list(aircraft_cfg.get("external_subsystems") or [])
    run_id = _make_run_id()
    scratch_dir = _run_scratch_dir(session, session_id, run_id)

    def _run():
        aircraft_data = load_deck(aircraft_cfg["deck"], aircraft_cfg["overrides"])
        if subsystem_specs and subsystem_mode == "precompute":
            prob, meta = run_precompute_sizing_problem(
                aircraft_data,
                phase_info,
                subsystem_specs,
                optimizer=optimizer,
                max_iter=max_iter,
                scratch_dir=scratch_dir,
            )
        else:
            builders = build_external_subsystems(subsystem_specs)
            prob = run_sizing_problem(
                aircraft_data,
                phase_info,
                optimizer=optimizer,
                max_iter=max_iter,
                scratch_dir=scratch_dir,
                subsystems=builders,
            )
            meta = {"mode": "coupled"} if subsystem_specs else None
        results = extract_sizing_results(prob, phase_names)
        if meta is not None:
            results["subsystems"] = meta
        return results

    results = await asyncio.to_thread(_suppress_output, _run)
    _cleanup_scratch(scratch_dir, results)

    aircraft_cfg["sized_run_id"] = run_id

    findings = validate_sizing_results(
        results, optimizer, max_iter, target_range_nmi=target_range_nm
    )
    findings.extend(
        external_subsystem_findings(
            subsystem_specs,
            aircraft_cfg["template"],
            results.get("design", {}).get("wing_mass_lbm"),
        )
    )

    inputs = {
        "aircraft_name": aircraft_name,
        "template": aircraft_cfg["template"],
        "deck": aircraft_cfg["deck"],
        "overrides": aircraft_cfg["overrides"],
        "external_subsystems": subsystem_specs,
        "subsystem_mode": subsystem_mode if subsystem_specs else None,
        "optimizer": optimizer,
        "max_iter": max_iter,
        "target_range_nm": target_range_nm,
        "phases": phases_summary,
    }

    return await _finalize_analysis(
        tool_name="run_sizing",
        run_id=run_id,
        session=session,
        session_id=session_id,
        aircraft_name=aircraft_name,
        analysis_type="sizing",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )


async def run_off_design(
    aircraft_name: Annotated[str, "Name of aircraft loaded by load_aircraft_template"] = "aircraft",
    mission_type: Annotated[
        str,
        "Off-design mission type: 'max_range' (fixed fuel, maximize range) or "
        "'min_fuel' (fixed range via mission_range_nm, minimize fuel).",
    ] = "max_range",
    mission_range_nm: Annotated[
        float | None,
        "Fixed mission range (nmi) for 'min_fuel' missions. Unused for 'max_range'.",
    ] = None,
    mission_gross_mass_lbm: Annotated[
        float | None,
        "Takeoff gross mass (lbm) for this mission. Defaults to the design "
        "gross mass; for 'min_fuel' it is the initial guess.",
    ] = None,
    cargo_mass_lbm: Annotated[
        float | None, "Total cargo mass (lbm) override for this mission."
    ] = None,
    num_pax: Annotated[
        int | None, "Passenger count override for this mission."
    ] = None,
    optimizer: Annotated[
        str, "Optimizer for both the sizing and off-design runs."
    ] = DEFAULT_OPTIMIZER,
    max_iter: Annotated[int, "Maximum optimizer iterations (sizing run)"] = DEFAULT_MAX_ITER,
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Fly an off-design mission with the sized aircraft (design held fixed).

    The design gross mass and empty mass come from the sizing optimization;
    the off-design mission varies fuel/gross mass to fly the requested
    mission ('max_range': how far at a given load; 'min_fuel': how little
    fuel over a fixed range).

    No sized problem is cached in the session, so this re-runs the sizing
    internally first -- expect roughly 2x the run_sizing wall-clock.

    Returns an envelope whose results describe the OFF-DESIGN mission, with
    the sizing headline metrics attached under results.design_point.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)

    if mission_type not in OFF_DESIGN_TYPES:
        raise ValueError(
            f"Unknown mission_type {mission_type!r}. "
            f"Valid: {', '.join(sorted(OFF_DESIGN_TYPES))}"
        )
    if mission_type == "min_fuel" and mission_range_nm is None:
        raise ValueError("mission_type='min_fuel' requires mission_range_nm.")
    if mission_range_nm is not None and mission_range_nm <= 0:
        raise ValueError(f"mission_range_nm must be positive (got {mission_range_nm})")

    aircraft_cfg, phase_info, phase_names, _, _phases = _prepare_run(
        session, aircraft_name, optimizer, max_iter
    )
    subsystem_specs = list(aircraft_cfg.get("external_subsystems") or [])
    run_id = _make_run_id()
    scratch_dir = _run_scratch_dir(session, session_id, run_id)

    od_kwargs = {}
    if mission_range_nm is not None:
        od_kwargs["mission_range"] = mission_range_nm
    if mission_gross_mass_lbm is not None:
        od_kwargs["mission_gross_mass"] = mission_gross_mass_lbm
    if cargo_mass_lbm is not None:
        od_kwargs["cargo_mass"] = cargo_mass_lbm
    if num_pax is not None:
        od_kwargs["num_pax"] = num_pax

    def _run():
        aircraft_data = load_deck(aircraft_cfg["deck"], aircraft_cfg["overrides"])
        sizing_prob, od_prob = run_off_design_problem(
            aircraft_data,
            phase_info,
            mission_type,
            optimizer=optimizer,
            max_iter=max_iter,
            scratch_dir=scratch_dir,
            subsystems=build_external_subsystems(subsystem_specs),
            **od_kwargs,
        )
        results = extract_sizing_results(od_prob, phase_names)
        design = extract_sizing_results(sizing_prob, [])
        results["design_point"] = design["performance"]
        results["design_point"]["optimizer_success"] = design["optimizer"]["success"]
        return results

    results = await asyncio.to_thread(_suppress_output, _run)
    _cleanup_scratch(scratch_dir, results)

    # The off-design range is a result ('max_range') or a target ('min_fuel').
    findings = validate_sizing_results(
        results, optimizer, max_iter, target_range_nmi=mission_range_nm
    )
    # The internal sizing can fail while the off-design mission "converges"
    # from the unsized iterate -- that failure must gate validation too.
    findings.append(
        design_point_finding(results["design_point"].get("optimizer_success"))
    )
    findings.extend(
        external_subsystem_findings(
            subsystem_specs,
            aircraft_cfg["template"],
            results.get("design", {}).get("wing_mass_lbm"),
        )
    )

    inputs = {
        "aircraft_name": aircraft_name,
        "template": aircraft_cfg["template"],
        "deck": aircraft_cfg["deck"],
        "overrides": aircraft_cfg["overrides"],
        "external_subsystems": subsystem_specs,
        "mission_type": mission_type,
        "mission_range_nm": mission_range_nm,
        "mission_gross_mass_lbm": mission_gross_mass_lbm,
        "cargo_mass_lbm": cargo_mass_lbm,
        "num_pax": num_pax,
        "optimizer": optimizer,
        "max_iter": max_iter,
    }

    return await _finalize_analysis(
        tool_name="run_off_design",
        run_id=run_id,
        session=session,
        session_id=session_id,
        aircraft_name=aircraft_name,
        analysis_type="off_design",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )


async def run_payload_range(
    aircraft_name: Annotated[str, "Name of aircraft loaded by load_aircraft_template"] = "aircraft",
    optimizer: Annotated[
        str, "Optimizer for the sizing and off-design runs."
    ] = DEFAULT_OPTIMIZER,
    max_iter: Annotated[int, "Maximum optimizer iterations (sizing run)"] = DEFAULT_MAX_ITER,
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Generate the payload-range diagram for the sized aircraft.

    Runs the sizing, then two additional off-design missions (max fuel +
    payload, and ferry range) to produce the four classic payload-range
    points: max payload @ zero range, the design mission, max fuel +
    payload, and ferry range. Energy_state missions only (upstream
    limitation; reserve fuel not yet accounted for).

    No sized problem is cached in the session, so expect roughly 3x the
    run_sizing wall-clock.

    Returns an envelope with results.payload_range.points plus the sizing
    performance. If the sizing does not converge the off-design missions
    are skipped: the envelope carries only the first two points and
    validation FAILS (the optimizer.success finding) -- as with every avy
    tool, non-convergence is reported, not raised.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)

    aircraft_cfg, phase_info, phase_names, target_range_nm, _phases = _prepare_run(
        session, aircraft_name, optimizer, max_iter
    )
    subsystem_specs = list(aircraft_cfg.get("external_subsystems") or [])
    run_id = _make_run_id()
    scratch_dir = _run_scratch_dir(session, session_id, run_id)

    def _run():
        aircraft_data = load_deck(aircraft_cfg["deck"], aircraft_cfg["overrides"])
        sizing_prob, pr_probs = run_payload_range_problem(
            aircraft_data,
            phase_info,
            optimizer=optimizer,
            max_iter=max_iter,
            scratch_dir=scratch_dir,
            subsystems=build_external_subsystems(subsystem_specs),
        )
        results = extract_sizing_results(sizing_prob, phase_names)
        results["payload_range"] = {
            "points": extract_payload_range_points(sizing_prob, pr_probs),
            "off_design_success": [
                bool(p.result.success) for p in pr_probs
            ],
        }
        return results

    results = await asyncio.to_thread(_suppress_output, _run)
    _cleanup_scratch(scratch_dir, results)

    findings = validate_sizing_results(
        results, optimizer, max_iter, target_range_nmi=target_range_nm
    )
    findings.append(
        payload_range_findings(results["payload_range"])
    )
    findings.extend(
        external_subsystem_findings(
            subsystem_specs,
            aircraft_cfg["template"],
            results.get("design", {}).get("wing_mass_lbm"),
        )
    )

    inputs = {
        "aircraft_name": aircraft_name,
        "template": aircraft_cfg["template"],
        "deck": aircraft_cfg["deck"],
        "overrides": aircraft_cfg["overrides"],
        "external_subsystems": subsystem_specs,
        "optimizer": optimizer,
        "max_iter": max_iter,
        "target_range_nm": target_range_nm,
    }

    return await _finalize_analysis(
        tool_name="run_payload_range",
        run_id=run_id,
        session=session,
        session_id=session_id,
        aircraft_name=aircraft_name,
        analysis_type="payload_range",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )
