#!/usr/bin/env python
"""Generate golden reference values for stability derivatives.

Uses the omd aero factory to produce deterministic reference values.
Run with fixed thread counts for reproducibility:

    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
        python packages/omd/tests/golden/generate_golden_stability.py
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import openmdao
from hangar.omd.factories.oas_aero import build_oas_aeropoint
from hangar.omd.stability import compute_stability


def main():
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 7,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "CD0": 0.01,
            "with_viscous": True,
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)
    prob.setup()
    prob.run_model()

    result = compute_stability(prob, metadata)
    prob.cleanup()

    golden = {
        "description": "Golden reference for stability derivatives (aero-only, rect wing)",
        "generated_at": "2026-04-06",
        "reproducibility": {
            "python": platform.python_version(),
            "openmdao": openmdao.__version__,
            "numpy": np.__version__,
        },
        "surface": {
            "wing_type": "rect",
            "span": 10.0,
            "root_chord": 1.0,
            "num_x": 2,
            "num_y": 7,
        },
        "flight_conditions": {
            "velocity": 248.136,
            "alpha": 5.0,
            "Mach_number": 0.84,
            "reynolds_number": 1e6,
            "density": 0.38,
        },
        "delta_alpha": 1e-4,
        "expected": result,
        "tolerances": {
            "CL_alpha_per_rad": {"rel": 0.005},
            "CM_alpha_per_rad": {"rel": 0.01},
            "static_margin": {"abs": 0.005},
        },
    }

    out = Path(__file__).parent / "golden_stability.json"
    out.write_text(json.dumps(golden, indent=2) + "\n")
    print(f"Wrote {out}")

    print(f"\nalpha = {result['alpha_deg']} deg")
    print(f"CL = {result['CL']:.6f}")
    print(f"CM = {result['CM']:.6f}")
    print(f"CL_alpha = {result['CL_alpha_per_rad']:.4f} /rad")
    print(f"CM_alpha = {result['CM_alpha_per_rad']:.4f} /rad")
    sm = result['static_margin']
    print(f"Static margin = {sm:.4f}" if sm is not None else "Static margin = N/A")


if __name__ == "__main__":
    main()
