"""Lane A: compositional reference for the loose-coupled OAS -> Aviary case.

No single upstream script does this composition, so the oracle is built
from the two certified raw pieces: (1) a raw OpenAeroStruct aerostructural
analysis in THIS venv (the ``oas_aerostruct_rect`` Lane A formulation with
the transport-scale surface from ``shared``), (2) its structural mass
handed -- kg converted to lbm here, exactly the conversion the OpenMDAO
connection performs in Lane B -- to a raw-Aviary override sizing run in
.venv-avy (``avy_override_sizing.py``).

Run standalone (main venv):
    uv run python packages/omd/examples/oas_avy_wing_mass/lane_a/coupled_wing_mass.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import FLIGHT, WING  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[5]
_AVY_PYTHON = _REPO_ROOT / ".venv-avy" / "bin" / "python"
_AVY_SCRIPT = Path(__file__).with_name("avy_override_sizing.py")

LBM_PER_KG = 1.0 / 0.45359237


def run_oas() -> float:
    """Raw OAS aerostructural analysis; return structural mass in kg."""
    import openmdao.api as om
    from openaerostruct.integration.aerostruct_groups import (
        AerostructGeometry,
        AerostructPoint,
    )
    from openaerostruct.meshing.mesh_generator import generate_mesh

    mesh_dict = {
        k: WING[k]
        for k in ("num_x", "num_y", "wing_type", "symmetry", "span", "root_chord")
    }
    mesh = generate_mesh(mesh_dict)
    if isinstance(mesh, tuple):
        mesh = mesh[0]

    n_cp = (WING["num_y"] + 1) // 2
    surface = {
        "name": "wing", "mesh": mesh, "symmetry": True,
        "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
        "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
        "c_max_t": 0.303, "with_viscous": WING["with_viscous"],
        "with_wave": False, "twist_cp": np.zeros(n_cp),
        "thickness_cp": np.array(WING["thickness_cp"]),
        "fem_model_type": "tube",
        "E": WING["E"], "G": WING["G"],
        "yield": WING["yield_stress"], "mrho": WING["mrho"],
        "safety_factor": 1.5, "fem_origin": 0.35,
        "wing_weight_ratio": 2.0, "struct_weight_relief": False,
        "distributed_fuel_weight": False, "exact_failure_constraint": False,
    }

    prob = om.Problem(reports=False)
    indep = om.IndepVarComp()
    indep.add_output("v", val=FLIGHT["velocity"], units="m/s")
    indep.add_output("alpha", val=FLIGHT["alpha"], units="deg")
    indep.add_output("beta", val=0.0, units="deg")
    indep.add_output("Mach_number", val=FLIGHT["Mach_number"])
    indep.add_output("re", val=FLIGHT["re"], units="1/m")
    indep.add_output("rho", val=FLIGHT["rho"], units="kg/m**3")
    indep.add_output("CT", val=9.81e-6, units="1/s")
    indep.add_output("R", val=14.3e6, units="m")
    indep.add_output("W0", val=25000.0, units="kg")
    indep.add_output("speed_of_sound", val=295.07, units="m/s")
    indep.add_output("load_factor", val=1.0)
    indep.add_output("empty_cg", val=np.array([0.35, 0.0, 0.0]), units="m")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])

    prob.model.add_subsystem("wing", AerostructGeometry(surface=surface))
    prob.model.add_subsystem(
        "AS_point_0",
        AerostructPoint(surfaces=[surface]),
        promotes_inputs=["v", "alpha", "beta", "Mach_number", "re", "rho",
                         "CT", "R", "W0", "speed_of_sound", "empty_cg",
                         "load_factor"],
    )
    prob.model.connect("wing.local_stiff_transformed",
                       "AS_point_0.coupled.wing.local_stiff_transformed")
    prob.model.connect("wing.nodes", "AS_point_0.coupled.wing.nodes")
    prob.model.connect("wing.mesh", "AS_point_0.coupled.wing.mesh")
    prob.model.connect("wing.nodes", "AS_point_0.wing_perf.nodes")
    prob.model.connect("wing.cg_location", "AS_point_0.total_perf.wing_cg_location")
    prob.model.connect("wing.structural_mass",
                       "AS_point_0.total_perf.wing_structural_mass")
    prob.model.connect("wing.t_over_c", "AS_point_0.wing_perf.t_over_c")
    prob.model.connect("wing.radius", "AS_point_0.wing_perf.radius")
    prob.model.connect("wing.thickness", "AS_point_0.wing_perf.thickness")

    prob.setup()
    coupled = prob.model.AS_point_0.coupled
    newton = om.NewtonSolver()
    newton.options["maxiter"] = 20
    newton.options["atol"] = 1e-6
    newton.options["solve_subsystems"] = True
    coupled.nonlinear_solver = newton
    coupled.linear_solver = om.DirectSolver()

    prob.run_model()
    return float(prob.get_val("wing.structural_mass", units="kg")[0])


def run() -> dict:
    structural_mass_kg = run_oas()

    if not _AVY_PYTHON.exists():
        raise RuntimeError(
            f"{_AVY_PYTHON} not found -- run `bash scripts/setup-avy-venv.sh`."
        )
    wing_mass_lbm = structural_mass_kg * LBM_PER_KG
    proc = subprocess.run(
        [str(_AVY_PYTHON), str(_AVY_SCRIPT), str(wing_mass_lbm)],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=_REPO_ROOT,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"Lane A aviary stage failed:\n{tail}")

    metrics: dict[str, float] = {"structural_mass_kg": structural_mass_kg}
    for line in proc.stdout.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            try:
                metrics[key.strip()] = float(value)
            except ValueError:
                continue
    return metrics


if __name__ == "__main__":
    for key, val in run().items():
        print(f"{key}: {val:.4f}")
