"""Parameter sweep tool for trade studies."""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Annotated

from hangar.sdk.helpers import _suppress_output

from hangar.ocp.builders import build_mission_problem
from hangar.ocp.config.defaults import PROPULSION_ARCHITECTURES
from hangar.ocp.results import extract_mission_results
from hangar.ocp.state import sessions as _sessions
from hangar.ocp.tools._helpers import _finalize_analysis, _make_run_id
from hangar.ocp.validation import validate_mission_results
from hangar.ocp.validators import validate_session_ready_for_analysis


# Map user-friendly parameter names to internal param keys
_SWEEP_PARAMS = {
    "mission_range": "mission_range_NM",
    "cruise_altitude": "cruise_altitude_ft",
    "battery_weight": "_battery_weight_kg",
    "battery_specific_energy": "_battery_specific_energy",
    "hybridization": "_cruise_hybridization",
    "cruise_hybridization": "cruise_hybridization",
    "climb_hybridization": "climb_hybridization",
    "engine_rating": "_engine_rating",
    "motor_rating": "_motor_rating",
}


async def run_parameter_sweep(
    parameter: Annotated[
        str,
        "Parameter to sweep: 'mission_range', 'cruise_altitude', "
        "'battery_weight', 'battery_specific_energy', 'hybridization', "
        "'engine_rating', 'motor_rating'",
    ],
    values: Annotated[
        list[float],
        "List of values to sweep over (e.g. [200, 300, 400, 500])",
    ],
    session_id: Annotated[str, "Session identifier"] = "default",
    run_name: Annotated[str | None, "Optional label for this sweep"] = None,
) -> dict:
    """Run the mission analysis at multiple values of a single parameter.

    Returns a sweep results table with the parameter values and corresponding
    key metrics (fuel burn, OEW, TOFL, battery SOC).
    """
    if parameter not in _SWEEP_PARAMS:
        valid = ", ".join(sorted(_SWEEP_PARAMS))
        raise ValueError(
            f"Unknown sweep parameter {parameter!r}. Valid: {valid}"
        )

    session = _sessions.get(session_id)
    validate_session_ready_for_analysis(session)

    run_id = _make_run_id()
    t0 = time.perf_counter()

    def _run_sweep():
        sweep_results = []
        for val in values:
            # Create modified mission params for this sweep point
            params = dict(session.mission_params)
            param_key = _SWEEP_PARAMS[parameter]

            if param_key.startswith("_"):
                # Special handling for aircraft-data params
                ac_data = copy.deepcopy(session.aircraft_data)
                overrides = dict(session.propulsion_overrides)

                if parameter == "battery_weight":
                    ac_data["ac"]["weights"]["W_battery"] = {"value": val, "units": "kg"}
                elif parameter == "battery_specific_energy":
                    overrides["battery_specific_energy"] = val
                elif parameter == "engine_rating":
                    ac_data["ac"]["propulsion"]["engine"]["rating"]["value"] = val
                elif parameter == "motor_rating":
                    ac_data["ac"]["propulsion"]["motor"]["rating"]["value"] = val
                elif parameter == "hybridization":
                    params["cruise_hybridization"] = val

                prob, metadata = build_mission_problem(
                    aircraft_data=ac_data,
                    architecture=session.propulsion_architecture,
                    mission_type=session.mission_type,
                    mission_params=params,
                    num_nodes=session.num_nodes,
                    solver_settings=session.solver_settings,
                    propulsion_overrides=overrides,
                )
            else:
                params[param_key] = val
                prob, metadata = build_mission_problem(
                    aircraft_data=session.aircraft_data,
                    architecture=session.propulsion_architecture,
                    mission_type=session.mission_type,
                    mission_params=params,
                    num_nodes=session.num_nodes,
                    solver_settings=session.solver_settings,
                    propulsion_overrides=session.propulsion_overrides,
                )

            try:
                prob.run_model()
                results = extract_mission_results(prob, metadata)
                sweep_results.append({
                    parameter: val,
                    "converged": True,
                    **{k: v for k, v in results.items()
                       if not isinstance(v, dict)},
                })
            except Exception as exc:
                sweep_results.append({
                    parameter: val,
                    "converged": False,
                    "error": str(exc),
                })

        return sweep_results

    sweep_results = await asyncio.to_thread(_suppress_output, _run_sweep)

    # Build envelope
    inputs = {
        "parameter": parameter,
        "values": values,
        "architecture": session.propulsion_architecture,
        "mission_type": session.mission_type,
    }

    results = {
        "sweep_parameter": parameter,
        "sweep_values": values,
        "num_points": len(values),
        "sweep_results": sweep_results,
    }

    findings = []
    failed = sum(1 for r in sweep_results if not r.get("converged"))
    if failed > 0:
        from hangar.ocp.validation import ValidationFinding
        findings.append(ValidationFinding(
            check_id="numerics.sweep_convergence",
            category="numerics",
            severity="warning",
            confidence="high",
            passed=failed == 0,
            message=f"{failed}/{len(values)} sweep points failed to converge",
            remediation="Check parameter bounds and solver settings.",
        ))

    return await _finalize_analysis(
        tool_name="run_parameter_sweep",
        run_id=run_id,
        session=session,
        session_id=session_id,
        analysis_type="mission",
        inputs=inputs,
        results=results,
        trajectory=None,
        findings=findings,
        t0=t0,
        cache_hit=False,
        run_name=run_name,
    )
