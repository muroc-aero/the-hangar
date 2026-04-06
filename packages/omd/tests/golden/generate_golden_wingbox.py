#!/usr/bin/env python
"""Generate golden reference values for wingbox FEM aerostruct analysis.

Uses the omd factory to produce deterministic reference values.
Run with fixed thread counts for reproducibility:

    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
        python packages/omd/tests/golden/generate_golden_wingbox.py
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import openmdao
from hangar.omd.factories.oas import build_oas_aerostruct


def main():
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "CRM",
            "num_x": 2,
            "num_y": 7,
            "symmetry": True,
            "fem_model_type": "wingbox",
            "E": 73.1e9,
            "G": 28.0e9,
            "yield_stress": 324.0e6,
            "mrho": 2780.0,
            "safety_factor": 1.5,
            "spar_thickness_cp": [0.004, 0.005, 0.005, 0.008],
            "skin_thickness_cp": [0.005, 0.010, 0.015, 0.020],
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
        "W0": 25000.0,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    prob.setup()
    prob.run_model()

    CL = float(prob.get_val("AS_point_0.CL")[0])
    CD = float(prob.get_val("AS_point_0.CD")[0])
    failure = float(np.max(prob.get_val("AS_point_0.wing_perf.failure")))
    mass = float(np.sum(prob.get_val("wing.structural_mass")))
    vm = prob.get_val("AS_point_0.wing_perf.vonmises")
    vm_peak_mpa = float(np.max(vm)) / 1e6

    prob.cleanup()

    golden = {
        "description": "Golden reference for wingbox FEM aerostruct analysis (CRM wing)",
        "generated_at": "2026-04-06",
        "reproducibility": {
            "python": platform.python_version(),
            "openmdao": openmdao.__version__,
            "numpy": np.__version__,
        },
        "surface": {
            "wing_type": "CRM",
            "num_x": 2,
            "num_y": 7,
            "fem_model_type": "wingbox",
            "E": 73.1e9,
            "G": 28.0e9,
            "yield_stress": 324.0e6,
            "mrho": 2780.0,
            "safety_factor": 1.5,
        },
        "flight_conditions": {
            "velocity": 248.136,
            "alpha": 5.0,
            "Mach_number": 0.84,
            "reynolds_number": 1e6,
            "density": 0.38,
            "W0": 25000.0,
        },
        "expected": {
            "CL": round(CL, 6),
            "CD": round(CD, 6),
            "failure": round(failure, 6),
            "structural_mass_kg": round(mass, 2),
            "vonmises_peak_MPa": round(vm_peak_mpa, 2),
        },
        "tolerances": {
            "CL": {"rel": 0.005},
            "CD": {"rel": 0.005},
            "failure": {"abs": 0.05},
            "structural_mass_kg": {"rel": 0.005},
            "vonmises_peak_MPa": {"rel": 0.01},
        },
    }

    out = Path(__file__).parent / "golden_wingbox.json"
    out.write_text(json.dumps(golden, indent=2) + "\n")
    print(f"Wrote {out}")

    print(f"\nCL = {CL:.6f}")
    print(f"CD = {CD:.6f}")
    print(f"failure = {failure:.6f}")
    print(f"structural_mass = {mass:.2f} kg")
    print(f"vonmises_peak = {vm_peak_mpa:.2f} MPa")


if __name__ == "__main__":
    main()
