"""Export analysis plans to standalone Python scripts.

Generates Python scripts that use only openmdao and openaerostruct
imports (no hangar dependency), making them portable for sharing
or archiving.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml


def export_plan_to_script(
    plan_path: Path,
    output_path: Path,
) -> None:
    """Generate a standalone Python script from a plan YAML.

    The generated script reproduces the analysis using only upstream
    openmdao and openaerostruct APIs.

    Args:
        plan_path: Path to assembled plan.yaml.
        output_path: Path for the output .py script.
    """
    with open(plan_path) as f:
        plan = yaml.safe_load(f)

    components = plan.get("components", [])
    operating_points = plan.get("operating_points", {})

    if not components:
        raise ValueError("Plan must contain at least one component")

    comp = components[0]
    comp_type = comp.get("type", "")

    if comp_type == "oas/AerostructPoint":
        script = _export_oas_aerostruct(plan, comp, operating_points)
    elif comp_type == "oas/AerostructMultipoint":
        script = _export_oas_aerostruct_multipoint(plan, comp, operating_points)
    elif comp_type == "paraboloid/Paraboloid":
        script = _export_paraboloid(plan, operating_points)
    else:
        raise NotImplementedError(
            f"Export not yet supported for component type: {comp_type}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(script)


def _export_oas_aerostruct(
    plan: dict,
    component: dict,
    operating_points: dict,
) -> str:
    """Generate script for an OAS aerostruct analysis."""
    config = component.get("config", {})
    surfaces = config.get("surfaces", [])
    meta = plan.get("metadata", {})

    # Build the surface config lines
    surface_lines = []
    for sc in surfaces:
        surface_lines.append(_format_surface_config(sc))

    op = {
        "velocity": operating_points.get("velocity", 248.136),
        "alpha": operating_points.get("alpha", 5.0),
        "Mach_number": operating_points.get("Mach_number", 0.84),
        "re": operating_points.get("re", 1.0e6),
        "rho": operating_points.get("rho", 0.38),
        "CT": operating_points.get("CT", 9.81e-6),
        "R": operating_points.get("R", 14.3e6),
        "W0": operating_points.get("W0", 25000.0),
        "speed_of_sound": operating_points.get("speed_of_sound", 295.07),
        "load_factor": operating_points.get("load_factor", 1.0),
        "empty_cg": operating_points.get("empty_cg", [0.35, 0.0, 0.0]),
    }

    surfaces_str = ",\n    ".join(surface_lines)
    op_str = json.dumps(op, indent=4)

    lines = [
        '#!/usr/bin/env python',
        '"""Standalone OAS aerostruct analysis.',
        '',
        f'Generated from plan: {meta.get("name", "unknown")}',
        f'Plan ID: {meta.get("id", "unknown")} v{meta.get("version", 0)}',
        '',
        'Dependencies: openmdao, openaerostruct, numpy',
        '"""',
        '',
        'import numpy as np',
        'import openmdao.api as om',
        'from openaerostruct.meshing.mesh_generator import generate_mesh',
        'from openaerostruct.integration.aerostruct_groups import (',
        '    AerostructGeometry,',
        '    AerostructPoint,',
        ')',
        '',
        '',
        'def build_surface(config):',
        '    """Build an OAS surface dict from config."""',
        '    mesh_dict = {',
        '        "num_x": config.get("num_x", 2),',
        '        "num_y": config["num_y"],',
        '        "wing_type": config.get("wing_type", "rect"),',
        '        "symmetry": config.get("symmetry", True),',
        '        "span": config.get("span", 10.0),',
        '        "root_chord": config.get("root_chord", 1.0),',
        '    }',
        '    result = generate_mesh(mesh_dict)',
        '    mesh = result[0] if isinstance(result, tuple) else result',
        '    num_y = config["num_y"]',
        '    sym = config.get("symmetry", True)',
        '    n_cp = (num_y + 1) // 2 if sym else num_y',
        '    surface = {',
        '        "name": config["name"], "mesh": mesh,',
        '        "symmetry": config.get("symmetry", True),',
        '        "S_ref_type": "wetted",',
        '        "CL0": config.get("CL0", 0.0), "CD0": config.get("CD0", 0.015),',
        '        "k_lam": 0.05, "t_over_c_cp": np.array(config.get("t_over_c_cp", [0.15])),',
        '        "c_max_t": 0.303,',
        '        "with_viscous": config.get("with_viscous", True),',
        '        "with_wave": config.get("with_wave", False),',
        '        "fem_model_type": config.get("fem_model_type", "tube"),',
        '        "fem_origin": 0.35, "wing_weight_ratio": 2.0,',
        '        "struct_weight_relief": False, "distributed_fuel_weight": False,',
        '        "exact_failure_constraint": False,',
        '        "twist_cp": np.array(config.get("twist_cp", [0.0] * n_cp)),',
        '    }',
        '    if config.get("E"): surface["E"] = config["E"]',
        '    if config.get("G"): surface["G"] = config["G"]',
        '    if config.get("yield_stress"): surface["yield"] = config["yield_stress"]',
        '    if config.get("mrho"): surface["mrho"] = config["mrho"]',
        '    if config.get("safety_factor"): surface["safety_factor"] = config["safety_factor"]',
        '    if surface["fem_model_type"] == "tube":',
        '        surface["thickness_cp"] = np.array(config.get("thickness_cp", [0.01] * n_cp))',
        '    return surface',
        '',
        '',
        'def connect_aerostruct_surface(model, name, point_name, fem_model_type="tube"):',
        '    """Wire connections between geometry and analysis point."""',
        '    com_name = f"{point_name}.{name}_perf"',
        '    model.connect(f"{name}.local_stiff_transformed",',
        '                  f"{point_name}.coupled.{name}.local_stiff_transformed")',
        '    model.connect(f"{name}.nodes", f"{point_name}.coupled.{name}.nodes")',
        '    model.connect(f"{name}.mesh", f"{point_name}.coupled.{name}.mesh")',
        '    model.connect(f"{name}.nodes", f"{com_name}.nodes")',
        '    model.connect(f"{name}.cg_location",',
        '                  f"{point_name}.total_perf.{name}_cg_location")',
        '    model.connect(f"{name}.structural_mass",',
        '                  f"{point_name}.total_perf.{name}_structural_mass")',
        '    model.connect(f"{name}.t_over_c", f"{com_name}.t_over_c")',
        '    if fem_model_type == "tube":',
        '        model.connect(f"{name}.radius", f"{com_name}.radius")',
        '        model.connect(f"{name}.thickness", f"{com_name}.thickness")',
        '',
        '',
        'def main():',
        '    surface_configs = [',
        f'        {surfaces_str}',
        '    ]',
        f'    op = {op_str}',
        '    surfaces = [build_surface(sc) for sc in surface_configs]',
        '    prob = om.Problem(reports=False)',
        '    indep = om.IndepVarComp()',
        '    indep.add_output("v", val=op["velocity"], units="m/s")',
        '    indep.add_output("alpha", val=op["alpha"], units="deg")',
        '    indep.add_output("beta", val=0.0, units="deg")',
        '    indep.add_output("Mach_number", val=op["Mach_number"])',
        '    indep.add_output("re", val=op["re"], units="1/m")',
        '    indep.add_output("rho", val=op["rho"], units="kg/m**3")',
        '    indep.add_output("CT", val=op["CT"], units="1/s")',
        '    indep.add_output("R", val=op["R"], units="m")',
        '    indep.add_output("W0", val=op["W0"], units="kg")',
        '    indep.add_output("speed_of_sound", val=op["speed_of_sound"], units="m/s")',
        '    indep.add_output("load_factor", val=op["load_factor"])',
        '    indep.add_output("empty_cg", val=np.array(op["empty_cg"]), units="m")',
        '    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])',
        '    point_name = "AS_point_0"',
        '    for surface in surfaces:',
        '        prob.model.add_subsystem(surface["name"], AerostructGeometry(surface=surface))',
        '    promotes = ["v", "alpha", "beta", "Mach_number", "re", "rho",',
        '                "CT", "R", "W0", "speed_of_sound", "empty_cg", "load_factor"]',
        '    prob.model.add_subsystem(point_name, AerostructPoint(surfaces=surfaces),',
        '                             promotes_inputs=promotes)',
        '    for surface in surfaces:',
        '        connect_aerostruct_surface(prob.model, surface["name"], point_name,',
        '                                   surface.get("fem_model_type", "tube"))',
        '    prob.setup()',
        '    prob.run_model()',
        '    CL = prob.get_val(f"{point_name}.CL")[0]',
        '    CD = prob.get_val(f"{point_name}.CD")[0]',
        '    print(f"CL = {CL:.6f}")',
        '    print(f"CD = {CD:.6f}")',
        '    print(f"L/D = {CL/CD:.2f}")',
        '    for surface in surfaces:',
        '        name = surface["name"]',
        '        mass = prob.get_val(f"{point_name}.{name}_perf.structural_mass")',
        '        print(f"{name} structural mass = {float(mass.sum()):.1f} kg")',
        '',
        '',
        'if __name__ == "__main__":',
        '    main()',
    ]
    script = "\n".join(lines) + "\n"

    return script


