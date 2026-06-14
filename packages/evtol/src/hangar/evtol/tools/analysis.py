"""Analysis tools -- run_mission_analysis, run_sizing."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from hangar.sdk.helpers import _suppress_output
from hangar.evtol.state import sessions as _sessions

from hangar.evtol.builders import build_aircraft
from hangar.evtol.results import extract_mission_results, run_mtow_iteration
from hangar.evtol.validation import validate_mission_results, validate_sizing_results
from hangar.evtol.validators import validate_config_present
from hangar.evtol.tools._helpers import _finalize_analysis, _make_run_id


async def run_mission_analysis(
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Evaluate the configured vehicle over its mission at the as-configured MTOW.

    Builds the evtolpy aircraft from the session config and reports the three core
    mission tables -- per-segment **energy** (kW*hr), per-segment average
    **electric power** (kW), and the component **mass breakdown** (kg) -- across
    all 18 segments (including reserves), plus total-energy roll-ups and
    geometry/aero/propulsion summaries. This reproduces upstream's
    ``log_mission_segment_energy`` / ``log_power_all`` / ``log_mass_breakdown``
    scripts, which read an unsized aircraft. To converge MTOW, use run_sizing.

    Returns a versioned response envelope.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)
    config = validate_config_present(session)
    run_id = _make_run_id()

    def _run():
        aircraft = build_aircraft(config)
        return extract_mission_results(aircraft)

    results = await asyncio.to_thread(_suppress_output, _run)
    findings = validate_mission_results(results)

    inputs = {
        "max_takeoff_mass_kg": config["aircraft"]["max_takeoff_mass_kg"],
        "payload_kg": config["aircraft"]["payload_kg"],
        "rotor_count": config["propulsion"]["rotor_count"],
        "batt_spec_energy_w_h_p_kg": config["power"]["batt_spec_energy_w_h_p_kg"],
        "cruise_s": config["mission"]["cruise_s"],
    }

    return await _finalize_analysis(
        tool_name="run_mission_analysis",
        run_id=run_id,
        session=session,
        session_id=session_id,
        analysis_type="mission",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )


async def run_sizing(
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Converge the vehicle's maximum takeoff weight (MTOW).

    Runs evtolpy's MTOW iteration: starting from the configured initial MTOW, it
    recomputes empty + battery + payload mass and updates the guess until it
    converges (or the divergence safeguard trips). Reproduces upstream's
    ``log_mtow_iteration`` script.

    Returns a versioned response envelope with the converged MTOW, the full
    per-iteration convergence history, and the mass breakdown at the sized MTOW.
    A diverging iteration fails with a USER_INPUT_ERROR describing which inputs
    are likely self-inconsistent.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)
    config = validate_config_present(session)
    run_id = _make_run_id()

    def _run():
        aircraft = build_aircraft(config)
        return run_mtow_iteration(aircraft)

    results = await asyncio.to_thread(_suppress_output, _run)
    findings = validate_sizing_results(results)

    inputs = {
        "initial_mtow_kg": config["aircraft"]["max_takeoff_mass_kg"],
        "payload_kg": config["aircraft"]["payload_kg"],
        "batt_spec_energy_w_h_p_kg": config["power"]["batt_spec_energy_w_h_p_kg"],
    }

    return await _finalize_analysis(
        tool_name="run_sizing",
        run_id=run_id,
        session=session,
        session_id=session_id,
        analysis_type="sizing",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )
