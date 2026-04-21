"""OpenAeroStruct component factory.

Builds OAS aerostructural models from plan YAML configs using
upstream openaerostruct and openmdao APIs directly. No dependency
on hangar-oas.
"""

from __future__ import annotations

from hangar.omd.factory_metadata import FactoryMetadata

import logging
from typing import Any

import numpy as np
import openmdao.api as om
from openaerostruct.meshing.mesh_generator import generate_mesh
from openaerostruct.integration.aerostruct_groups import (
    AerostructGeometry,
    AerostructPoint,
)


# ---------------------------------------------------------------------------
# Default surface properties (matches OAS conventions)
# ---------------------------------------------------------------------------

_DEFAULT_AERO_SURFACE: dict[str, Any] = {
    "S_ref_type": "wetted",
    "CL0": 0.0,
    "CD0": 0.015,
    "k_lam": 0.05,
    "t_over_c_cp": [0.15],
    "c_max_t": 0.303,
    "with_viscous": True,
    "with_wave": False,
}

_DEFAULT_STRUCT_PROPS: dict[str, Any] = {
    "safety_factor": 1.5,
    "fem_origin": 0.35,
    "wing_weight_ratio": 2.0,
    "struct_weight_relief": False,
    "distributed_fuel_weight": False,
    "exact_failure_constraint": False,
}

_DEFAULT_FLIGHT_CONDITIONS: dict[str, Any] = {
    "velocity": 248.136,
    "alpha": 5.0,
    "Mach_number": 0.84,
    "re": 1.0e6,
    "rho": 0.38,
    "CT": 9.81e-6,
    "R": 14.3e6,
    "W0": 25000.0,
    "speed_of_sound": 295.07,
    "load_factor": 1.0,
    "empty_cg": [0.35, 0.0, 0.0],
}


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------


