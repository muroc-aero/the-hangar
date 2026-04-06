#!/usr/bin/env python
"""Generate golden reference values for drag polar sweep.

Uses the omd aero factory to produce deterministic reference values.
Run with fixed thread counts for reproducibility:

    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
        python packages/omd/tests/golden/generate_golden_polar.py
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import openmdao
from hangar.omd.factories.oas_aero import build_oas_aeropoint


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
        "alpha": 0.0,
        "Mach_number": 0.84,
        "re": 1e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)
    prob.setup()

    alphas = [-2.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    CLs, CDs, CMs = [], [], []

    for a in alphas:
        prob.set_val("alpha", a, units="deg")
        prob.run_model()
        CLs.append(float(np.asarray(prob.get_val("aero_point_0.CL")).ravel()[0]))
        CDs.append(float(np.asarray(prob.get_val("aero_point_0.CD")).ravel()[0]))
        cm = np.asarray(prob.get_val("aero_point_0.CM")).ravel()
        CMs.append(float(cm[1]) if len(cm) > 1 else float(cm[0]))

    prob.cleanup()

    LoDs = [cl / cd if cd > 0 else None for cl, cd in zip(CLs, CDs)]
    valid_LoDs = [(i, v) for i, v in enumerate(LoDs) if v is not None]
    best_idx, best_LoD = max(valid_LoDs, key=lambda x: x[1])

    golden = {
        "description": "Golden reference for drag polar sweep (aero-only, rect wing)",
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
            "CD0": 0.01,
            "with_viscous": True,
        },
        "flight_conditions": {
            "velocity": 248.136,
            "Mach_number": 0.84,
            "reynolds_number": 1e6,
            "density": 0.38,
        },
        "alpha_deg": [round(a, 4) for a in alphas],
        "expected": {
            "CL": [round(v, 6) for v in CLs],
            "CD": [round(v, 6) for v in CDs],
            "CM": [round(v, 6) for v in CMs],
            "L_over_D": [round(v, 4) if v is not None else None for v in LoDs],
            "best_L_over_D": {
                "index": best_idx,
                "alpha_deg": round(float(alphas[best_idx]), 4),
                "CL": round(CLs[best_idx], 6),
                "CD": round(CDs[best_idx], 6),
                "L_over_D": round(best_LoD, 4),
            },
        },
        "tolerances": {
            "CL": {"rel": 0.005},
            "CD": {"rel": 0.005},
            "L_over_D": {"rel": 0.01},
        },
    }

    out = Path(__file__).parent / "golden_polar.json"
    out.write_text(json.dumps(golden, indent=2) + "\n")
    print(f"Wrote {out}")

    print(f"\nBest L/D: {best_LoD:.2f} at alpha={alphas[best_idx]:.1f} deg")
    for a, cl, cd, ld in zip(alphas, CLs, CDs, LoDs):
        ld_str = f"{ld:.2f}" if ld is not None else "N/A"
        print(f"  alpha={a:6.1f}  CL={cl:8.5f}  CD={cd:8.6f}  L/D={ld_str}")


if __name__ == "__main__":
    main()
