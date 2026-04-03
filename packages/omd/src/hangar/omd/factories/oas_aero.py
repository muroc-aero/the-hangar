"""OpenAeroStruct aero-only (VLM) component factory.

Builds OAS AeroPoint models from plan YAML configs using upstream
openaerostruct and openmdao APIs directly. No structural analysis,
no coupling -- pure aerodynamics via the vortex lattice method.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import openmdao.api as om
from openaerostruct.geometry.geometry_group import Geometry
from openaerostruct.aerodynamics.aero_groups import AeroPoint

# Reuse mesh and surface helpers from the aerostruct factory
from hangar.omd.factories.oas import (
    _generate_mesh,
    _apply_sweep,
    _apply_dihedral,
    _apply_taper,
    _DEFAULT_AERO_SURFACE,
)


# ---------------------------------------------------------------------------
# Default flight conditions (aero-only, no structural vars)
# ---------------------------------------------------------------------------

_DEFAULT_AERO_CONDITIONS: dict[str, Any] = {
    "velocity": 248.136,
    "alpha": 5.0,
    "Mach_number": 0.84,
    "re": 1.0e6,
    "rho": 0.38,
    "cg": [0.0, 0.0, 0.0],
}


# ---------------------------------------------------------------------------
# Surface dict construction (aero-only)
# ---------------------------------------------------------------------------


def _plan_config_to_aero_surface(surface_config: dict) -> dict:
    """Translate plan YAML surface config to an aero-only OAS surface dict.

    No structural properties, no fem_model_type.
    """
    mesh, default_twist_cp = _generate_mesh(surface_config)

    sweep = surface_config.get("sweep", 0.0)
    dihedral = surface_config.get("dihedral", 0.0)
    taper = surface_config.get("taper", 1.0)
    mesh = _apply_sweep(mesh, sweep)
    mesh = _apply_dihedral(mesh, dihedral)
    mesh = _apply_taper(mesh, taper)

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

    surface["symmetry"] = surface_config.get("symmetry", True)

    # Twist control points
    num_y = surface_config["num_y"]
    sym = surface_config.get("symmetry", True)
    n_cp = (num_y + 1) // 2 if sym else num_y

    if "twist_cp" in surface_config:
        surface["twist_cp"] = np.array(surface_config["twist_cp"])
    elif default_twist_cp is not None:
        surface["twist_cp"] = default_twist_cp
    else:
        surface["twist_cp"] = np.zeros(n_cp)

    # Optional overrides
    for key in ("groundplane", "CL0", "CD0"):
        if key in surface_config:
            surface[key] = surface_config[key]

    return surface


# ---------------------------------------------------------------------------
# Connection wiring (aero-only)
# ---------------------------------------------------------------------------


def _connect_aero_surface(
    model: om.Group,
    name: str,
    point_name: str,
) -> None:
    """Connect a Geometry group to an AeroPoint.

    Args:
        model: Top-level model group.
        name: Surface name.
        point_name: AeroPoint subsystem name.
    """
    model.connect(f"{name}.mesh", f"{point_name}.{name}.def_mesh")
    model.connect(f"{name}.mesh", f"{point_name}.aero_states.{name}_def_mesh")
    model.connect(f"{name}.t_over_c", f"{point_name}.{name}_perf.t_over_c")


# ---------------------------------------------------------------------------
# Factory entry point
# ---------------------------------------------------------------------------


def build_oas_aeropoint(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, dict]:
    """Build an OAS aero-only problem from plan config.

    Args:
        component_config: Must contain "surfaces" list.
        operating_points: Flight conditions dict.

    Returns:
        Tuple of (problem, metadata). Problem has setup NOT called.
    """
    surface_configs = component_config.get("surfaces", [])
    if not surface_configs:
        raise ValueError("component config must contain 'surfaces' list")

    surfaces = [_plan_config_to_aero_surface(sc) for sc in surface_configs]

    flight = {**_DEFAULT_AERO_CONDITIONS, **operating_points}

    ground_effect = any(s.get("groundplane", False) for s in surfaces)

    prob = om.Problem(reports=False)

    # Independent variables (aero-only: no CT, R, W0, etc.)
    indep = om.IndepVarComp()
    indep.add_output("v", val=flight["velocity"], units="m/s")
    indep.add_output("alpha", val=flight["alpha"], units="deg")
    indep.add_output("beta", val=flight.get("beta", 0.0), units="deg")
    indep.add_output("Mach_number", val=flight["Mach_number"])
    indep.add_output("re", val=flight["re"], units="1/m")
    indep.add_output("rho", val=flight["rho"], units="kg/m**3")
    indep.add_output("cg", val=np.array(flight.get("cg", [0.0, 0.0, 0.0])), units="m")
    if ground_effect:
        indep.add_output(
            "height_agl", val=flight.get("height_agl", 8000.0), units="m"
        )
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    point_name = "aero_point_0"

    # Geometry groups
    for surface in surfaces:
        prob.model.add_subsystem(surface["name"], Geometry(surface=surface))

    # Analysis point
    promotes = ["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"]
    if ground_effect:
        promotes.append("height_agl")

    aero_group = AeroPoint(surfaces=surfaces)
    prob.model.add_subsystem(point_name, aero_group, promotes_inputs=promotes)

    # Wire connections
    for surface in surfaces:
        _connect_aero_surface(prob.model, surface["name"], point_name)

    metadata = {
        "point_name": point_name,
        "surface_names": [s["name"] for s in surfaces],
        "surfaces": surfaces,
        "flight_conditions": flight,
    }

    return prob, metadata
