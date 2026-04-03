"""OpenAeroStruct component factory.

Builds OAS aerostructural models from plan YAML configs using
upstream openaerostruct and openmdao APIs directly. No dependency
on hangar-oas.
"""

from __future__ import annotations

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
    """
    mesh_dict = {
        "num_x": config.get("num_x", 2),
        "num_y": config["num_y"],
        "wing_type": config.get("wing_type", "rect"),
        "symmetry": config.get("symmetry", True),
        "span": config.get("span", 10.0),
        "root_chord": config.get("root_chord", 1.0),
    }

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

    # Structural defaults
    for key, default in _DEFAULT_STRUCT_PROPS.items():
        if key not in surface:
            surface[key] = default

    # Control point arrays (root-to-tip, matching OAS convention)
    num_y = surface_config["num_y"]
    sym = surface_config.get("symmetry", True)
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
) -> tuple[om.Problem, dict]:
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

    # Independent variables
    indep = om.IndepVarComp()
    indep.add_output("v", val=flight["velocity"], units="m/s")
    indep.add_output("alpha", val=flight["alpha"], units="deg")
    indep.add_output("beta", val=flight.get("beta", 0.0), units="deg")
    indep.add_output("Mach_number", val=flight["Mach_number"])
    indep.add_output("re", val=flight["re"], units="1/m")
    indep.add_output("rho", val=flight["rho"], units="kg/m**3")
    indep.add_output("CT", val=flight["CT"], units="1/s")
    indep.add_output("R", val=flight["R"], units="m")
    indep.add_output("W0", val=flight["W0"], units="kg")
    indep.add_output("speed_of_sound", val=flight["speed_of_sound"], units="m/s")
    indep.add_output("load_factor", val=flight["load_factor"])
    indep.add_output(
        "empty_cg", val=np.array(flight["empty_cg"]), units="m"
    )
    if ground_effect:
        indep.add_output(
            "height_agl", val=flight.get("height_agl", 8000.0), units="m"
        )
    if rotational:
        indep.add_output(
            "omega", val=np.array(omega) * np.pi / 180.0, units="rad/s"
        )
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

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
        _connect_aerostruct_surface(
            prob.model,
            surface["name"],
            point_name,
            fem_model_type=surface.get("fem_model_type", "tube"),
        )

    metadata = {
        "point_name": point_name,
        "surface_names": [s["name"] for s in surfaces],
        "surfaces": surfaces,
        "flight_conditions": flight,
    }

    return prob, metadata
