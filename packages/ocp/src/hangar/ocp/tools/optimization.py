"""Design optimization tool."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

import numpy as np
import openmdao.api as om

from hangar.sdk.helpers import _suppress_output

from hangar.ocp.builders import build_mission_problem
from hangar.ocp.results import extract_mission_results
from hangar.ocp.state import sessions as _sessions
from hangar.ocp.tools._helpers import _finalize_analysis, _make_run_id
from hangar.ocp.validation import validate_mission_results, validate_optimization_results
from hangar.ocp.validators import validate_session_ready_for_analysis


async def run_optimization(
    objective: Annotated[
        str,
        "Objective to minimize: 'fuel_burn', 'mixed_objective' (fuel + MTOW/100), 'MTOW'",
    ] = "fuel_burn",
    design_variables: Annotated[
        list[dict] | None,
        "Design variables, each a dict with 'name', 'lower', 'upper', and optional 'units'. "
        "Names use OpenConcept paths, e.g.:\n"
        "  {'name': 'ac|weights|MTOW', 'lower': 4000, 'upper': 5700}\n"
        "  {'name': 'cruise.hybridization', 'lower': 0.01, 'upper': 0.5}\n"
        "  {'name': 'ac|propulsion|engine|rating', 'lower': 500, 'upper': 3000}",
    ] = None,
    constraints: Annotated[
        list[dict] | None,
        "Constraints, each a dict with 'name' and 'lower'/'upper'/'equals'. "
        "Names use OpenConcept paths, e.g.:\n"
        "  {'name': 'margins.MTOW_margin', 'lower': 0.0}\n"
        "  {'name': 'descent.propmodel.batt1.SOC_final', 'lower': 0.0}\n"
        "  {'name': 'climb.throttle', 'upper': 1.05}",
    ] = None,
    max_iterations: Annotated[int, "Maximum optimizer iterations"] = 200,
    tolerance: Annotated[float, "Optimizer convergence tolerance"] = 1e-6,
    session_id: Annotated[str, "Session identifier"] = "default",
    run_name: Annotated[str | None, "Optional label for this run"] = None,
) -> dict:
    """Run design optimization on the configured mission.

    Requires prior calls to set up aircraft, propulsion, and mission.
    Uses SciPy's SLSQP optimizer (gradient-based, supports analytic derivatives).

    Common design variables for hybrid aircraft:
    - ac|weights|MTOW, ac|geom|wing|S_ref, ac|propulsion|engine|rating
    - ac|propulsion|motor|rating, ac|propulsion|generator|rating
    - ac|weights|W_battery, ac|weights|W_fuel_max
    - cruise.hybridization, climb.hybridization, descent.hybridization

    Common constraints:
    - margins.MTOW_margin >= 0 (weight closure)
    - descent.propmodel.batt1.SOC_final >= 0 (battery not depleted)
    - climb.throttle <= 1.05 (throttle feasibility)
    - Component sizing margins: climb.propmodel.eng1.component_sizing_margin <= 1.0
    """
    session = _sessions.get(session_id)
    validate_session_ready_for_analysis(session)

    if design_variables is None or len(design_variables) == 0:
        raise ValueError(
            "At least one design variable must be specified. "
            "Example: [{'name': 'cruise.hybridization', 'lower': 0.01, 'upper': 0.5}]"
        )

    run_id = _make_run_id()
    t0 = time.perf_counter()

    # Map objective names to OpenConcept problem paths
    objective_map = {
        "fuel_burn": "descent.fuel_used_final",
        "mixed_objective": "mixed_objective",
        "MTOW": "ac|weights|MTOW",
    }

    if objective not in objective_map:
        raise ValueError(
            f"Unknown objective {objective!r}. "
            f"Valid: {', '.join(sorted(objective_map))}"
        )

    def _run():
        prob, metadata = build_mission_problem(
            aircraft_data=session.aircraft_data,
            architecture=session.propulsion_architecture,
            mission_type=session.mission_type,
            mission_params=session.mission_params,
            num_nodes=session.num_nodes,
            solver_settings=session.solver_settings,
            propulsion_overrides=session.propulsion_overrides,
        )

        nn = session.num_nodes

        # Add design variables
        for dv in design_variables:
            dv_name = dv["name"]
            dv_kwargs = {}
            if "lower" in dv:
                dv_kwargs["lower"] = dv["lower"]
            if "upper" in dv:
                dv_kwargs["upper"] = dv["upper"]
            if "units" in dv:
                dv_kwargs["units"] = dv["units"]
            prob.model.add_design_var(dv_name, **dv_kwargs)

        # Add constraints
        if constraints:
            for con in constraints:
                con_name = con["name"]
                con_kwargs = {}
                if "lower" in con:
                    con_kwargs["lower"] = con["lower"]
                if "upper" in con:
                    upper_val = con["upper"]
                    # Vectorize scalar upper bounds for array constraints
                    if isinstance(upper_val, (int, float)):
                        try:
                            val = prob.get_val(con_name)
                            if hasattr(val, "__len__") and len(val) > 1:
                                upper_val = upper_val * np.ones(len(val))
                        except KeyError:
                            pass
                    con_kwargs["upper"] = upper_val
                if "equals" in con:
                    con_kwargs["equals"] = con["equals"]
                if "units" in con:
                    con_kwargs["units"] = con["units"]
                prob.model.add_constraint(con_name, **con_kwargs)

        # Set objective
        prob.model.add_objective(objective_map[objective])

        # Configure optimizer
        prob.driver = om.ScipyOptimizeDriver()
        prob.driver.options["optimizer"] = "SLSQP"
        prob.driver.options["maxiter"] = max_iterations
        prob.driver.options["tol"] = tolerance

        # Re-setup with optimizer
        prob.setup(check=False, mode="fwd")

        # Re-set mission values
        from hangar.ocp.builders import _set_mission_values
        from hangar.ocp.config.defaults import DEFAULT_MISSION_PARAMS, PROPULSION_ARCHITECTURES
        arch_info = PROPULSION_ARCHITECTURES[session.propulsion_architecture]
        is_hybrid = arch_info["has_battery"] and arch_info["has_fuel"]
        params = {**DEFAULT_MISSION_PARAMS, **session.mission_params}
        _set_mission_values(
            prob, params, metadata["phases"],
            session.num_nodes, is_hybrid, session.mission_type,
        )

        # Run optimizer
        run_flag = prob.run_driver()

        # Extract results
        mission_results = extract_mission_results(prob, metadata)

        # Get optimized DV values
        opt_dvs = {}
        for dv in design_variables:
            try:
                val = prob.get_val(dv["name"])
                opt_dvs[dv["name"]] = float(val.flat[0]) if hasattr(val, "flat") else float(val)
            except KeyError:
                pass

        # Get objective value
        obj_val = None
        try:
            obj_raw = prob.get_val(objective_map[objective])
            obj_val = float(obj_raw.flat[0]) if hasattr(obj_raw, "flat") else float(obj_raw)
        except KeyError:
            pass

        opt_results = {
            "optimization_successful": not run_flag,
            "num_iterations": getattr(prob.driver, "iter_count", None),
            "objective": objective,
            "objective_value": obj_val,
            "optimized_values": opt_dvs,
            **mission_results,
        }

        return opt_results, metadata

    opt_results, metadata = await asyncio.to_thread(_suppress_output, _run)

    inputs = {
        "objective": objective,
        "design_variables": design_variables,
        "constraints": constraints,
        "max_iterations": max_iterations,
        "architecture": session.propulsion_architecture,
        "mission_type": session.mission_type,
    }

    findings = validate_mission_results(opt_results, inputs)
    findings.extend(validate_optimization_results(opt_results, inputs))

    return await _finalize_analysis(
        tool_name="run_optimization",
        run_id=run_id,
        session=session,
        session_id=session_id,
        analysis_type="optimization",
        inputs=inputs,
        results=opt_results,
        trajectory=None,
        findings=findings,
        t0=t0,
        cache_hit=False,
        run_name=run_name,
    )
