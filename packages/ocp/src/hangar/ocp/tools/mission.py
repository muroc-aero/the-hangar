"""Mission configuration and analysis tools."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from hangar.sdk.helpers import _suppress_output

from hangar.ocp.builders import build_mission_problem
from hangar.ocp.results import extract_mission_results, extract_trajectory_data
from hangar.ocp.state import sessions as _sessions
from hangar.ocp.tools._helpers import _finalize_analysis, _make_run_id
from hangar.ocp.validation import validate_mission_results
from hangar.ocp.validators import (
    validate_mission_params,
    validate_mission_type,
    validate_num_nodes,
    validate_session_ready_for_analysis,
)


async def configure_mission(
    mission_type: Annotated[
        str,
        "Mission type: 'full' (with balanced-field takeoff), "
        "'basic' (climb/cruise/descent only), "
        "'with_reserve' (basic + reserve phases + loiter)",
    ] = "full",
    cruise_altitude: Annotated[float, "Cruise altitude in ft"] = 18000.0,
    mission_range: Annotated[float, "Mission range in NM"] = 250.0,
    # Climb
    climb_vs: Annotated[float, "Climb vertical speed in ft/min"] = 850.0,
    climb_Ueas: Annotated[float, "Climb equivalent airspeed in kn"] = 104.0,
    # Cruise
    cruise_Ueas: Annotated[float, "Cruise equivalent airspeed in kn"] = 129.0,
    # Descent
    descent_vs: Annotated[
        float,
        "Descent vertical speed in ft/min (positive value; will be negated internally)",
    ] = 400.0,
    descent_Ueas: Annotated[float, "Descent equivalent airspeed in kn"] = 100.0,
    # Payload
    payload: Annotated[float | None, "Payload in lb (for hybrid/reserve missions)"] = None,
    # Reserve (only for 'with_reserve')
    reserve_altitude: Annotated[float | None, "Reserve cruise altitude in ft"] = None,
    reserve_range: Annotated[float | None, "Reserve range in NM"] = None,
    loiter_duration: Annotated[float | None, "Loiter duration in minutes"] = None,
    # Hybrid-specific
    climb_hybridization: Annotated[
        float | None,
        "Hybridization fraction during climb (0-1, hybrid architectures only)",
    ] = None,
    cruise_hybridization: Annotated[
        float | None,
        "Hybridization fraction during cruise (0-1, hybrid architectures only)",
    ] = None,
    descent_hybridization: Annotated[
        float | None,
        "Hybridization fraction during descent (0-1, hybrid architectures only)",
    ] = None,
    # Solver
    num_nodes: Annotated[
        int,
        "Analysis nodes per phase (must be odd, e.g. 11, 21). "
        "Higher = more accurate but slower.",
    ] = 11,
    session_id: Annotated[str, "Session identifier"] = "default",
) -> dict:
    """Configure the mission profile parameters.

    Must be called after aircraft and propulsion are set.
    Returns a summary of the configured mission.
    """
    validate_mission_type(mission_type)
    validate_num_nodes(num_nodes)

    params = {
        "cruise_altitude_ft": cruise_altitude,
        "mission_range_NM": mission_range,
        "climb_vs_ftmin": climb_vs,
        "climb_Ueas_kn": climb_Ueas,
        "cruise_Ueas_kn": cruise_Ueas,
        "descent_vs_ftmin": -abs(descent_vs),
        "descent_Ueas_kn": descent_Ueas,
    }

    if payload is not None:
        params["payload_lb"] = payload
    if climb_hybridization is not None:
        params["climb_hybridization"] = climb_hybridization
    if cruise_hybridization is not None:
        params["cruise_hybridization"] = cruise_hybridization
    if descent_hybridization is not None:
        params["descent_hybridization"] = descent_hybridization
    if reserve_altitude is not None:
        params["reserve_altitude_ft"] = reserve_altitude
    if reserve_range is not None:
        params["reserve_range_NM"] = reserve_range
    if loiter_duration is not None:
        params["loiter_duration_min"] = loiter_duration

    validate_mission_params(params)

    session = _sessions.get(session_id)
    session.mission_type = mission_type
    session.mission_params = params
    session.num_nodes = num_nodes
    session.invalidate_cache()

    # Build phases list for summary
    if mission_type == "full":
        phases = ["v0v1", "v1vr", "v1v0", "rotate", "climb", "cruise", "descent"]
    elif mission_type == "with_reserve":
        phases = [
            "climb", "cruise", "descent",
            "reserve_climb", "reserve_cruise", "reserve_descent", "loiter",
        ]
    else:
        phases = ["climb", "cruise", "descent"]

    return {
        "mission_type": mission_type,
        "phases": phases,
        "cruise_altitude_ft": cruise_altitude,
        "mission_range_NM": mission_range,
        "num_nodes": num_nodes,
        "parameters": params,
        "next_step": "Call run_mission_analysis() to execute the analysis.",
    }


async def run_mission_analysis(
    session_id: Annotated[str, "Session identifier"] = "default",
    run_name: Annotated[str | None, "Optional label for this run"] = None,
) -> dict:
    """Run the full mission analysis using the configured aircraft, propulsion, and mission.

    Requires prior calls to:
    1. ``load_aircraft_template()`` or ``define_aircraft()``
    2. ``set_propulsion_architecture()``
    3. ``configure_mission()`` (optional -- uses defaults if not called)

    Returns a response envelope (schema_version='1.0') with fuel burn, OEW,
    TOFL, phase-by-phase results, validation findings, and telemetry.
    """
    session = _sessions.get(session_id)
    validate_session_ready_for_analysis(session)

    run_id = _make_run_id()
    t0 = time.perf_counter()
    cache_hit = session.get_cached_problem() is not None

    def _run():
        cached = session.get_cached_problem()
        if cached is not None:
            prob, metadata = cached
            # Update mission params on the cached problem
            from hangar.ocp.builders import _set_mission_values, PROPULSION_ARCHITECTURES
            arch_info = PROPULSION_ARCHITECTURES[session.propulsion_architecture]
            is_hybrid = arch_info["has_battery"] and arch_info["has_fuel"]
            from hangar.ocp.config.defaults import DEFAULT_MISSION_PARAMS
            params = {**DEFAULT_MISSION_PARAMS, **session.mission_params}
            _set_mission_values(
                prob, params, metadata["phases"],
                session.num_nodes, is_hybrid, session.mission_type,
            )
        else:
            prob, metadata = build_mission_problem(
                aircraft_data=session.aircraft_data,
                architecture=session.propulsion_architecture,
                mission_type=session.mission_type,
                mission_params=session.mission_params,
                num_nodes=session.num_nodes,
                solver_settings=session.solver_settings,
                propulsion_overrides=session.propulsion_overrides,
            )
            session.store_problem(prob, metadata)

        prob.run_model()

        results = extract_mission_results(prob, metadata)
        trajectory = extract_trajectory_data(prob, metadata)
        return results, trajectory, metadata

    results, trajectory, metadata = await asyncio.to_thread(_suppress_output, _run)

    # Build inputs dict for the envelope
    inputs = {
        "architecture": session.propulsion_architecture,
        "mission_type": session.mission_type,
        "template": session.aircraft_template,
        **session.mission_params,
    }

    findings = validate_mission_results(results, inputs)

    return await _finalize_analysis(
        tool_name="run_mission_analysis",
        run_id=run_id,
        session=session,
        session_id=session_id,
        analysis_type="mission",
        inputs=inputs,
        results=results,
        trajectory=trajectory,
        findings=findings,
        t0=t0,
        cache_hit=cache_hit,
        run_name=run_name,
    )