def _export_oas_aerostruct_multipoint(
    plan: dict,
    component: dict,
    operating_points: dict,
) -> str:
    """Generate script for a multipoint OAS aerostruct problem."""
    config = component.get("config", {})
    surfaces = config.get("surfaces", [])
    meta = plan.get("metadata", {})

    surface_lines = []
    for sc in surfaces:
        surface_lines.append(_format_surface_config(sc))

    flight_points = operating_points.get("flight_points", [])
    shared = operating_points.get("shared", {})

    surfaces_str = ",\n    ".join(surface_lines)
    fp_str = json.dumps(flight_points, indent=4)
    shared_str = json.dumps(shared, indent=4)

    lines = [
        '#!/usr/bin/env python',
        '"""Standalone multipoint OAS aerostruct analysis.',
        '',
        f'Generated from plan: {meta.get("name", "unknown")}',
        f'Plan ID: {meta.get("id", "unknown")} v{meta.get("version", 0)}',
        '',
        'Dependencies: openmdao, openaerostruct, numpy',
        '"""',
        '',
        'import numpy as np',
        'import openmdao.api as om',
        'from openaerostruct.meshing.mesh_generator import generate_mesh',
        'from openaerostruct.integration.aerostruct_groups import (',
        '    AerostructGeometry,',
        '    AerostructPoint,',
        ')',
        '',
        '',
        '# (build_surface and connect_aerostruct_surface same as single-point)',
        'def build_surface(config):',
        '    mesh_dict = {"num_x": config.get("num_x", 2), "num_y": config["num_y"],',
        '                 "wing_type": config.get("wing_type", "rect"),',
        '                 "symmetry": config.get("symmetry", True),',
        '                 "span": config.get("span", 10.0), "root_chord": config.get("root_chord", 1.0)}',
        '    result = generate_mesh(mesh_dict)',
        '    mesh = result[0] if isinstance(result, tuple) else result',
        '    n_cp = (config["num_y"] + 1) // 2 if config.get("symmetry", True) else config["num_y"]',
        '    surface = {"name": config["name"], "mesh": mesh, "symmetry": config.get("symmetry", True),',
        '              "S_ref_type": "wetted", "CL0": 0.0, "CD0": config.get("CD0", 0.015),',
        '              "k_lam": 0.05, "t_over_c_cp": np.array([0.15]), "c_max_t": 0.303,',
        '              "with_viscous": True, "with_wave": False,',
        '              "fem_model_type": config.get("fem_model_type", "tube"),',
        '              "fem_origin": 0.35, "wing_weight_ratio": 2.0,',
        '              "struct_weight_relief": False, "distributed_fuel_weight": False,',
        '              "exact_failure_constraint": False,',
        '              "twist_cp": np.zeros(n_cp)}',
        '    if config.get("E"): surface["E"] = config["E"]',
        '    if config.get("G"): surface["G"] = config["G"]',
        '    if config.get("yield_stress"): surface["yield"] = config["yield_stress"]',
        '    if config.get("mrho"): surface["mrho"] = config["mrho"]',
        '    if config.get("safety_factor"): surface["safety_factor"] = config["safety_factor"]',
        '    if surface["fem_model_type"] == "tube":',
        '        surface["thickness_cp"] = np.array(config.get("thickness_cp", [0.01] * n_cp))',
        '    return surface',
        '',
        '',
        'def connect_aerostruct_surface(model, name, point_name, fem_model_type="tube"):',
        '    com_name = f"{point_name}.{name}_perf"',
        '    model.connect(f"{name}.local_stiff_transformed", f"{point_name}.coupled.{name}.local_stiff_transformed")',
        '    model.connect(f"{name}.nodes", f"{point_name}.coupled.{name}.nodes")',
        '    model.connect(f"{name}.mesh", f"{point_name}.coupled.{name}.mesh")',
        '    model.connect(f"{name}.nodes", f"{com_name}.nodes")',
        '    model.connect(f"{name}.cg_location", f"{point_name}.total_perf.{name}_cg_location")',
        '    model.connect(f"{name}.structural_mass", f"{point_name}.total_perf.{name}_structural_mass")',
        '    model.connect(f"{name}.t_over_c", f"{com_name}.t_over_c")',
        '    if fem_model_type == "tube":',
        '        model.connect(f"{name}.radius", f"{com_name}.radius")',
        '        model.connect(f"{name}.thickness", f"{com_name}.thickness")',
        '',
        '',
        'def main():',
        '    surface_configs = [',
        f'        {surfaces_str}',
        '    ]',
        f'    flight_points = {fp_str}',
        f'    shared = {shared_str}',
        '    surfaces = [build_surface(sc) for sc in surface_configs]',
        '    N = len(flight_points)',
        '    prob = om.Problem(reports=False)',
        '    v_arr = np.array([fp["velocity"] for fp in flight_points])',
        '    mach_arr = np.array([fp["Mach_number"] for fp in flight_points])',
        '    re_arr = np.array([fp.get("reynolds_number", 1e6) for fp in flight_points])',
        '    rho_arr = np.array([fp.get("density", 0.38) for fp in flight_points])',
        '    sos_arr = np.array([fp.get("speed_of_sound", 295.4) for fp in flight_points])',
        '    lf_arr = np.array([fp.get("load_factor", 1.0) for fp in flight_points])',
        '    indep = om.IndepVarComp()',
        '    indep.add_output("v", val=v_arr, units="m/s")',
        '    indep.add_output("Mach_number", val=mach_arr)',
        '    indep.add_output("re", val=re_arr, units="1/m")',
        '    indep.add_output("rho", val=rho_arr, units="kg/m**3")',
        '    indep.add_output("speed_of_sound", val=sos_arr, units="m/s")',
        '    indep.add_output("load_factor", val=lf_arr)',
        f'    indep.add_output("CT", val={shared.get("CT", 9.81e-6)}, units="1/s")',
        f'    indep.add_output("R", val={shared.get("R", 3e6)}, units="m")',
        f'    indep.add_output("W0_without_point_masses", val={shared.get("W0_without_point_masses", 5000)}, units="kg")',
        f'    indep.add_output("alpha", val={shared.get("alpha", 5.0)}, units="deg")',
        '    indep.add_output("alpha_maneuver", val=0.0, units="deg")',
        '    indep.add_output("empty_cg", val=np.zeros(3), units="m")',
        '    indep.add_output("fuel_mass", val=10000.0, units="kg")',
        '    indep.add_output("point_masses", val=np.zeros((1, 1)), units="kg")',
        '    indep.add_output("point_mass_locations", val=np.zeros((1, 3)), units="m")',
        '    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])',
        '    prob.model.add_subsystem("W0_comp",',
        '        om.ExecComp("W0 = W0_without_point_masses + 2 * sum(point_masses)", units="kg"),',
        '        promotes=["*"])',
        '    for surface in surfaces:',
        '        prob.model.add_subsystem(surface["name"], AerostructGeometry(surface=surface))',
        '    for i in range(N):',
        '        pt = f"AS_point_{i}"',
        '        prob.model.add_subsystem(pt, AerostructPoint(surfaces=surfaces, internally_connect_fuelburn=False))',
        '        prob.model.connect("v", f"{pt}.v", src_indices=[i])',
        '        prob.model.connect("Mach_number", f"{pt}.Mach_number", src_indices=[i])',
        '        prob.model.connect("re", f"{pt}.re", src_indices=[i])',
        '        prob.model.connect("rho", f"{pt}.rho", src_indices=[i])',
        '        prob.model.connect("speed_of_sound", f"{pt}.speed_of_sound", src_indices=[i])',
        '        prob.model.connect("load_factor", f"{pt}.load_factor", src_indices=[i])',
        '        prob.model.connect("CT", f"{pt}.CT")',
        '        prob.model.connect("R", f"{pt}.R")',
        '        prob.model.connect("W0", f"{pt}.W0")',
        '        prob.model.connect("empty_cg", f"{pt}.empty_cg")',
        '        prob.model.connect("fuel_mass", f"{pt}.total_perf.L_equals_W.fuelburn")',
        '        prob.model.connect("fuel_mass", f"{pt}.total_perf.CG.fuelburn")',
        '        for surface in surfaces:',
        '            connect_aerostruct_surface(prob.model, surface["name"], pt,',
        '                                       surface.get("fem_model_type", "tube"))',
        '    prob.model.connect("alpha", "AS_point_0.alpha")',
        '    if N > 1:',
        '        prob.model.connect("alpha_maneuver", "AS_point_1.alpha")',
        '    prob.setup()',
        '    prob.run_model()',
        '    for i in range(N):',
        '        pt = f"AS_point_{i}"',
        '        CL = prob.get_val(f"{pt}.CL")[0]',
        '        CD = prob.get_val(f"{pt}.CD")[0]',
        '        label = flight_points[i].get("name", f"point_{i}")',
        '        print(f"{label}: CL={CL:.6f}, CD={CD:.6f}, L/D={CL/CD:.2f}")',
        '',
        '',
        'if __name__ == "__main__":',
        '    main()',
    ]
    return "\n".join(lines) + "\n"


