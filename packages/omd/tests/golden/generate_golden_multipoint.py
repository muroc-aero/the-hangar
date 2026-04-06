#!/usr/bin/env python
"""Generate golden reference values for multipoint aerostructural optimization.

Uses raw OpenAeroStruct and OpenMDAO APIs (no hangar dependency) to produce
deterministic reference values. Run with fixed thread counts for reproducibility:

    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
        python packages/omd/tests/golden/generate_golden_multipoint.py
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import openmdao.api as om
from openaerostruct.meshing.mesh_generator import generate_mesh
from openaerostruct.integration.aerostruct_groups import (
    AerostructGeometry,
    AerostructPoint,
)


def build_multipoint_problem():
    """Build the golden multipoint problem matching the fixture config."""
    # Surface definition
    mesh_dict = {
        "num_x": 2,
        "num_y": 7,
        "wing_type": "rect",
        "symmetry": True,
        "span": 10.0,
        "root_chord": 1.0,
    }
    mesh = generate_mesh(mesh_dict)
    if isinstance(mesh, tuple):
        mesh = mesh[0]

    surface = {
        "name": "wing",
        "mesh": mesh,
        "symmetry": True,
        "S_ref_type": "wetted",
        "fem_model_type": "tube",
        "thickness_cp": np.full(4, 0.01),
        "twist_cp": np.zeros(4),
        "E": 7e10,
        "G": 3e10,
        "yield": 5e8,
        "mrho": 3000.0,
        "safety_factor": 1.5,
        "fem_origin": 0.35,
        "wing_weight_ratio": 2.0,
        "struct_weight_relief": False,
        "distributed_fuel_weight": False,
        "exact_failure_constraint": False,
        "CL0": 0.0,
        "CD0": 0.015,
        "k_lam": 0.05,
        "t_over_c_cp": np.array([0.15]),
        "c_max_t": 0.303,
        "with_viscous": True,
        "with_wave": False,
    }

    surfaces = [surface]

    # Flight points
    flight_points = [
        {"velocity": 248.136, "Mach_number": 0.84, "density": 0.38,
         "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 1.0},
        {"velocity": 248.136, "Mach_number": 0.84, "density": 0.38,
         "reynolds_number": 1e6, "speed_of_sound": 295.4, "load_factor": 2.5},
    ]

    N = len(flight_points)
    v_arr = np.array([fp["velocity"] for fp in flight_points])
    mach_arr = np.array([fp["Mach_number"] for fp in flight_points])
    re_arr = np.array([fp["reynolds_number"] for fp in flight_points])
    rho_arr = np.array([fp["density"] for fp in flight_points])
    sos_arr = np.array([fp["speed_of_sound"] for fp in flight_points])
    lf_arr = np.array([fp["load_factor"] for fp in flight_points])

    prob = om.Problem(reports=False)

    # Optimizer
    driver = om.ScipyOptimizeDriver()
    driver.options["optimizer"] = "SLSQP"
    driver.options["tol"] = 1e-8
    driver.options["maxiter"] = 200
    prob.driver = driver

    # Independent variables
    indep = om.IndepVarComp()
    indep.add_output("v", val=v_arr, units="m/s")
    indep.add_output("Mach_number", val=mach_arr)
    indep.add_output("re", val=re_arr, units="1/m")
    indep.add_output("rho", val=rho_arr, units="kg/m**3")
    indep.add_output("speed_of_sound", val=sos_arr, units="m/s")
    indep.add_output("load_factor", val=lf_arr)
    indep.add_output("CT", val=9.81e-6, units="1/s")
    indep.add_output("R", val=3e6, units="m")
    indep.add_output("W0_without_point_masses", val=5000.0, units="kg")
    indep.add_output("alpha", val=5.0, units="deg")
    indep.add_output("alpha_maneuver", val=0.0, units="deg")
    indep.add_output("empty_cg", val=np.zeros(3), units="m")
    indep.add_output("fuel_mass", val=10000.0, units="kg")
    indep.add_output("point_masses", val=np.zeros((1, 1)), units="kg")
    indep.add_output("point_mass_locations", val=np.zeros((1, 3)), units="m")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    prob.model.add_subsystem(
        "W0_comp",
        om.ExecComp("W0 = W0_without_point_masses + 2 * sum(point_masses)",
                     units="kg"),
        promotes=["*"],
    )

    # Shared geometry
    prob.model.add_subsystem("wing", AerostructGeometry(surface=surface))

    # Analysis points
    for i in range(N):
        pt = f"AS_point_{i}"
        AS_point = AerostructPoint(
            surfaces=surfaces, internally_connect_fuelburn=False,
        )
        prob.model.add_subsystem(pt, AS_point)

        prob.model.connect("v", f"{pt}.v", src_indices=[i])
        prob.model.connect("Mach_number", f"{pt}.Mach_number", src_indices=[i])
        prob.model.connect("re", f"{pt}.re", src_indices=[i])
        prob.model.connect("rho", f"{pt}.rho", src_indices=[i])
        prob.model.connect("speed_of_sound", f"{pt}.speed_of_sound",
                           src_indices=[i])
        prob.model.connect("load_factor", f"{pt}.load_factor", src_indices=[i])
        prob.model.connect("CT", f"{pt}.CT")
        prob.model.connect("R", f"{pt}.R")
        prob.model.connect("W0", f"{pt}.W0")
        prob.model.connect("empty_cg", f"{pt}.empty_cg")
        prob.model.connect("fuel_mass", f"{pt}.total_perf.L_equals_W.fuelburn")
        prob.model.connect("fuel_mass", f"{pt}.total_perf.CG.fuelburn")

        # Wire surface connections
        prob.model.connect("wing.local_stiff_transformed",
                           f"{pt}.coupled.wing.local_stiff_transformed")
        prob.model.connect("wing.nodes", f"{pt}.coupled.wing.nodes")
        prob.model.connect("wing.mesh", f"{pt}.coupled.wing.mesh")
        prob.model.connect("wing.nodes", f"{pt}.wing_perf.nodes")
        prob.model.connect("wing.cg_location",
                           f"{pt}.total_perf.wing_cg_location")
        prob.model.connect("wing.structural_mass",
                           f"{pt}.total_perf.wing_structural_mass")
        prob.model.connect("wing.t_over_c", f"{pt}.wing_perf.t_over_c")
        prob.model.connect("wing.radius", f"{pt}.wing_perf.radius")
        prob.model.connect("wing.thickness", f"{pt}.wing_perf.thickness")

    prob.model.connect("alpha", "AS_point_0.alpha")
    prob.model.connect("alpha_maneuver", "AS_point_1.alpha")

    # Design variables
    prob.model.add_design_var("wing.twist_cp", lower=-5, upper=10, scaler=0.1)
    prob.model.add_design_var("wing.thickness_cp", lower=0.001, upper=0.1,
                              scaler=100)
    prob.model.add_design_var("alpha", lower=-5, upper=10)
    prob.model.add_design_var("alpha_maneuver", lower=-5, upper=10)

    # Constraints
    prob.model.add_constraint("AS_point_0.wing_perf.CL", equals=0.5)
    prob.model.add_constraint("AS_point_0.wing_perf.failure", upper=0.0)
    prob.model.add_constraint("AS_point_1.wing_perf.failure", upper=0.0)

    # Objective
    prob.model.add_objective("AS_point_0.CD")

    prob.setup()
    return prob


def main():
    prob = build_multipoint_problem()
    prob.run_driver()

    results = {
        "cruise": {
            "CL": float(prob.get_val("AS_point_0.wing_perf.CL")[0]),
            "CD": float(prob.get_val("AS_point_0.CD")[0]),
            "failure": float(np.max(prob.get_val("AS_point_0.wing_perf.failure"))),
            "structural_mass_kg": float(prob.get_val("wing.structural_mass")),
        },
        "maneuver": {
            "CL": float(prob.get_val("AS_point_1.wing_perf.CL")[0]),
            "CD": float(prob.get_val("AS_point_1.CD")[0]),
            "failure": float(np.max(prob.get_val("AS_point_1.wing_perf.failure"))),
        },
        "optimized_dvs": {
            "twist": prob.get_val("wing.twist_cp").tolist(),
            "thickness": prob.get_val("wing.thickness_cp").tolist(),
            "alpha": float(prob.get_val("alpha")),
            "alpha_maneuver": float(prob.get_val("alpha_maneuver")),
        },
    }

    print("\n=== Golden multipoint results ===")
    for section, data in results.items():
        print(f"\n{section}:")
        for k, v in data.items():
            if isinstance(v, list):
                print(f"  {k}: {[round(x, 6) for x in v]}")
            else:
                print(f"  {k}: {v:.6f}")

    # Update golden file
    golden_path = Path(__file__).parent / "golden_multipoint.json"
    with open(golden_path) as f:
        golden = json.load(f)

    golden["expected"] = results
    try:
        import openmdao
        om_version = openmdao.__version__
    except AttributeError:
        om_version = "unknown"
    golden["reproducibility_header"] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "openmdao_version": om_version,
        "numpy_version": np.__version__,
    }

    with open(golden_path, "w") as f:
        json.dump(golden, f, indent=2)

    print(f"\nGolden values written to {golden_path}")
    prob.cleanup()


if __name__ == "__main__":
    main()
