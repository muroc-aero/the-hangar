"""Build OpenMDAO problem instances for aero and aerostruct analyses.

Migrated from: OpenAeroStruct/oas_mcp/core/builders.py
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import numpy as np
import openmdao.api as om
from openaerostruct.geometry.geometry_group import Geometry
from openaerostruct.aerodynamics.aero_groups import AeroPoint
from openaerostruct.integration.aerostruct_groups import AerostructGeometry, AerostructPoint
from openaerostruct.utils.constants import grav_constant

from hangar.oas.connections import connect_aero_surface, connect_aerostruct_surface
from hangar.oas.validators import validate_design_variables_for_surfaces


# ---------------------------------------------------------------------------
# Internal assemblers (no setup() call)
# ---------------------------------------------------------------------------


def _assemble_aero_model(
    prob: om.Problem,
    surfaces: list[dict],
    velocity: float,
    alpha: float,
    Mach_number: float,
    reynolds_number: float,
    density: float,
    cg: list | None,
    beta: float = 0.0,
    height_agl: float = 8000.0,
    omega: list | None = None,
) -> str:
    """Add IndepVarComp, Geometry groups, AeroPoint, and connections to prob.model.
    Returns the point_name."""
    if cg is None:
        cg = [0.0, 0.0, 0.0]

    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    rotational = omega is not None

    indep = om.IndepVarComp()
    indep.add_output("v", val=velocity, units="m/s")
    indep.add_output("alpha", val=alpha, units="deg")
    indep.add_output("beta", val=beta, units="deg")
    indep.add_output("Mach_number", val=Mach_number)
    indep.add_output("re", val=reynolds_number, units="1/m")
    indep.add_output("rho", val=density, units="kg/m**3")
    indep.add_output("cg", val=np.array(cg), units="m")
    if ground_effect:
        indep.add_output("height_agl", val=height_agl, units="m")
    if rotational:
        indep.add_output("omega", val=np.array(omega) * np.pi / 180.0, units="rad/s")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    point_name = "aero"

    for surface in surfaces:
        name = surface["name"]
        geom_group = Geometry(surface=surface)
        prob.model.add_subsystem(name, geom_group)

    aero_group = AeroPoint(surfaces=surfaces, rotational=rotational)
    promotes = ["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"]
    if ground_effect:
        promotes.append("height_agl")
    if rotational:
        promotes.append("omega")
    prob.model.add_subsystem(
        point_name,
        aero_group,
        promotes_inputs=promotes,
    )

    for surface in surfaces:
        connect_aero_surface(prob.model, surface["name"], point_name)

    return point_name


def _assemble_aerostruct_model(
    prob: om.Problem,
    surfaces: list[dict],
    velocity: float,
    alpha: float,
    Mach_number: float,
    reynolds_number: float,
    density: float,
    CT: float,
    R: float,
    W0: float,
    speed_of_sound: float,
    load_factor: float,
    empty_cg: list | None,
    beta: float = 0.0,
    height_agl: float = 8000.0,
    omega: list | None = None,
) -> str:
    """Add IndepVarComp, AerostructGeometry, AerostructPoint, connections.
    Returns the point_name."""
    if empty_cg is None:
        empty_cg = [0.0, 0.0, 0.0]

    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    rotational = omega is not None

    indep = om.IndepVarComp()
    indep.add_output("v", val=velocity, units="m/s")
    indep.add_output("alpha", val=alpha, units="deg")
    indep.add_output("beta", val=beta, units="deg")
    indep.add_output("Mach_number", val=Mach_number)
    indep.add_output("re", val=reynolds_number, units="1/m")
    indep.add_output("rho", val=density, units="kg/m**3")
    indep.add_output("CT", val=CT, units="1/s")
    indep.add_output("R", val=R, units="m")
    indep.add_output("W0", val=W0, units="kg")
    indep.add_output("speed_of_sound", val=speed_of_sound, units="m/s")
    indep.add_output("load_factor", val=load_factor)
    indep.add_output("empty_cg", val=np.array(empty_cg), units="m")
    if ground_effect:
        indep.add_output("height_agl", val=height_agl, units="m")
    if rotational:
        indep.add_output("omega", val=np.array(omega) * np.pi / 180.0, units="rad/s")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    point_name = "AS_point_0"

    for surface in surfaces:
        name = surface["name"]
        as_geom = AerostructGeometry(surface=surface)
        prob.model.add_subsystem(name, as_geom)

    AS_point = AerostructPoint(surfaces=surfaces, rotational=rotational)
    promotes = [
        "v", "alpha", "beta", "Mach_number", "re", "rho",
        "CT", "R", "W0", "speed_of_sound", "empty_cg", "load_factor",
    ]
    if ground_effect:
        promotes.append("height_agl")
    if rotational:
        promotes.extend(["omega", "cg"])
    prob.model.add_subsystem(
        point_name,
        AS_point,
        promotes_inputs=promotes,
    )

    for surface in surfaces:
        connect_aerostruct_surface(
            prob.model,
            surface["name"],
            point_name,
            fem_model_type=surface.get("fem_model_type", "tube"),
        )

    return point_name


def _set_initial_values_aero(prob, velocity, alpha, Mach_number, reynolds_number, density, cg,
                              beta=0.0, height_agl=None, omega=None):
    prob.set_val("v", velocity, units="m/s")
    prob.set_val("alpha", alpha, units="deg")
    prob.set_val("beta", beta, units="deg")
    prob.set_val("Mach_number", Mach_number)
    prob.set_val("re", reynolds_number, units="1/m")
    prob.set_val("rho", density, units="kg/m**3")
    prob.set_val("cg", np.array(cg if cg else [0.0, 0.0, 0.0]), units="m")
    if height_agl is not None:
        prob.set_val("height_agl", height_agl, units="m")
    if omega is not None:
        prob.set_val("omega", np.array(omega) * np.pi / 180.0, units="rad/s")


def _set_initial_values_aerostruct(
    prob, velocity, alpha, Mach_number, reynolds_number, density,
    CT, R, W0, speed_of_sound, load_factor, empty_cg,
    beta=0.0, height_agl=None, omega=None,
):
    prob.set_val("v", velocity, units="m/s")
    prob.set_val("alpha", alpha, units="deg")
    prob.set_val("beta", beta, units="deg")
    prob.set_val("Mach_number", Mach_number)
    prob.set_val("re", reynolds_number, units="1/m")
    prob.set_val("rho", density, units="kg/m**3")
    prob.set_val("CT", CT, units="1/s")
    prob.set_val("R", R, units="m")
    prob.set_val("W0", W0, units="kg")
    prob.set_val("speed_of_sound", speed_of_sound, units="m/s")
    prob.set_val("load_factor", load_factor)
    prob.set_val("empty_cg", np.array(empty_cg if empty_cg else [0.0, 0.0, 0.0]), units="m")
    if height_agl is not None:
        prob.set_val("height_agl", height_agl, units="m")
    if omega is not None:
        prob.set_val("omega", np.array(omega) * np.pi / 180.0, units="rad/s")


# ---------------------------------------------------------------------------
# Public builders (analysis only — no optimisation)
# ---------------------------------------------------------------------------


def build_aero_problem(
    surfaces: list[dict],
    velocity: float = 248.136,
    alpha: float = 5.0,
    Mach_number: float = 0.84,
    reynolds_number: float = 1.0e6,
    density: float = 0.38,
    cg: list | None = None,
    beta: float = 0.0,
    height_agl: float = 8000.0,
    omega: list | None = None,
) -> om.Problem:
    """Build and set up an aerodynamics-only OpenMDAO problem."""
    prob = om.Problem(reports=False)
    _assemble_aero_model(
        prob, surfaces, velocity, alpha, Mach_number, reynolds_number, density, cg,
        beta=beta, height_agl=height_agl, omega=omega,
    )
    prob.setup(force_alloc_complex=False)
    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    _set_initial_values_aero(
        prob, velocity, alpha, Mach_number, reynolds_number, density, cg,
        beta=beta,
        height_agl=height_agl if ground_effect else None,
        omega=omega,
    )
    return prob


def build_aerostruct_problem(
    surfaces: list[dict],
    velocity: float = 248.136,
    alpha: float = 5.0,
    Mach_number: float = 0.84,
    reynolds_number: float = 1.0e6,
    density: float = 0.38,
    CT: float | None = None,
    R: float = 11.165e6,
    W0: float = 0.4 * 3e5,
    speed_of_sound: float = 295.4,
    load_factor: float = 1.0,
    empty_cg: list | None = None,
    beta: float = 0.0,
    height_agl: float = 8000.0,
    omega: list | None = None,
) -> om.Problem:
    """Build and set up a coupled aerostructural OpenMDAO problem."""
    if CT is None:
        CT = grav_constant * 17.0e-6
    if empty_cg is None:
        empty_cg = [0.0, 0.0, 0.0]

    prob = om.Problem(reports=False)
    _assemble_aerostruct_model(
        prob, surfaces, velocity, alpha, Mach_number, reynolds_number,
        density, CT, R, W0, speed_of_sound, load_factor, empty_cg,
        beta=beta, height_agl=height_agl, omega=omega,
    )
    prob.setup(force_alloc_complex=False)
    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    _set_initial_values_aerostruct(
        prob, velocity, alpha, Mach_number, reynolds_number, density,
        CT, R, W0, speed_of_sound, load_factor, empty_cg,
        beta=beta,
        height_agl=height_agl if ground_effect else None,
        omega=omega,
    )
    return prob


# ---------------------------------------------------------------------------
# Problem rebuild for N2 diagrams (no run_model)
# ---------------------------------------------------------------------------

# Keys in a surface dict that are numpy arrays when built in-memory but
# become plain lists after JSON round-tripping through artifact storage.
_ARRAY_KEYS = frozenset({
    "mesh", "twist_cp", "chord_cp", "t_over_c_cp",
    "thickness_cp", "spar_thickness_cp", "skin_thickness_cp",
    "data_x_upper", "data_y_upper", "data_x_lower", "data_y_lower",
    "radius_cp", "taper", "sweep",
})


def rebuild_problem_for_n2(
    surface_dicts: list[dict],
    analysis_type: str,
    parameters: dict,
) -> om.Problem:
    """Rebuild a setup-only Problem from persisted surface dicts and parameters.

    Used to generate N2 diagrams when the in-memory cache has been evicted.
    Only calls ``setup()`` — does NOT call ``run_model()``.
    """
    restored = []
    for sd in surface_dicts:
        s = dict(sd)
        for key in _ARRAY_KEYS:
            if key in s and isinstance(s[key], list):
                s[key] = np.array(s[key])
        restored.append(s)

    if analysis_type in ("aero", "drag_polar", "stability"):
        return build_aero_problem(
            surfaces=restored,
            velocity=parameters.get("velocity", 248.136),
            alpha=parameters.get("alpha", 5.0),
            Mach_number=parameters.get("Mach_number", 0.84),
            reynolds_number=parameters.get("reynolds_number", 1e6),
            density=parameters.get("density", 0.38),
            beta=parameters.get("beta", 0.0),
            height_agl=parameters.get("height_agl", 8000.0),
            omega=parameters.get("omega"),
        )
    elif analysis_type == "aerostruct":
        return build_aerostruct_problem(
            surfaces=restored,
            velocity=parameters.get("velocity", 248.136),
            alpha=parameters.get("alpha", 5.0),
            Mach_number=parameters.get("Mach_number", 0.84),
            reynolds_number=parameters.get("reynolds_number", 1e6),
            density=parameters.get("density", 0.38),
            W0=parameters.get("W0", 0.4 * 3e5),
            R=parameters.get("R", 11.165e6),
            speed_of_sound=parameters.get("speed_of_sound", 295.4),
            load_factor=parameters.get("load_factor", 1.0),
            beta=parameters.get("beta", 0.0),
            height_agl=parameters.get("height_agl", 8000.0),
            omega=parameters.get("omega"),
        )
    else:
        raise ValueError(f"Cannot rebuild problem for analysis_type={analysis_type!r}")


# ---------------------------------------------------------------------------
# DV / constraint / objective path resolution
# ---------------------------------------------------------------------------


class PathKind(enum.Enum):
    """Category of OpenMDAO variable being resolved."""
    DV = "dv"
    CONSTRAINT = "constraint"
    OBJECTIVE = "objective"


# Design variable path templates.
# Templates use ``{name}`` for the surface name.  Scalar DVs (``alpha``,
# ``alpha_maneuver``, ``fuel_mass``) have literal paths — no substitution.
_DV_PATH_MAP: dict[str, str] = {
    "twist": "{name}.twist_cp",
    "thickness": "{name}.thickness_cp",
    "chord": "{name}.chord_cp",
    "sweep": "{name}.sweep",
    "taper": "{name}.taper",
    "alpha": "alpha",
    "spar_thickness": "{name}.spar_thickness_cp",
    "skin_thickness": "{name}.skin_thickness_cp",
    "t_over_c": "{name}.geometry.t_over_c_cp",
    "alpha_maneuver": "alpha_maneuver",
    "fuel_mass": "fuel_mass",
}

# DVs whose path is a literal string (no surface_name substitution needed).
_SCALAR_DVS: frozenset[str] = frozenset(
    k for k, v in _DV_PATH_MAP.items() if "{name}" not in v
)

# Aero-only constraint path templates.
# Templates use ``{point}`` for the analysis point name and ``{name}`` for
# the surface name.
_CONSTRAINT_PATH_MAP_AERO: dict[str, str] = {
    "CL": "{point}.{name}_perf.CL",
    "CD": "{point}.{name}_perf.CD",
    "CM": "{point}.CM",
    "S_ref": "{point}.{name}.S_ref",
}

# Aerostruct constraint path templates.
# Includes structural constraints (``failure``, ``thickness_intersects``,
# ``L_equals_W``) and multipoint-only top-level constraints
# (``fuel_vol_delta``, ``fuel_diff``) that need no point/name substitution.
_CONSTRAINT_PATH_MAP_AEROSTRUCT: dict[str, str] = {
    "CL": "{point}.{name}_perf.CL",
    "CD": "{point}.{name}_perf.CD",
    "CM": "{point}.CM",
    "S_ref": "{point}.coupled.{name}.S_ref",
    "failure": "{point}.{name}_perf.failure",
    "thickness_intersects": "{point}.{name}_perf.thickness_intersects",
    "L_equals_W": "{point}.L_equals_W",
    "fuel_vol_delta": "fuel_vol_delta.fuel_vol_delta",
    "fuel_diff": "fuel_diff",
}

# Constraint templates that are top-level (no point/name substitution).
_TOPLEVEL_CONSTRAINTS: frozenset[str] = frozenset(
    k for k, v in _CONSTRAINT_PATH_MAP_AEROSTRUCT.items()
    if "{point}" not in v and "{name}" not in v
)

# Aero-only objective path templates.
# Templates use ``{point}`` for the analysis point name and ``{name}`` for
# the surface name.
_OBJECTIVE_PATH_MAP_AERO: dict[str, str] = {
    "CD": "{point}.CD",
    "CL": "{point}.CL",
}

# Aerostruct objective path templates.
_OBJECTIVE_PATH_MAP_AEROSTRUCT: dict[str, str] = {
    "fuelburn": "{point}.fuelburn",
    "structural_mass": "{name}.structural_mass",
    "CD": "{point}.{name}_perf.CD",
}


def make_om_path(
    kind: PathKind,
    name: str,
    *,
    surface_name: str = "",
    point_name: str = "",
    analysis_type: str = "aero",
) -> str:
    """Return the OpenMDAO absolute path for a named DV, constraint, or objective.

    Handles ``_cp`` suffix aliasing (e.g. ``twist_cp`` resolves to ``twist``),
    scalar DVs (no surface substitution), and top-level constraints (no point
    substitution).

    Raises ``ValueError`` for unknown names or names incompatible with the
    analysis type.
    """
    canonical = name
    if kind == PathKind.DV:
        template = _DV_PATH_MAP.get(name)
        if template is None and name.endswith("_cp"):
            canonical = name[:-3]
            template = _DV_PATH_MAP.get(canonical)
        if template is None:
            raise ValueError(
                f"Unknown design variable {name!r}. Options: {sorted(_DV_PATH_MAP)}"
            )
        if canonical in _SCALAR_DVS:
            return template
        if canonical == "chord" and analysis_type == "aerostruct":
            return f"{surface_name}.geometry.chord_cp"
        return template.format(name=surface_name, point=point_name)

    if kind == PathKind.CONSTRAINT:
        con_map = (
            _CONSTRAINT_PATH_MAP_AEROSTRUCT
            if analysis_type == "aerostruct"
            else _CONSTRAINT_PATH_MAP_AERO
        )
        template = con_map.get(name)
        if template is None:
            raise ValueError(
                f"Unknown constraint {name!r}. Options: {sorted(con_map)}"
            )
        if name in _TOPLEVEL_CONSTRAINTS:
            return template
        return template.format(name=surface_name, point=point_name)

    if kind == PathKind.OBJECTIVE:
        obj_map = (
            _OBJECTIVE_PATH_MAP_AEROSTRUCT
            if analysis_type == "aerostruct"
            else _OBJECTIVE_PATH_MAP_AERO
        )
        template = obj_map.get(name)
        if template is None:
            raise ValueError(
                f"Unknown objective {name!r}. Options: {sorted(obj_map)}"
            )
        return template.format(name=surface_name, point=point_name)

    raise ValueError(f"Unknown PathKind {kind!r}")  # pragma: no cover


def resolve_dv_paths(
    design_variables: list[dict],
    surface_name: str,
    point_name: str,
    analysis_type: str = "aero",
) -> dict[str, str]:
    """Return ``{dv_user_name: om_path}`` for each DV in the list."""
    result: dict[str, str] = {}
    for dv in design_variables:
        dv_name = dv["name"]
        path = make_om_path(
            PathKind.DV, dv_name,
            surface_name=surface_name,
            point_name=point_name,
            analysis_type=analysis_type,
        )
        result[dv_name] = path
    return result


def resolve_constraint_paths(
    constraints: list[dict | str],
    surface_name: str,
    point_name: str,
    analysis_type: str = "aero",
) -> dict[str, str]:
    """Return ``{constraint_user_name: om_path}`` for each constraint."""
    result: dict[str, str] = {}
    for con in constraints:
        con_name = con["name"] if isinstance(con, dict) else con
        path = make_om_path(
            PathKind.CONSTRAINT, con_name,
            surface_name=surface_name,
            point_name=point_name,
            analysis_type=analysis_type,
        )
        result[con_name] = path
    return result


def resolve_objective_path(
    objective: str,
    surface_name: str,
    point_name: str,
    analysis_type: str = "aero",
) -> str:
    """Return the OpenMDAO path for the given objective name."""
    return make_om_path(
        PathKind.OBJECTIVE, objective,
        surface_name=surface_name,
        point_name=point_name,
        analysis_type=analysis_type,
    )


# Backward-compatible aliases for external callers.
# Prefer make_om_path / resolve_dv_paths / resolve_objective_path.
DV_NAME_MAP = _DV_PATH_MAP
CONSTRAINT_NAME_MAP_AERO = _CONSTRAINT_PATH_MAP_AERO
CONSTRAINT_NAME_MAP_AEROSTRUCT = _CONSTRAINT_PATH_MAP_AEROSTRUCT
OBJECTIVE_MAP_AERO = _OBJECTIVE_PATH_MAP_AERO
OBJECTIVE_MAP_AEROSTRUCT = _OBJECTIVE_PATH_MAP_AEROSTRUCT
_MP_TOPLEVEL_CONSTRAINTS = _TOPLEVEL_CONSTRAINTS
_MP_SCALAR_DVS = _SCALAR_DVS


def resolve_path(template: str, name: str, point: str) -> str:
    """Deprecated — use ``make_om_path`` instead."""
    return template.format(name=name, point=point)


# ---------------------------------------------------------------------------
# Solver configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SolverConfig:
    """Non-linear and linear solver settings for coupled aerostructural problems.

    Has no effect on aero-only problems (no coupled system to solve).
    When ``None`` is passed to builder functions, they apply their own defaults:
    - Single-point aerostruct: OpenMDAO defaults (DirectSolver / Newton as applicable)
    - Multipoint aerostruct: LinearBlockGS with Aitken on each coupled group
    """
    # Nonlinear solver: "default" keeps OpenMDAO's choice, "newton" or "nlbgs"
    nonlinear_solver: str = "default"
    nonlinear_maxiter: int = 20
    nonlinear_atol: float = 1e-8

    # Linear solver: "default" keeps OpenMDAO's choice, "direct" or "lbgs"
    linear_solver: str = "default"
    linear_maxiter: int = 30
    use_aitken: bool = True

    iprint: int = 0


# Default config for multipoint problems (matches previous hardcoded behaviour).
_MULTIPOINT_DEFAULT_SOLVER_CONFIG = SolverConfig(
    linear_solver="lbgs",
    linear_maxiter=30,
    use_aitken=True,
    iprint=0,
)


def _apply_solver_config(
    prob: om.Problem,
    point_names: list[str],
    config: SolverConfig,
) -> None:
    """Apply solver configuration to coupled groups in each analysis point."""
    for pt in point_names:
        pt_group = getattr(prob.model, pt, None)
        if pt_group is None:
            continue
        coupled = getattr(pt_group, "coupled", None)
        if coupled is None:
            continue

        if config.nonlinear_solver == "newton":
            coupled.nonlinear_solver = om.NewtonSolver(
                iprint=config.iprint,
                maxiter=config.nonlinear_maxiter,
                atol=config.nonlinear_atol,
            )
        elif config.nonlinear_solver == "nlbgs":
            coupled.nonlinear_solver = om.NonlinearBlockGS(
                iprint=config.iprint,
                maxiter=config.nonlinear_maxiter,
                atol=config.nonlinear_atol,
            )
        # "default" — leave OpenMDAO's choice

        if config.linear_solver == "direct":
            coupled.linear_solver = om.DirectSolver(iprint=config.iprint)
        elif config.linear_solver == "lbgs":
            coupled.linear_solver = om.LinearBlockGS(
                iprint=config.iprint,
                maxiter=config.linear_maxiter,
                use_aitken=config.use_aitken,
            )
        # "default" — leave OpenMDAO's choice


# ---------------------------------------------------------------------------
# Shared optimisation helpers
# ---------------------------------------------------------------------------


def _add_dvs_constraints_objective(
    prob: om.Problem,
    surfaces: list[dict],
    design_variables: list[dict],
    constraints: list[dict],
    objective: str,
    objective_scaler: float,
    point_name: str,
    analysis_type: str,
) -> None:
    """Add design variables, constraints, and objective to the problem model.

    Used by both single-point and multipoint optimisation builders.
    """
    validate_design_variables_for_surfaces(design_variables, surfaces)
    primary_name = surfaces[0]["name"] if surfaces else "wing"

    # --- Design variables ---
    for dv in design_variables:
        dv_name = dv["name"]
        path = make_om_path(
            PathKind.DV, dv_name,
            surface_name=primary_name, point_name=point_name,
            analysis_type=analysis_type,
        )
        kwargs: dict = {}
        if "lower" in dv:
            kwargs["lower"] = dv["lower"]
        if "upper" in dv:
            kwargs["upper"] = dv["upper"]
        if "scaler" in dv:
            kwargs["scaler"] = dv["scaler"]
        prob.model.add_design_var(path, **kwargs)

    # --- Constraints ---
    con_map = (
        _CONSTRAINT_PATH_MAP_AEROSTRUCT
        if analysis_type == "aerostruct"
        else _CONSTRAINT_PATH_MAP_AERO
    )
    for con in constraints:
        con_name = con["name"]
        template = con_map.get(con_name)
        if template is None:
            raise ValueError(f"Unknown constraint {con_name!r}. Options: {sorted(con_map)}")
        if con_name == "thickness_intersects":
            wingbox_surfs = [s["name"] for s in surfaces if s.get("fem_model_type") == "wingbox"]
            if wingbox_surfs:
                raise ValueError(
                    f"Constraint 'thickness_intersects' is only available for tube "
                    f"fem_model_type surfaces. Surface(s) {wingbox_surfs} use 'wingbox'. "
                    f"Remove 'thickness_intersects' from constraints for wingbox optimizations."
                )
        if con_name in _TOPLEVEL_CONSTRAINTS:
            path = template
        else:
            path = template.format(name=primary_name, point=point_name)
        kwargs = {}
        if "equals" in con:
            kwargs["equals"] = con["equals"]
        if "lower" in con:
            kwargs["lower"] = con["lower"]
        if "upper" in con:
            kwargs["upper"] = con["upper"]
        prob.model.add_constraint(path, **kwargs)

    # --- Objective ---
    obj_map = (
        _OBJECTIVE_PATH_MAP_AEROSTRUCT
        if analysis_type == "aerostruct"
        else _OBJECTIVE_PATH_MAP_AERO
    )
    obj_template = obj_map.get(objective)
    if obj_template is None:
        raise ValueError(f"Unknown objective {objective!r}. Options: {sorted(obj_map)}")
    obj_path = obj_template.format(name=primary_name, point=point_name)
    obj_kwargs: dict = {"scaler": objective_scaler} if objective_scaler != 1.0 else {}
    prob.model.add_objective(obj_path, **obj_kwargs)


def _set_cp_initial_values(prob: om.Problem, surfaces: list[dict]) -> None:
    """Set surface-level control-point array initial values after setup.

    Ensures early ``prob.get_val()`` calls return the surface-dict values
    rather than OpenMDAO's default (1.0).
    """
    cp_keys = ("twist_cp", "thickness_cp", "t_over_c_cp",
               "spar_thickness_cp", "skin_thickness_cp")
    for surface in surfaces:
        sname = surface["name"]
        for key in cp_keys:
            if key in surface:
                try:
                    prob.set_val(f"{sname}.{key}", surface[key])
                except Exception:
                    pass


def _extract_aero_fc(fc: dict) -> dict:
    """Unpack a flight_conditions dict into kwargs for aero assembler/init."""
    return {
        "velocity": fc.get("velocity", 248.136),
        "alpha": fc.get("alpha", 5.0),
        "Mach_number": fc.get("Mach_number", 0.84),
        "reynolds_number": fc.get("reynolds_number", 1.0e6),
        "density": fc.get("density", 0.38),
        "cg": fc.get("cg"),
        "beta": fc.get("beta", 0.0),
        "height_agl": fc.get("height_agl", 8000.0),
        "omega": fc.get("omega"),
    }


def _extract_aerostruct_fc(fc: dict) -> dict:
    """Unpack a flight_conditions dict into kwargs for aerostruct assembler/init."""
    return {
        "velocity": fc.get("velocity", 248.136),
        "alpha": fc.get("alpha", 5.0),
        "Mach_number": fc.get("Mach_number", 0.84),
        "reynolds_number": fc.get("reynolds_number", 1.0e6),
        "density": fc.get("density", 0.38),
        "CT": fc.get("CT", grav_constant * 17.0e-6),
        "R": fc.get("R", 11.165e6),
        "W0": fc.get("W0", 0.4 * 3e5),
        "speed_of_sound": fc.get("speed_of_sound", 295.4),
        "load_factor": fc.get("load_factor", 1.0),
        "empty_cg": fc.get("empty_cg"),
        "beta": fc.get("beta", 0.0),
        "height_agl": fc.get("height_agl", 8000.0),
        "omega": fc.get("omega"),
    }


# ---------------------------------------------------------------------------
# Optimisation problem builders
# ---------------------------------------------------------------------------


def build_aero_optimization_problem(
    surfaces: list[dict],
    objective: str,
    design_variables: list[dict],
    constraints: list[dict],
    flight_conditions: dict,
    objective_scaler: float = 1.0,
    tolerance: float = 1e-6,
    max_iterations: int = 200,
) -> tuple[om.Problem, str]:
    """Build and set up an aero-only optimisation problem.

    Returns ``(prob, point_name)``.  The caller should call ``prob.run_driver()``.
    """
    prob = om.Problem(reports=False)
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["tol"] = tolerance
    prob.driver.options["maxiter"] = max_iterations

    fc = _extract_aero_fc(flight_conditions)
    point_name = _assemble_aero_model(prob, surfaces, **fc)

    _add_dvs_constraints_objective(
        prob, surfaces, design_variables, constraints,
        objective, objective_scaler, point_name, "aero",
    )

    prob.setup(force_alloc_complex=False)
    _set_cp_initial_values(prob, surfaces)

    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    _set_initial_values_aero(
        prob, **{**fc, "height_agl": fc["height_agl"] if ground_effect else None},
    )
    return prob, point_name


def build_aerostruct_optimization_problem(
    surfaces: list[dict],
    objective: str,
    design_variables: list[dict],
    constraints: list[dict],
    flight_conditions: dict,
    objective_scaler: float = 1.0,
    tolerance: float = 1e-6,
    max_iterations: int = 200,
    solver_config: SolverConfig | None = None,
) -> tuple[om.Problem, str]:
    """Build and set up a single-point aerostructural optimisation problem.

    Returns ``(prob, point_name)``.  The caller should call ``prob.run_driver()``.

    Parameters
    ----------
    solver_config : SolverConfig or None
        Solver settings for the coupled group.  ``None`` keeps OpenMDAO defaults.
    """
    prob = om.Problem(reports=False)
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["tol"] = tolerance
    prob.driver.options["maxiter"] = max_iterations

    fc = _extract_aerostruct_fc(flight_conditions)
    point_name = _assemble_aerostruct_model(prob, surfaces, **fc)

    _add_dvs_constraints_objective(
        prob, surfaces, design_variables, constraints,
        objective, objective_scaler, point_name, "aerostruct",
    )

    prob.setup(force_alloc_complex=False)
    _set_cp_initial_values(prob, surfaces)

    if solver_config is not None:
        _apply_solver_config(prob, [point_name], solver_config)

    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    _set_initial_values_aerostruct(
        prob, **{**fc, "height_agl": fc["height_agl"] if ground_effect else None},
    )
    return prob, point_name


def build_optimization_problem(
    surfaces: list[dict],
    analysis_type: str,
    objective: str,
    design_variables: list[dict],
    constraints: list[dict],
    flight_conditions: dict,
    objective_scaler: float = 1.0,
    tolerance: float = 1e-6,
    max_iterations: int = 200,
) -> tuple[om.Problem, str]:
    """Build and set up an optimisation problem (dispatcher).

    Delegates to ``build_aero_optimization_problem`` or
    ``build_aerostruct_optimization_problem`` based on *analysis_type*.

    Returns ``(prob, point_name)``.
    """
    if analysis_type == "aero":
        return build_aero_optimization_problem(
            surfaces, objective, design_variables, constraints,
            flight_conditions,
            objective_scaler=objective_scaler,
            tolerance=tolerance,
            max_iterations=max_iterations,
        )
    return build_aerostruct_optimization_problem(
        surfaces, objective, design_variables, constraints,
        flight_conditions,
        objective_scaler=objective_scaler,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )


# ---------------------------------------------------------------------------
# Multipoint aerostructural assembler and optimisation problem builder
# ---------------------------------------------------------------------------


def _assemble_multipoint_aerostruct_model(
    prob: om.Problem,
    surfaces: list[dict],
    flight_points: list[dict],
    CT: float,
    R: float,
    W0_without_point_masses: float,
    alpha: float = 0.0,
    alpha_maneuver: float = 0.0,
    empty_cg: list | None = None,
    fuel_mass: float = 10000.0,
    point_masses: list | None = None,
    point_mass_locations: list | None = None,
) -> list[str]:
    """Assemble a multipoint aerostructural model following the OAS tutorial.

    Returns list of point names ["AS_point_0", "AS_point_1", ...].
    """
    from openaerostruct.structures.wingbox_fuel_vol_delta import WingboxFuelVolDelta

    if empty_cg is None:
        empty_cg = [0.0, 0.0, 0.0]

    N = len(flight_points)
    v_arr = np.array([fp["velocity"] for fp in flight_points])
    mach_arr = np.array([fp["Mach_number"] for fp in flight_points])
    re_arr = np.array([fp["reynolds_number"] for fp in flight_points])
    rho_arr = np.array([fp["density"] for fp in flight_points])
    sos_arr = np.array([fp["speed_of_sound"] for fp in flight_points])
    lf_arr = np.array([fp.get("load_factor", 1.0) for fp in flight_points])

    has_point_masses = point_masses is not None and len(point_masses) > 0
    pm_arr = np.array(point_masses) if has_point_masses else np.zeros((1, 1))
    pml_arr = np.array(point_mass_locations) if has_point_masses else np.zeros((1, 3))

    indep = om.IndepVarComp()
    indep.add_output("v", val=v_arr, units="m/s")
    indep.add_output("Mach_number", val=mach_arr)
    indep.add_output("re", val=re_arr, units="1/m")
    indep.add_output("rho", val=rho_arr, units="kg/m**3")
    indep.add_output("speed_of_sound", val=sos_arr, units="m/s")
    indep.add_output("load_factor", val=lf_arr)
    indep.add_output("CT", val=CT, units="1/s")
    indep.add_output("R", val=R, units="m")
    indep.add_output("W0_without_point_masses", val=W0_without_point_masses, units="kg")
    indep.add_output("alpha", val=alpha, units="deg")
    indep.add_output("alpha_maneuver", val=alpha_maneuver, units="deg")
    indep.add_output("empty_cg", val=np.array(empty_cg), units="m")
    indep.add_output("fuel_mass", val=fuel_mass, units="kg")
    indep.add_output("point_masses", val=pm_arr, units="kg")
    indep.add_output("point_mass_locations", val=pml_arr, units="m")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    prob.model.add_subsystem(
        "W0_comp",
        om.ExecComp("W0 = W0_without_point_masses + 2 * sum(point_masses)", units="kg"),
        promotes=["*"],
    )

    for surface in surfaces:
        prob.model.add_subsystem(surface["name"], AerostructGeometry(surface=surface))

    point_names = []
    for i in range(N):
        pt = f"AS_point_{i}"
        point_names.append(pt)

        AS_point = AerostructPoint(surfaces=surfaces, internally_connect_fuelburn=False)
        prob.model.add_subsystem(pt, AS_point)

        prob.model.connect("v", pt + ".v", src_indices=[i])
        prob.model.connect("Mach_number", pt + ".Mach_number", src_indices=[i])
        prob.model.connect("re", pt + ".re", src_indices=[i])
        prob.model.connect("rho", pt + ".rho", src_indices=[i])
        prob.model.connect("speed_of_sound", pt + ".speed_of_sound", src_indices=[i])
        prob.model.connect("load_factor", pt + ".load_factor", src_indices=[i])
        prob.model.connect("CT", pt + ".CT")
        prob.model.connect("R", pt + ".R")
        prob.model.connect("W0", pt + ".W0")
        prob.model.connect("empty_cg", pt + ".empty_cg")
        prob.model.connect("fuel_mass", pt + ".total_perf.L_equals_W.fuelburn")
        prob.model.connect("fuel_mass", pt + ".total_perf.CG.fuelburn")

        for surface in surfaces:
            name = surface["name"]
            fem_type = surface.get("fem_model_type", "tube")
            struct_weight_relief = surface.get("struct_weight_relief", False)
            distributed_fuel_weight = surface.get("distributed_fuel_weight", False)

            if distributed_fuel_weight:
                prob.model.connect("load_factor", pt + ".coupled.load_factor", src_indices=[i])

            connect_aerostruct_surface(prob.model, name, pt, fem_model_type=fem_type)

            if struct_weight_relief:
                prob.model.connect(name + ".element_mass", pt + ".coupled." + name + ".element_mass")

            if has_point_masses:
                coupled_name = pt + ".coupled." + name
                prob.model.connect("point_masses", coupled_name + ".point_masses")
                prob.model.connect("point_mass_locations", coupled_name + ".point_mass_locations")

            if distributed_fuel_weight:
                prob.model.connect(
                    name + ".struct_setup.fuel_vols",
                    pt + ".coupled." + name + ".struct_states.fuel_vols",
                )
                prob.model.connect("fuel_mass", pt + ".coupled." + name + ".struct_states.fuel_mass")

    prob.model.connect("alpha", "AS_point_0.alpha")
    if N > 1:
        prob.model.connect("alpha_maneuver", "AS_point_1.alpha")

    # Fuel volume constraint and diff components (wingbox only)
    wingbox_surfaces = [s for s in surfaces if s.get("fem_model_type") == "wingbox"]
    if wingbox_surfaces:
        wb_surf = wingbox_surfaces[0]
        wb_name = wb_surf["name"]
        prob.model.add_subsystem("fuel_vol_delta", WingboxFuelVolDelta(surface=wb_surf))
        prob.model.connect(wb_name + ".struct_setup.fuel_vols", "fuel_vol_delta.fuel_vols")
        prob.model.connect("AS_point_0.fuelburn", "fuel_vol_delta.fuelburn")

        comp = om.ExecComp("fuel_diff = (fuel_mass - fuelburn) / fuelburn", units="kg")
        prob.model.add_subsystem("fuel_diff", comp, promotes_inputs=["fuel_mass"], promotes_outputs=["fuel_diff"])
        prob.model.connect("AS_point_0.fuelburn", "fuel_diff.fuelburn")

    return point_names


def _add_multipoint_dvs_constraints_objective(
    prob: om.Problem,
    surfaces: list[dict],
    design_variables: list[dict],
    constraints: list[dict],
    objective: str,
    point_names: list[str],
) -> None:
    """Add DVs, constraints, and objective for multipoint optimisation.

    Handles scalar DVs (no surface substitution) and per-point constraint
    targeting via the optional ``"point"`` key in constraint dicts.
    """
    validate_design_variables_for_surfaces(design_variables, surfaces)
    primary_name = surfaces[0]["name"] if surfaces else "wing"

    # --- Design variables ---
    for dv in design_variables:
        dv_name = dv.get("name", "")
        path = make_om_path(
            PathKind.DV, dv_name,
            surface_name=primary_name, point_name=point_names[0],
            analysis_type="aerostruct",
        )
        kwargs: dict = {}
        if "lower" in dv:
            kwargs["lower"] = dv["lower"]
        if "upper" in dv:
            kwargs["upper"] = dv["upper"]
        if "scaler" in dv:
            kwargs["scaler"] = dv["scaler"]
        prob.model.add_design_var(path, **kwargs)

    # --- Constraints ---
    for con in constraints:
        con_name = con.get("name", "")
        if con_name in _TOPLEVEL_CONSTRAINTS:
            path = make_om_path(
                PathKind.CONSTRAINT, con_name,
                analysis_type="aerostruct",
            )
        else:
            pt_idx = con.get("point", 0)
            pt_name = point_names[pt_idx] if pt_idx < len(point_names) else point_names[0]
            path = make_om_path(
                PathKind.CONSTRAINT, con_name,
                surface_name=primary_name, point_name=pt_name,
                analysis_type="aerostruct",
            )
        kwargs = {}
        if "equals" in con:
            kwargs["equals"] = con["equals"]
        if "lower" in con:
            kwargs["lower"] = con["lower"]
        if "upper" in con:
            kwargs["upper"] = con["upper"]
        prob.model.add_constraint(path, **kwargs)

    # --- Objective ---
    obj_path = make_om_path(
        PathKind.OBJECTIVE, objective,
        surface_name=primary_name, point_name=point_names[0],
        analysis_type="aerostruct",
    )
    prob.model.add_objective(obj_path)


def build_multipoint_optimization_problem(
    surfaces: list[dict],
    objective: str,
    design_variables: list[dict],
    constraints: list[dict],
    flight_points: list[dict],
    CT: float,
    R: float,
    W0_without_point_masses: float,
    alpha: float = 0.0,
    alpha_maneuver: float = 0.0,
    empty_cg: list | None = None,
    fuel_mass: float = 10000.0,
    point_masses: list | None = None,
    point_mass_locations: list | None = None,
    tolerance: float = 1e-2,
    max_iterations: int = 200,
    optimizer: str = "SLSQP",
    solver_config: SolverConfig | None = None,
) -> tuple[om.Problem, list[str]]:
    """Build and set up a multipoint aerostructural optimisation problem.

    Returns ``(prob, point_names)``.  The caller should call ``prob.run_driver()``.

    Parameters
    ----------
    optimizer : str
        SciPy optimizer name (default ``"SLSQP"``).
    solver_config : SolverConfig or None
        Solver settings for the coupled groups.  ``None`` applies the multipoint
        default (Aitken-accelerated LinearBlockGS).
    """
    prob = om.Problem(reports=False)
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = optimizer
    prob.driver.options["tol"] = tolerance
    prob.driver.options["maxiter"] = max_iterations

    point_names = _assemble_multipoint_aerostruct_model(
        prob, surfaces, flight_points, CT, R, W0_without_point_masses,
        alpha, alpha_maneuver, empty_cg, fuel_mass, point_masses, point_mass_locations,
    )

    _add_multipoint_dvs_constraints_objective(
        prob, surfaces, design_variables, constraints, objective, point_names,
    )

    prob.setup(force_alloc_complex=False)

    # Apply solver configuration (default: Aitken-accelerated LBGS)
    effective_config = solver_config if solver_config is not None else _MULTIPOINT_DEFAULT_SOLVER_CONFIG
    _apply_solver_config(prob, point_names, effective_config)

    return prob, point_names