def _export_paraboloid(plan: dict, operating_points: dict) -> str:
    """Generate a standalone script for the paraboloid problem."""
    meta = plan.get("metadata", {})
    x = operating_points.get("x", 0.0)
    y = operating_points.get("y", 0.0)

    lines = [
        '#!/usr/bin/env python',
        f'"""Standalone paraboloid analysis. Plan: {meta.get("name", "unknown")}"""',
        '',
        'import openmdao.api as om',
        '',
        '',
        'class Paraboloid(om.ExplicitComponent):',
        '    def setup(self):',
        '        self.add_input("x", val=0.0)',
        '        self.add_input("y", val=0.0)',
        '        self.add_output("f_xy", val=0.0)',
        '        self.declare_partials("*", "*")',
        '',
        '    def compute(self, inputs, outputs):',
        '        x, y = inputs["x"], inputs["y"]',
        '        outputs["f_xy"] = (x - 3.0)**2 + x * y + (y + 4.0)**2 - 3.0',
        '',
        '    def compute_partials(self, inputs, J):',
        '        x, y = inputs["x"], inputs["y"]',
        '        J["f_xy", "x"] = 2.0 * x - 6.0 + y',
        '        J["f_xy", "y"] = 2.0 * y + 8.0 + x',
        '',
        '',
        'def main():',
        '    prob = om.Problem(reports=False)',
        '    prob.model.add_subsystem("paraboloid", Paraboloid(), promotes=["*"])',
        '    prob.setup()',
        f'    prob.set_val("x", {x})',
        f'    prob.set_val("y", {y})',
        '    prob.run_model()',
        '    f = prob.get_val("f_xy")[0]',
        '    print(f"f_xy = {f:.6f}")',
        '',
        '',
        'if __name__ == "__main__":',
        '    main()',
    ]
    return "\n".join(lines) + "\n"


def _format_surface_config(sc: dict) -> str:
    """Format a surface config dict as a Python dict literal."""
    # Filter out numpy-incompatible keys for the literal
    safe_keys = [
        "name", "wing_type", "num_x", "num_y", "span", "root_chord",
        "symmetry", "fem_model_type", "E", "G", "yield_stress", "mrho",
        "safety_factor", "with_viscous", "with_wave", "CL0", "CD0",
        "sweep", "dihedral", "taper",
    ]
    items = []
    for key in safe_keys:
        if key in sc:
            items.append(f'"{key}": {repr(sc[key])}')

    # Array keys
    for key in ("twist_cp", "thickness_cp", "t_over_c_cp",
                "spar_thickness_cp", "skin_thickness_cp"):
        if key in sc:
            items.append(f'"{key}": {sc[key]}')

    return "{" + ", ".join(items) + "}"