def _generate_mesh(
    config: dict,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Generate a mesh from surface config using upstream OAS.

    Args:
        config: Surface config dict with wing_type, num_x, num_y,
            span, root_chord, symmetry, and optional sweep/dihedral/taper.

    Returns:
        Tuple of (mesh, twist_cp_or_None).

    Note: When symmetry is True, OAS's generate_mesh halves both span
    and num_y internally. So span=28 with symmetry gives a 14m half-span
    mesh, and num_y=21 gives 11 half-span nodes.
    """
    mesh_dict = {
        "num_x": config.get("num_x", 2),
        "num_y": config["num_y"],
        "wing_type": config.get("wing_type", "rect"),
        "symmetry": config.get("symmetry", True),
        "span": config.get("span", 10.0),
        "root_chord": config.get("root_chord", 1.0),
        "span_cos_spacing": config.get("span_cos_spacing", 0.0),
        "chord_cos_spacing": config.get("chord_cos_spacing", 0.0),
    }
    offset = config.get("offset")
    if offset is not None:
        mesh_dict["offset"] = np.asarray(offset, dtype=float)

    if "CRM" in mesh_dict["wing_type"]:
        num_twist = config.get(
            "num_twist_cp",
            max(2, min(5, (mesh_dict["num_y"] + 1) // 2)),
        )
        mesh_dict["num_twist_cp"] = num_twist
        mesh, twist_cp = generate_mesh(mesh_dict)
        return mesh, twist_cp
    else:
        result = generate_mesh(mesh_dict)
        if isinstance(result, tuple):
            result = result[0]
        return result, None

    return mesh, None


def _apply_sweep(mesh: np.ndarray, sweep_deg: float) -> np.ndarray:
    """Shear mesh in x direction to apply leading-edge sweep."""
    if sweep_deg == 0.0:
        return mesh
    mesh = mesh.copy()
    sweep_rad = np.deg2rad(sweep_deg)
    y_coords = mesh[0, :, 1]
    x_shift = np.abs(y_coords) * np.tan(sweep_rad)
    for ix in range(mesh.shape[0]):
        mesh[ix, :, 0] += x_shift
    return mesh


def _apply_dihedral(mesh: np.ndarray, dihedral_deg: float) -> np.ndarray:
    """Shift mesh z coords to apply dihedral."""
    if dihedral_deg == 0.0:
        return mesh
    mesh = mesh.copy()
    dih_rad = np.deg2rad(dihedral_deg)
    y_coords = mesh[0, :, 1]
    z_shift = np.abs(y_coords) * np.tan(dih_rad)
    for ix in range(mesh.shape[0]):
        mesh[ix, :, 2] += z_shift
    return mesh


def _apply_taper(mesh: np.ndarray, taper: float) -> np.ndarray:
    """Scale chord linearly from root (1.0) to tip (taper)."""
    if taper == 1.0:
        return mesh
    mesh = mesh.copy()
    y_abs = np.abs(mesh[0, :, 1])
    y_max = y_abs.max()
    if y_max == 0.0:
        return mesh
    scale = 1.0 - (1.0 - taper) * y_abs / y_max
    le_x = mesh[0, :, 0]
    te_x = mesh[-1, :, 0]
    mid_x = 0.5 * (le_x + te_x)
    chord = te_x - le_x
    for ix in range(mesh.shape[0]):
        frac = ix / (mesh.shape[0] - 1)
        mesh[ix, :, 0] = mid_x + (frac - 0.5) * chord * scale
    return mesh


# ---------------------------------------------------------------------------
# Surface dict construction
# ---------------------------------------------------------------------------


def _plan_config_to_surface_dict(surface_config: dict) -> dict:
    """Translate plan YAML surface config to an OAS surface dict.

    Args:
        surface_config: Single surface entry from plan component config.

    Returns:
        OAS-compatible surface dict with mesh and all required fields.
    """
    # Generate mesh
    mesh, default_twist_cp = _generate_mesh(surface_config)

    # Apply geometric transforms
    sweep = surface_config.get("sweep", 0.0)
    dihedral = surface_config.get("dihedral", 0.0)
    taper = surface_config.get("taper", 1.0)
    mesh = _apply_sweep(mesh, sweep)
    mesh = _apply_dihedral(mesh, dihedral)
    mesh = _apply_taper(mesh, taper)

    # Warn if span looks like it might be a half-span value
    span = surface_config.get("span", 10.0)
    root_chord = surface_config.get("root_chord", 1.0)
    if surface_config.get("symmetry", True) and span < 3 * root_chord:
        logging.getLogger(__name__).warning(
            "span=%.1f with symmetry=True and root_chord=%.1f -- "
            "span should be the full wingspan (OAS halves it internally). "
            "Did you mean span=%.1f?",
            span, root_chord, span * 2,
        )

    # Build the surface dict
    surface: dict[str, Any] = {"name": surface_config["name"], "mesh": mesh}

    # Aero defaults
    for key, default in _DEFAULT_AERO_SURFACE.items():
        if key in surface_config:
            val = surface_config[key]
            if key == "t_over_c_cp":
                val = np.array(val)
            surface[key] = val
        else:
            if isinstance(default, list):
                surface[key] = np.array(default)
            else:
                surface[key] = default

    # Symmetry
    surface["symmetry"] = surface_config.get("symmetry", True)

    # Structural properties (required for aerostruct)
    fem_model_type = surface_config.get("fem_model_type", "tube")
    surface["fem_model_type"] = fem_model_type

    # Material properties (coerce to float -- YAML may parse scientific
    # notation like 70.0e9 as strings depending on the notation used)
    for prop in ("E", "G", "yield_stress", "mrho", "safety_factor"):
        if prop in surface_config:
            surface[prop] = float(surface_config[prop])

    # Map yield_stress to OAS "yield" key
    if "yield_stress" in surface and "yield" not in surface:
        surface["yield"] = surface.pop("yield_stress")

    # Structural defaults -- use plan config values, falling back to defaults
    for key, default in _DEFAULT_STRUCT_PROPS.items():
        if key in surface_config:
            surface[key] = surface_config[key]
        elif key not in surface:
            surface[key] = default

    # Control point arrays (root-to-tip, matching OAS convention)
    num_y = surface_config["num_y"]
    sym = surface_config.get("symmetry", True)
    num_twist_cp = surface_config.get("num_twist_cp")
    if num_twist_cp is not None:
        n_cp = num_twist_cp
    else:
        n_cp = (num_y + 1) // 2 if sym else num_y

    if "twist_cp" in surface_config:
        surface["twist_cp"] = np.array(surface_config["twist_cp"])
    elif default_twist_cp is not None:
        surface["twist_cp"] = default_twist_cp
    else:
        surface["twist_cp"] = np.zeros(n_cp)

    if fem_model_type == "tube":
        if "thickness_cp" in surface_config:
            surface["thickness_cp"] = np.array(surface_config["thickness_cp"])
        else:
            surface["thickness_cp"] = np.full(n_cp, 0.01)
    elif fem_model_type == "wingbox":
        if "spar_thickness_cp" in surface_config:
            surface["spar_thickness_cp"] = np.array(surface_config["spar_thickness_cp"])
        if "skin_thickness_cp" in surface_config:
            surface["skin_thickness_cp"] = np.array(surface_config["skin_thickness_cp"])
        # Wingbox-specific defaults
        surface.setdefault("strength_factor_for_upper_skin", 1.0)
        surface.setdefault("wing_weight_ratio",
                           float(surface_config.get("wing_weight_ratio", 2.0)))
        surface.setdefault("exact_failure_constraint",
                           surface_config.get("exact_failure_constraint", False))
        # Wingbox airfoil cross-section data
        for wb_key in ("data_x_upper", "data_x_lower", "data_y_upper",
                        "data_y_lower"):
            if wb_key in surface_config:
                surface[wb_key] = np.array(surface_config[wb_key])
        # Defaults for wingbox airfoil data (NASA SC2-0612 profile)
        if "data_x_upper" not in surface:
            _wb_x = np.linspace(0.1, 0.6, 51)
            surface["data_x_upper"] = _wb_x
            surface["data_x_lower"] = _wb_x
        if "data_y_upper" not in surface:
            # Symmetric NACA-like profile, t/c ~ 0.12
            _wb_x = surface["data_x_upper"]
            _t = 0.12
            _y = _t / 0.2 * (
                0.2969 * np.sqrt(_wb_x)
                - 0.1260 * _wb_x
                - 0.3516 * _wb_x**2
                + 0.2843 * _wb_x**3
                - 0.1015 * _wb_x**4
            )
            surface["data_y_upper"] = _y
            surface["data_y_lower"] = -_y
        if "original_wingbox_airfoil_t_over_c" in surface_config:
            surface["original_wingbox_airfoil_t_over_c"] = float(
                surface_config["original_wingbox_airfoil_t_over_c"]
            )
        elif "original_wingbox_airfoil_t_over_c" not in surface:
            surface["original_wingbox_airfoil_t_over_c"] = 0.12
        # Fuel parameters for wingbox volume constraints
        surface.setdefault("Wf_reserve",
                           float(surface_config.get("Wf_reserve", 0.0)))
        surface.setdefault("fuel_density",
                           float(surface_config.get("fuel_density", 803.0)))

    # Fuel parameters for distributed_fuel_weight (any FEM type)
    if surface.get("distributed_fuel_weight", False):
        surface.setdefault("Wf_reserve",
                           float(surface_config.get("Wf_reserve", 0.0)))
        surface.setdefault("fuel_density",
                           float(surface_config.get("fuel_density", 803.0)))

    # Composite laminate properties (wingbox only)
    if surface_config.get("use_composite", False):
        from openaerostruct.structures.utils import compute_composite_stiffness

        surface["useComposite"] = True
        for key in ("ply_angles", "ply_fractions"):
            if key in surface_config:
                surface[key] = surface_config[key]
        for key in ("E1", "E2", "nu12", "G12",
                     "sigma_t1", "sigma_c1", "sigma_t2", "sigma_c2",
                     "sigma_12max"):
            if key in surface_config:
                surface[key] = float(surface_config[key])
        compute_composite_stiffness(surface)  # sets effective E, G in-place

    # Point masses
    if "n_point_masses" in surface_config:
        surface["n_point_masses"] = int(surface_config["n_point_masses"])

    # Optional overrides
    for key in ("groundplane", "CL0", "CD0"):
        if key in surface_config:
            surface[key] = surface_config[key]

    return surface


# ---------------------------------------------------------------------------
# Connection wiring
# ---------------------------------------------------------------------------


def _connect_aerostruct_surface(
    model: om.Group,
    name: str,
    point_name: str,
    fem_model_type: str = "tube",
) -> None:
    """Connect an AerostructGeometry group to an AerostructPoint.

    Replicates the connection pattern from upstream OAS examples.

    Args:
        model: Top-level model group.
        name: Surface name.
        point_name: AerostructPoint subsystem name.
        fem_model_type: "tube" or "wingbox".
    """
    com_name = f"{point_name}.{name}_perf"

    # Structural stiffness and nodes to coupled group
    model.connect(
        f"{name}.local_stiff_transformed",
        f"{point_name}.coupled.{name}.local_stiff_transformed",
    )
    model.connect(f"{name}.nodes", f"{point_name}.coupled.{name}.nodes")
    model.connect(f"{name}.mesh", f"{point_name}.coupled.{name}.mesh")

    # Perf connections
    model.connect(f"{name}.nodes", f"{com_name}.nodes")
    model.connect(
        f"{name}.cg_location",
        f"{point_name}.total_perf.{name}_cg_location",
    )
    model.connect(
        f"{name}.structural_mass",
        f"{point_name}.total_perf.{name}_structural_mass",
    )
    model.connect(f"{name}.t_over_c", f"{com_name}.t_over_c")

    if fem_model_type.lower() == "wingbox":
        for prop in ("Qz", "J", "A_enc", "htop", "hbottom", "hfront", "hrear",
                      "spar_thickness"):
            model.connect(f"{name}.{prop}", f"{com_name}.{prop}")
    else:
        model.connect(f"{name}.radius", f"{com_name}.radius")
        model.connect(f"{name}.thickness", f"{com_name}.thickness")


# ---------------------------------------------------------------------------
# Factory entry point
# ---------------------------------------------------------------------------


def build_oas_aerostruct(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an OAS aerostructural problem from plan config.

    Creates a complete om.Problem with IndepVarComp, AerostructGeometry,
    AerostructPoint, and all connections. Returns a ready-to-setup Problem
    (setup() NOT called -- the materializer handles that).

    Args:
        component_config: The "config" dict from a plan component entry.
            Must contain "surfaces" list.
        operating_points: Flight conditions dict from plan.

    Returns:
        Tuple of (problem, metadata) where:
        - problem is the assembled om.Problem (setup NOT called)
        - metadata has point_name, surface_names, flight_conditions
    """
    surface_configs = component_config.get("surfaces", [])
    if not surface_configs:
        raise ValueError("component config must contain 'surfaces' list")

    # Build OAS surface dicts
    surfaces = [_plan_config_to_surface_dict(sc) for sc in surface_configs]

    # Merge flight conditions with defaults
    flight = {**_DEFAULT_FLIGHT_CONDITIONS, **operating_points}

    # Check for ground effect and rotational modes
    ground_effect = any(s.get("groundplane", False) for s in surfaces)
    omega = flight.get("omega")
    rotational = omega is not None

    # Build the problem
    prob = om.Problem(reports=False)

    # Point masses (optional)
    point_masses_cfg = operating_points.get("point_masses")
    has_point_masses = (
        point_masses_cfg is not None and len(point_masses_cfg) > 0
    )

    skip_fields = set(component_config.get("skip_fields") or [])

    # Independent variables
    indep = om.IndepVarComp()
    def _add(name, **kw):
        if name in skip_fields:
            return
        indep.add_output(name, **kw)
    _add("v", val=flight["velocity"], units="m/s")
    _add("alpha", val=flight["alpha"], units="deg")
    _add("beta", val=flight.get("beta", 0.0), units="deg")
    _add("Mach_number", val=flight["Mach_number"])
    _add("re", val=flight["re"], units="1/m")
    _add("rho", val=flight["rho"], units="kg/m**3")
    _add("CT", val=flight["CT"], units="1/s")
    _add("R", val=flight["R"], units="m")
    _add("speed_of_sound", val=flight["speed_of_sound"], units="m/s")
    _add("load_factor", val=flight["load_factor"])
    _add("empty_cg", val=np.array(flight["empty_cg"]), units="m")

    if has_point_masses:
        pm_arr = np.array(point_masses_cfg)
        pml_cfg = operating_points.get("point_mass_locations")
        pml_arr = np.array(pml_cfg) if pml_cfg is not None else np.zeros((1, 3))
        W0_wpm = float(operating_points.get(
            "W0_without_point_masses",
            flight["W0"],
        ))
        _add("W0_without_point_masses", val=W0_wpm, units="kg")
        _add("point_masses", val=pm_arr, units="kg")
        _add("point_mass_locations", val=pml_arr, units="m")
    else:
        _add("W0", val=flight["W0"], units="kg")
    if ground_effect:
        _add("height_agl", val=flight.get("height_agl", 8000.0), units="m")
    if rotational:
        _add("omega", val=np.array(omega) * np.pi / 180.0, units="rad/s")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    if has_point_masses:
        prob.model.add_subsystem(
            "W0_comp",
            om.ExecComp(
                "W0 = W0_without_point_masses + 2 * sum(point_masses)",
                units="kg",
            ),
            promotes=["*"],
        )

    point_name = "AS_point_0"

    # Geometry groups
    for surface in surfaces:
        as_geom = AerostructGeometry(surface=surface)
        prob.model.add_subsystem(surface["name"], as_geom)

    # Analysis point
    promotes = [
        "v", "alpha", "beta", "Mach_number", "re", "rho",
        "CT", "R", "W0", "speed_of_sound", "empty_cg", "load_factor",
    ]
    if ground_effect:
        promotes.append("height_agl")
    if rotational:
        promotes.extend(["omega", "cg"])

    as_point = AerostructPoint(surfaces=surfaces, rotational=rotational)
    prob.model.add_subsystem(point_name, as_point, promotes_inputs=promotes)

    # Wire connections
    for surface in surfaces:
        name = surface["name"]
        _connect_aerostruct_surface(
            prob.model,
            name,
            point_name,
            fem_model_type=surface.get("fem_model_type", "tube"),
        )
        if has_point_masses:
            coupled_name = f"{point_name}.coupled.{name}"
            prob.model.connect("point_masses",
                               f"{coupled_name}.point_masses")
            prob.model.connect("point_mass_locations",
                               f"{coupled_name}.point_mass_locations")

    # Build variable path mappings for the materializer
    surface_names = [s["name"] for s in surfaces]
    var_paths: dict[str, str] = {}
    for s_name in surface_names:
        var_paths["twist_cp"] = f"{s_name}.twist_cp"
        var_paths["thickness_cp"] = f"{s_name}.thickness_cp"
        var_paths["chord_cp"] = f"{s_name}.chord_cp"
        var_paths["spar_thickness_cp"] = f"{s_name}.spar_thickness_cp"
        var_paths["skin_thickness_cp"] = f"{s_name}.skin_thickness_cp"
        var_paths["t_over_c_cp"] = f"{s_name}.geometry.t_over_c_cp"
        var_paths["S_ref"] = f"{point_name}.{s_name}.S_ref"
        var_paths["structural_mass"] = f"{s_name}.structural_mass"
        # Aerostruct: perf outputs nested under {point}.{surf}_perf.{var}
        for perf_var in ("CL", "CD", "CDi", "CDv", "CDw", "CM"):
            var_paths[perf_var] = f"{point_name}.{s_name}_perf.{perf_var}"
        var_paths["failure"] = f"{point_name}.{s_name}_perf.failure"
        var_paths["tsaiwu_sr"] = f"{point_name}.{s_name}_perf.tsaiwu_sr"
    var_paths["L_equals_W"] = f"{point_name}.L_equals_W"
    var_paths["fuelburn"] = "fuelburn"

    metadata = {
        "point_name": point_name,
        "surface_names": surface_names,
        "surfaces": surfaces,
        "flight_conditions": flight,
        "var_paths": var_paths,
    }

    return prob, metadata


# ---------------------------------------------------------------------------
# Multipoint aerostruct factory
# ---------------------------------------------------------------------------


def build_oas_aerostruct_multipoint(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a multipoint OAS aerostructural problem from plan config.

    Creates shared geometry groups and N AerostructPoint groups (one per
    flight condition). Follows the upstream OAS multipoint tutorial and
    the hangar-oas MCP server's _assemble_multipoint_aerostruct_model().

    Args:
        component_config: The "config" dict from a plan component entry.
            Must contain "surfaces" list.
        operating_points: Must contain "flight_points" list and optional
            "shared" dict with common parameters (CT, R, W0_without_point_masses).

    Returns:
        Tuple of (problem, metadata) where problem has setup NOT called.
    """
    surface_configs = component_config.get("surfaces", [])
    if not surface_configs:
        raise ValueError("component config must contain 'surfaces' list")

    surfaces = [_plan_config_to_surface_dict(sc) for sc in surface_configs]

    flight_points = operating_points["flight_points"]
    shared = operating_points.get("shared", {})
    N = len(flight_points)

    # Shared mission parameters with defaults
    CT = float(shared.get("CT", _DEFAULT_FLIGHT_CONDITIONS["CT"]))
    R = float(shared.get("R", _DEFAULT_FLIGHT_CONDITIONS["R"]))
    W0_wpm = float(shared.get(
        "W0_without_point_masses",
        shared.get("W0", _DEFAULT_FLIGHT_CONDITIONS["W0"]),
    ))
    empty_cg = shared.get("empty_cg", _DEFAULT_FLIGHT_CONDITIONS["empty_cg"])
    alpha = float(shared.get("alpha", _DEFAULT_FLIGHT_CONDITIONS["alpha"]))
    alpha_maneuver = float(shared.get("alpha_maneuver", 0.0))
    fuel_mass = float(shared.get("fuel_mass", 10000.0))

    # Build per-point arrays
    v_arr = np.array([float(fp["velocity"]) for fp in flight_points])
    mach_arr = np.array([float(fp["Mach_number"]) for fp in flight_points])
    re_arr = np.array([float(fp.get("re", fp.get("reynolds_number", 1e6)))
                        for fp in flight_points])
    rho_arr = np.array([float(fp.get("rho", fp.get("density", 0.38)))
                         for fp in flight_points])
    sos_arr = np.array([float(fp.get("speed_of_sound",
                        _DEFAULT_FLIGHT_CONDITIONS["speed_of_sound"]))
                         for fp in flight_points])
    lf_arr = np.array([float(fp.get("load_factor", 1.0))
                        for fp in flight_points])

    # Point masses (optional)
    point_masses_cfg = shared.get("point_masses")
    has_point_masses = point_masses_cfg is not None and len(point_masses_cfg) > 0
    pm_arr = np.array(point_masses_cfg) if has_point_masses else np.zeros((1, 1))
    pml_cfg = shared.get("point_mass_locations")
    pml_arr = np.array(pml_cfg) if pml_cfg is not None else np.zeros((1, 3))

    # Build the problem
    prob = om.Problem(reports=False)

    indep = om.IndepVarComp()
    indep.add_output("v", val=v_arr, units="m/s")
    indep.add_output("Mach_number", val=mach_arr)
    indep.add_output("re", val=re_arr, units="1/m")
    indep.add_output("rho", val=rho_arr, units="kg/m**3")
    indep.add_output("speed_of_sound", val=sos_arr, units="m/s")
    indep.add_output("load_factor", val=lf_arr)
    indep.add_output("CT", val=CT, units="1/s")
    indep.add_output("R", val=R, units="m")
    indep.add_output("W0_without_point_masses", val=W0_wpm, units="kg")
    indep.add_output("alpha", val=alpha, units="deg")
    indep.add_output("alpha_maneuver", val=alpha_maneuver, units="deg")
    indep.add_output("empty_cg", val=np.array(empty_cg), units="m")
    indep.add_output("fuel_mass", val=fuel_mass, units="kg")
    indep.add_output("point_masses", val=pm_arr, units="kg")
    indep.add_output("point_mass_locations", val=pml_arr, units="m")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    # W0 = W0_without_point_masses + 2 * sum(point_masses)
    prob.model.add_subsystem(
        "W0_comp",
        om.ExecComp(
            "W0 = W0_without_point_masses + 2 * sum(point_masses)",
            units="kg",
        ),
        promotes=["*"],
    )

    # Shared geometry groups (one per surface)
    for surface in surfaces:
        prob.model.add_subsystem(
            surface["name"], AerostructGeometry(surface=surface),
        )

    # Analysis points (one per flight condition)
    point_names = []
    for i in range(N):
        pt = f"AS_point_{i}"
        point_names.append(pt)

        AS_point = AerostructPoint(
            surfaces=surfaces, internally_connect_fuelburn=False,
        )
        prob.model.add_subsystem(pt, AS_point)

        # Route per-point flight conditions via src_indices
        prob.model.connect("v", f"{pt}.v", src_indices=[i])
        prob.model.connect("Mach_number", f"{pt}.Mach_number", src_indices=[i])
        prob.model.connect("re", f"{pt}.re", src_indices=[i])
        prob.model.connect("rho", f"{pt}.rho", src_indices=[i])
        prob.model.connect("speed_of_sound", f"{pt}.speed_of_sound",
                           src_indices=[i])
        prob.model.connect("load_factor", f"{pt}.load_factor", src_indices=[i])

        # Shared scalar connections
        prob.model.connect("CT", f"{pt}.CT")
        prob.model.connect("R", f"{pt}.R")
        prob.model.connect("W0", f"{pt}.W0")
        prob.model.connect("empty_cg", f"{pt}.empty_cg")
        prob.model.connect("fuel_mass",
                           f"{pt}.total_perf.L_equals_W.fuelburn")
        prob.model.connect("fuel_mass", f"{pt}.total_perf.CG.fuelburn")

        # Wire each surface to this point
        for surface in surfaces:
            name = surface["name"]
            fem_type = surface.get("fem_model_type", "tube")
            struct_weight_relief = surface.get("struct_weight_relief", False)
            distributed_fuel_weight = surface.get(
                "distributed_fuel_weight", False,
            )

            if distributed_fuel_weight:
                prob.model.connect(
                    "load_factor",
                    f"{pt}.coupled.load_factor",
                    src_indices=[i],
                )

            _connect_aerostruct_surface(
                prob.model, name, pt, fem_model_type=fem_type,
            )

            if struct_weight_relief:
                prob.model.connect(
                    f"{name}.element_mass",
                    f"{pt}.coupled.{name}.element_mass",
                )

            if has_point_masses:
                coupled_name = f"{pt}.coupled.{name}"
                prob.model.connect("point_masses",
                                   f"{coupled_name}.point_masses")
                prob.model.connect("point_mass_locations",
                                   f"{coupled_name}.point_mass_locations")

            if distributed_fuel_weight:
                prob.model.connect(
                    f"{name}.struct_setup.fuel_vols",
                    f"{pt}.coupled.{name}.struct_states.fuel_vols",
                )
                prob.model.connect(
                    "fuel_mass",
                    f"{pt}.coupled.{name}.struct_states.fuel_mass",
                )

    # Alpha routing: cruise = alpha, maneuver = alpha_maneuver
    prob.model.connect("alpha", "AS_point_0.alpha")
    if N > 1:
        prob.model.connect("alpha_maneuver", "AS_point_1.alpha")

    # Fuel volume constraints (wingbox only)
    wingbox_surfaces = [
        s for s in surfaces if s.get("fem_model_type") == "wingbox"
    ]
    if wingbox_surfaces:
        from openaerostruct.structures.wingbox_fuel_vol_delta import (
            WingboxFuelVolDelta,
        )
        wb_surf = wingbox_surfaces[0]
        wb_name = wb_surf["name"]
        prob.model.add_subsystem(
            "fuel_vol_delta", WingboxFuelVolDelta(surface=wb_surf),
        )
        prob.model.connect(
            f"{wb_name}.struct_setup.fuel_vols",
            "fuel_vol_delta.fuel_vols",
        )
        prob.model.connect("AS_point_0.fuelburn", "fuel_vol_delta.fuelburn")

        comp = om.ExecComp(
            "fuel_diff = (fuel_mass - fuelburn) / fuelburn", units="kg",
        )
        prob.model.add_subsystem(
            "fuel_diff", comp,
            promotes_inputs=["fuel_mass"],
            promotes_outputs=["fuel_diff"],
        )
        prob.model.connect("AS_point_0.fuelburn", "fuel_diff.fuelburn")

    # Build point labels for metadata
    point_labels = []
    for i, fp in enumerate(flight_points):
        point_labels.append(fp.get("name", f"point_{i}"))

    # Build variable path mappings for the materializer
    surface_names_list = [s["name"] for s in surfaces]
    var_paths: dict[str, str] = {}
    for s_name in surface_names_list:
        var_paths["twist_cp"] = f"{s_name}.twist_cp"
        var_paths["thickness_cp"] = f"{s_name}.thickness_cp"
        var_paths["chord_cp"] = f"{s_name}.chord_cp"
        var_paths["spar_thickness_cp"] = f"{s_name}.spar_thickness_cp"
        var_paths["skin_thickness_cp"] = f"{s_name}.skin_thickness_cp"
        var_paths["t_over_c_cp"] = f"{s_name}.geometry.t_over_c_cp"
        var_paths["structural_mass"] = f"{s_name}.structural_mass"
        # Per-point perf outputs (use first point for default resolution)
        pt0 = point_names[0]
        for perf_var in ("CL", "CD", "CDi", "CDv", "CDw", "CM"):
            var_paths[perf_var] = f"{pt0}.{s_name}_perf.{perf_var}"
        var_paths["failure"] = f"{pt0}.{s_name}_perf.failure"
        var_paths["tsaiwu_sr"] = f"{pt0}.{s_name}_perf.tsaiwu_sr"
    var_paths["L_equals_W"] = f"{point_names[0]}.L_equals_W"
    var_paths["fuelburn"] = f"{point_names[0]}.fuelburn"
    var_paths["fuel_vol_delta"] = "fuel_vol_delta.fuel_vol_delta"
    var_paths["fuel_diff"] = "fuel_diff"

    metadata = {
        "point_names": point_names,
        "point_name": point_names[0],  # backwards compat
        "point_labels": point_labels,
        "surface_names": surface_names_list,
        "surfaces": surfaces,
        "flight_conditions": shared,
        "flight_points": flight_points,
        "multipoint": True,
        "var_paths": var_paths,
    }

    return prob, metadata
