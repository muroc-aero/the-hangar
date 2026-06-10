"""Tool: run_optimization — design optimization with SLSQP.

Migrated from: OpenAeroStruct/oas_mcp/tools/optimization.py
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

import numpy as np

from hangar.sdk.artifacts.store import _make_run_id
from hangar.sdk.state import sessions as _sessions

from hangar.oas.builders import (
    build_multipoint_optimization_problem,
    build_optimization_problem,
)
from hangar.oas.results import (
    extract_aero_results,
    extract_aerostruct_results,
    extract_multipoint_results,
    extract_standard_detail,
)
from hangar.oas.validation import validate_optimization
from hangar.oas.validators import (
    validate_flight_points,
    validate_struct_props_present,
    validate_surface_names_exist,
)
from hangar.oas.tools._helpers import (
    _finalize_analysis,
    _from_oas_order,
    _is_cp_dv,
)
from hangar.sdk.helpers import _suppress_output


def _multi_surface_scope_finding(
    surfaces: list[str],
    design_variables: list,
    constraints: list[dict],
):
    """Warn when a multi-surface optimization silently targets surfaces[0] only.

    Surface-scoped DVs (twist, chord, thickness, ...) and constraints whose
    OpenMDAO path embeds a surface name are resolved against the first surface
    in the list; the remaining surfaces are analysed but never optimised.
    Returns a ValidationFinding, or None when nothing is surface-scoped.
    """
    if len(surfaces) <= 1:
        return None

    from hangar.oas.builders import _CONSTRAINT_PATH_MAP_AEROSTRUCT, _SCALAR_DVS
    from hangar.sdk.validation.checks import ValidationFinding

    def _dv_name(dv) -> str:
        name = dv["name"] if isinstance(dv, dict) else dv
        return name[:-3] if name.endswith("_cp") else name

    surface_scoped = sorted(
        {n for n in (_dv_name(dv) for dv in design_variables) if n not in _SCALAR_DVS}
        | {
            c["name"] for c in constraints
            if "{name}" in _CONSTRAINT_PATH_MAP_AEROSTRUCT.get(c["name"], "")
        }
    )
    if not surface_scoped:
        return None

    return ValidationFinding(
        check_id="setup.multi_surface_dv_scope",
        category="constraints",
        severity="warning",
        confidence="high",
        passed=False,
        message=(
            f"Surface-scoped design variables/constraints {surface_scoped} "
            f"were applied to {surfaces[0]!r} only; the other surface(s) "
            f"{surfaces[1:]} were analysed but not optimised."
        ),
        remediation=(
            "Per-surface DV targeting is not supported. Optimise one "
            "surface at a time, or treat the extra surfaces as fixed "
            "geometry."
        ),
    )


async def run_optimization(
    surfaces: Annotated[list[str], "Names of surfaces to use"],
    analysis_type: Annotated[str, "Analysis type: 'aero' or 'aerostruct'"] = "aero",
    objective: Annotated[str, "Objective to minimise: 'CD', 'fuelburn', or 'structural_mass'"] = "CD",
    design_variables: Annotated[
        list[dict],
        "List of DV dicts, e.g. [{'name':'twist','lower':-10,'upper':10}, {'name':'alpha','lower':-5,'upper':10}]"
    ] = None,
    constraints: Annotated[
        list[dict],
        "List of constraint dicts, e.g. [{'name':'CL','equals':0.5,'point':0}, {'name':'failure','upper':0.0,'point':1}]"
    ] = None,
    velocity: Annotated[float, "Free-stream velocity in m/s (single-point only)"] = 248.136,
    alpha: Annotated[float, "Initial angle of attack in degrees"] = 5.0,
    Mach_number: Annotated[float, "Mach number (single-point only)"] = 0.84,
    reynolds_number: Annotated[float, "Reynolds number per unit length (1/m, single-point only)"] = 1.0e6,
    density: Annotated[float, "Air density in kg/m^3 (single-point only)"] = 0.38,
    W0: Annotated[float, "Aircraft empty weight in kg (single-point aerostruct only)"] = 0.4 * 3e5,
    speed_of_sound: Annotated[float, "Speed of sound in m/s (single-point aerostruct only)"] = 295.4,
    load_factor: Annotated[float, "Load factor (single-point aerostruct only)"] = 1.0,
    CT: Annotated[float | None, "Thrust specific fuel consumption in 1/s (None = OAS default ~1.67e-4)"] = None,
    R: Annotated[float, "Range in metres"] = 14.307e6,
    flight_points: Annotated[
        list[dict] | None,
        "Multipoint flight conditions. Each dict requires: velocity, Mach_number, density, "
        "reynolds_number, speed_of_sound, load_factor. Enables multipoint aerostruct optimization."
    ] = None,
    W0_without_point_masses: Annotated[float, "Empty weight + reserve fuel in kg (multipoint only)"] = 143000.0,
    point_masses: Annotated[list[list[float]] | None, "Point masses in kg, e.g. [[10000]] for one engine"] = None,
    point_mass_locations: Annotated[list[list[float]] | None, "Point mass [x,y,z] locations in m, e.g. [[25,-10,0]]"] = None,
    objective_scaler: Annotated[float, "Scaler applied to the objective in add_objective (e.g. 1e4 for CD, 1e-5 for fuelburn)"] = 1.0,
    tolerance: Annotated[float, "Optimiser convergence tolerance"] = 1e-6,
    max_iterations: Annotated[int, "Maximum optimiser iterations"] = 200,
    capture_solver_iters: Annotated[bool, "Capture nonlinear solver sub-iteration residuals (aerostruct only)"] = False,
    session_id: Annotated[str, "Session identifier"] = "default",
    run_name: Annotated[str | None, "Optional label for this run (stored in artifact metadata)"] = None,
) -> dict:
    """Run a design optimisation.

    Minimises the objective function subject to the given constraints by
    varying the specified design variables.  Supports aero-only (VLM),
    single-point aerostructural, and multipoint aerostructural problems.

    Design variable names (all models):     'twist', 'chord', 'sweep', 'taper', 'alpha', 't_over_c'
    Design variable names (tube only):      'thickness'
    Design variable names (wingbox only):   'spar_thickness', 'skin_thickness'
    Design variable names (multipoint):     'alpha_maneuver', 'fuel_mass'
    Constraint names (aero):                'CL', 'CD', 'CM', 'S_ref'
    Constraint names (aerostruct):          all aero + 'failure', 'thickness_intersects', 'L_equals_W'
    Constraint names (multipoint):          all aerostruct + 'fuel_vol_delta', 'fuel_diff'
    Objective names (aero):                 'CD', 'CL'
    Objective names (aerostruct):           'fuelburn', 'structural_mass', 'CD'

    For multipoint optimization, pass flight_points as a list of dicts with keys:
    velocity, Mach_number, density, reynolds_number, speed_of_sound, load_factor.
    Point 0 = cruise, point 1 = maneuver.  Constraint dicts accept an optional
    'point' key (int index, default 0) to target a specific flight point.
    """
    if design_variables is None:
        design_variables = [{"name": "alpha", "lower": -10.0, "upper": 15.0}]
    if constraints is None:
        constraints = [{"name": "CL", "equals": 0.5}]

    session = _sessions.get(session_id)
    validate_surface_names_exist(surfaces, session)
    surface_dicts = session.get_surfaces(surfaces)

    if analysis_type not in ("aero", "aerostruct"):
        raise ValueError("analysis_type must be 'aero' or 'aerostruct'")

    if analysis_type == "aerostruct":
        for s in surface_dicts:
            validate_struct_props_present(s)

    if flight_points is not None:
        validate_flight_points(flight_points)

    from openaerostruct.utils.constants import grav_constant
    ct_default = grav_constant * 17.0e-6
    ct_val = CT if CT is not None else ct_default

    def _run():
        from hangar.oas.builders import resolve_constraint_paths, resolve_dv_paths, resolve_objective_path
        from hangar.oas.convergence import OptimizationTracker, summarize_convergence_history

        primary_name = surface_dicts[0]["name"] if surface_dicts else "wing"

        if flight_points is not None and analysis_type == "aerostruct":
            # ----------------------------------------------------------------
            # MULTIPOINT path
            # ----------------------------------------------------------------
            prob, point_names = build_multipoint_optimization_problem(
                surface_dicts,
                objective=objective,
                design_variables=design_variables,
                constraints=constraints,
                flight_points=flight_points,
                CT=ct_val,
                R=R,
                W0_without_point_masses=W0_without_point_masses,
                alpha=alpha,
                point_masses=point_masses,
                point_mass_locations=point_mass_locations,
                tolerance=tolerance,
                max_iterations=max_iterations,
            )

            dv_path_map = resolve_dv_paths(
                design_variables, primary_name, point_names[0], "aerostruct",
            )
            con_path_map = resolve_constraint_paths(
                constraints, primary_name, point_names[0], "aerostruct",
            )

            tracker = OptimizationTracker()
            initial_dvs = tracker.record_initial(prob, dv_path_map)
            tracker.attach(prob)
            if capture_solver_iters:
                tracker.attach_solver(prob, f"{point_names[0]}.coupled")

            obj_path = resolve_objective_path(objective, primary_name, point_names[0], "aerostruct")

            prob.run_driver()
            success = prob.driver.result.success if hasattr(prob.driver, "result") else True
            opt_history = tracker.extract(dv_path_map, obj_path, constraint_path_map=con_path_map)

            # Final gradient norm (if available)
            try:
                dr = prob.driver.result
                if hasattr(dr, "optimality"):
                    opt_history["final_gradient_norm"] = float(dr.optimality)
            except Exception:
                pass

            # Per-point roles
            if len(point_names) == 2:
                roles = ["cruise", "maneuver"]
            else:
                roles = ["cruise"] + [f"maneuver_{i}" for i in range(1, len(point_names))]
            final_results = extract_multipoint_results(prob, surface_dicts, point_names, roles)

            # Standard detail from cruise point for visualization
            standard = extract_standard_detail(prob, surface_dicts, "aerostruct", point_names[0])

        else:
            # ----------------------------------------------------------------
            # SINGLE-POINT path
            # ----------------------------------------------------------------
            if analysis_type == "aero":
                flight_conditions = {
                    "velocity": velocity,
                    "alpha": alpha,
                    "Mach_number": Mach_number,
                    "reynolds_number": reynolds_number,
                    "density": density,
                }
            else:
                flight_conditions = {
                    "velocity": velocity,
                    "alpha": alpha,
                    "Mach_number": Mach_number,
                    "reynolds_number": reynolds_number,
                    "density": density,
                    "CT": ct_val,
                    "R": R,
                    "W0": W0,
                    "speed_of_sound": speed_of_sound,
                    "load_factor": load_factor,
                }

            prob, point_name = build_optimization_problem(
                surface_dicts,
                analysis_type=analysis_type,
                objective=objective,
                design_variables=design_variables,
                constraints=constraints,
                flight_conditions=flight_conditions,
                objective_scaler=objective_scaler,
                tolerance=tolerance,
                max_iterations=max_iterations,
            )

            dv_path_map = resolve_dv_paths(
                design_variables, primary_name, point_name, analysis_type,
            )
            con_path_map = resolve_constraint_paths(
                constraints, primary_name, point_name, analysis_type,
            )

            tracker = OptimizationTracker()
            initial_dvs = tracker.record_initial(prob, dv_path_map)
            tracker.attach(prob)
            if capture_solver_iters and analysis_type == "aerostruct":
                tracker.attach_solver(prob, f"{point_name}.coupled")

            obj_path = resolve_objective_path(objective, primary_name, point_name, analysis_type)

            prob.run_driver()
            success = prob.driver.result.success if hasattr(prob.driver, "result") else True
            opt_history = tracker.extract(dv_path_map, obj_path, constraint_path_map=con_path_map)

            # Final gradient norm (if available)
            try:
                dr = prob.driver.result
                if hasattr(dr, "optimality"):
                    opt_history["final_gradient_norm"] = float(dr.optimality)
            except Exception:
                pass

            if analysis_type == "aero":
                final_results = extract_aero_results(prob, surface_dicts, point_name)
            else:
                final_results = extract_aerostruct_results(prob, surface_dicts, point_name)

            standard = extract_standard_detail(prob, surface_dicts, analysis_type, point_name)

        # Extract optimised DV values
        dv_results: dict = {}
        for dv_name, path in dv_path_map.items():
            try:
                val = prob.get_val(path)
                dv_results[dv_name] = np.asarray(val).tolist()
            except Exception:
                pass

        # Convert cp arrays from OAS order (tip->root) to MCP order (root->tip)
        for dv_name in list(dv_results):
            if _is_cp_dv(dv_name):
                dv_results[dv_name] = _from_oas_order(np.array(dv_results[dv_name])).tolist()
        for dv_name in list(initial_dvs):
            if _is_cp_dv(dv_name):
                initial_dvs[dv_name] = _from_oas_order(np.array(initial_dvs[dv_name])).tolist()
        for dv_name, iters in opt_history.get("dv_history", {}).items():
            if _is_cp_dv(dv_name):
                opt_history["dv_history"][dv_name] = [
                    _from_oas_order(np.array(v)).tolist() for v in iters
                ]

        full_history = {"initial_dvs": initial_dvs, **opt_history}
        summary_history = summarize_convergence_history(full_history)

        result = {
            "success": bool(success),
            "optimized_design_variables": dv_results,
            "final_results": final_results,
            "optimization_history": summary_history,
        }
        return result, standard, full_history

    run_id = _make_run_id()
    t0 = time.perf_counter()
    result, standard_detail, full_convergence = await asyncio.to_thread(_suppress_output, _run)

    session.store_mesh_snapshot(run_id, standard_detail.get("mesh_snapshot", {}))
    session.store_convergence(run_id, full_convergence)

    inputs: dict = {
        "analysis_type": analysis_type, "objective": objective,
        "alpha": alpha,
    }
    if flight_points is not None:
        inputs["multipoint"] = True
        inputs["n_flight_points"] = len(flight_points)
        inputs["CT"] = ct_val
        inputs["R"] = R
    else:
        inputs["velocity"] = velocity
        inputs["Mach_number"] = Mach_number
        inputs["density"] = density

    findings = validate_optimization(result, context={
        "analysis_type": analysis_type,
        "max_iterations": max_iterations,
        "objective_scaler": objective_scaler,
        "design_variables": [dv if isinstance(dv, dict) else {"name": dv} for dv in design_variables],
    })
    scope_finding = _multi_surface_scope_finding(surfaces, design_variables, constraints)
    if scope_finding is not None:
        findings.append(scope_finding)
    return await _finalize_analysis(
        tool_name="run_optimization", run_id=run_id,
        session=session, session_id=session_id, surfaces=surfaces,
        analysis_type="optimization", inputs=inputs, results=result,
        standard_detail=standard_detail, findings=findings,
        t0=t0, cache_hit=False, run_name=run_name,
        surface_dicts=surface_dicts, auto_plots=False,
    )
