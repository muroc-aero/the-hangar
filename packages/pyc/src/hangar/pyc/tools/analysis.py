"""Analysis tools — run_design_point, run_off_design."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from hangar.sdk.helpers import _suppress_output
from hangar.sdk.state import sessions as _sessions

from hangar.pyc.archetypes import get_archetype
from hangar.pyc.builders import build_design_problem, build_multipoint_problem
from hangar.pyc.results import extract_cycle_results
from hangar.pyc.validators import (
    validate_engine_exists,
    validate_flight_conditions,
    validate_thrust_target,
    validate_T4_target,
)
from hangar.pyc.validation import validate_cycle_results
from hangar.pyc.tools._helpers import _finalize_analysis, _make_run_id


async def run_design_point(
    engine_name: Annotated[str, "Name of engine created by create_engine"] = "engine",
    alt: Annotated[float, "Design altitude (ft)"] = 0.0,
    MN: Annotated[float, "Design Mach number"] = 0.000001,
    Fn_target: Annotated[float, "Design net thrust target (lbf)"] = 11800.0,
    T4_target: Annotated[float, "Turbine inlet temperature target (degR)"] = 2370.0,
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Run the engine at its design point to size all components.

    This must be called before ``run_off_design``. The design point sets the
    engine geometry (areas, map scalars) which are then held fixed for
    off-design evaluation.

    Returns a versioned response envelope with performance metrics (TSFC, Fn,
    OPR), flow station data, and component details.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)

    engine_cfg = validate_engine_exists(session, engine_name)
    validate_flight_conditions(alt, MN)
    validate_thrust_target(Fn_target)
    validate_T4_target(T4_target)

    archetype = engine_cfg["archetype"]
    params = engine_cfg["params"]
    arch_meta = get_archetype(archetype)

    design_conditions = {
        "alt": alt,
        "MN": MN,
        "Fn_target": Fn_target,
        "T4_target": T4_target,
    }
    run_id = _make_run_id()

    # Build and solve
    def _run():
        prob = build_design_problem(archetype, params, design_conditions)
        prob.set_solver_print(level=-1)
        prob.run_model()
        return prob

    prob = await asyncio.to_thread(_suppress_output, _run)

    # Store the solved problem for off-design reuse
    engine_cfg["design_prob"] = prob
    engine_cfg["design_solved"] = True
    engine_cfg["design_conditions"] = design_conditions

    # Extract results
    results = extract_cycle_results(prob, "", arch_meta)

    # Validate
    findings = validate_cycle_results(results, archetype)

    inputs = {
        "engine_name": engine_name,
        "archetype": archetype,
        "alt_ft": alt,
        "MN": MN,
        "Fn_target_lbf": Fn_target,
        "T4_target_degR": T4_target,
        **{k: v for k, v in params.items() if k != "_overrides"},
    }

    # Save under the tool-container session_id (the `session_id` kwarg), not
    # the provenance session id; oas/ocp do the same, and cross-tool artifact
    # lookups rely on it.
    return await _finalize_analysis(
        tool_name="run_design_point",
        run_id=run_id,
        session=session,
        session_id=session_id,
        engine_name=engine_name,
        analysis_type="design",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )


async def run_off_design(
    engine_name: Annotated[str, "Name of engine (must have run_design_point first)"] = "engine",
    alt: Annotated[float, "Off-design altitude (ft)"] = 0.0,
    MN: Annotated[float, "Off-design Mach number"] = 0.000001,
    Fn_target: Annotated[float, "Off-design thrust target (lbf)"] = 11000.0,
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Evaluate the engine at an off-design operating point.

    Requires ``run_design_point`` to have been called first — the design point
    sets the engine geometry that is held fixed during off-design analysis.

    Off-design analysis uses different balance equations: the solver adjusts
    fuel-air ratio (FAR), shaft speed (Nmech), and mass flow (W) to match
    the thrust target at the given flight conditions.

    Returns a versioned response envelope with performance metrics, flow
    stations, and component data at the off-design condition.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)

    engine_cfg = validate_engine_exists(session, engine_name)
    if not engine_cfg.get("design_solved"):
        raise ValueError(
            f"Engine '{engine_name}' has not been sized yet. "
            f"Call run_design_point first."
        )
    validate_flight_conditions(alt, MN)
    validate_thrust_target(Fn_target)

    archetype = engine_cfg["archetype"]
    params = engine_cfg["params"]
    arch_meta = get_archetype(archetype)
    design_conditions = engine_cfg["design_conditions"]
    run_id = _make_run_id()

    od_point = {
        "name": "OD0",
        "MN": MN,
        "alt": alt,
        "Fn_target": Fn_target,
    }

    def _run():
        prob = build_multipoint_problem(
            archetype, params, design_conditions, [od_point]
        )
        prob.set_solver_print(level=-1)
        prob.run_model()
        return prob

    prob = await asyncio.to_thread(_suppress_output, _run)

    # Extract off-design results
    results = extract_cycle_results(prob, "OD0", arch_meta)

    # Also extract design-point results for context
    design_results = extract_cycle_results(prob, "DESIGN", arch_meta)
    results["design_point"] = design_results.get("performance", {})

    findings = validate_cycle_results(results, archetype)

    inputs = {
        "engine_name": engine_name,
        "archetype": archetype,
        "alt_ft": alt,
        "MN": MN,
        "Fn_target_lbf": Fn_target,
        "analysis_type": "off_design",
    }

    return await _finalize_analysis(
        tool_name="run_off_design",
        run_id=run_id,
        session=session,
        session_id=session_id,
        engine_name=engine_name,
        analysis_type="off_design",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )
