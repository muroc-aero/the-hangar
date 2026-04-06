#!/usr/bin/env python3
"""Generate all YAML plan directories for the regional wing optimization study.

Study: Aerostructural optimization of a 28m-span regional aircraft wing
       for minimum fuel burn with structural constraints.

Aircraft class: E190-type regional jet
  - 28m span, swept tapered wing
  - Al 7075-T6 tube FEM structure
  - Cruise at M0.78, FL370
  - 2000 nmi design range

Cases generated:
  01-baseline          -- analysis at initial geometry (num_y=21)
  02-mesh-ny{N}        -- mesh convergence study (N=7,11,15,21,25)
  03-opt-fuelburn      -- main fuel burn optimization (num_y=21)
  04-sens-mach-{M}     -- Mach sensitivity (0.72, 0.75, 0.81, 0.84)
  04-sens-w0-{W}       -- weight sensitivity (35t, 45t, 50t)
  04-sens-range-{R}    -- range sensitivity (1500, 2500, 3000 nmi)
  05-robust-sf-{SF}    -- safety factor robustness (1.25, 2.0)
  05-robust-lf25       -- 2.5g maneuver load case
  05-robust-init-wash  -- alternate initial twist (strong washout)
  05-robust-init-thick -- alternate initial thickness (uniform heavy)
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml


STUDY_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Baseline wing configuration (E190-class regional jet)
# ---------------------------------------------------------------------------

BASE_METADATA = {
    "name": "Regional Wing Optimization",
    "version": 1,
}

BASE_SURFACE = {
    "name": "wing",
    "wing_type": "rect",
    "num_x": 3,
    "num_y": 21,
    "span": 28.0,
    "root_chord": 4.2,
    "symmetry": True,
    "sweep": 24.0,
    "dihedral": 5.0,
    "taper": 0.32,
    "span_cos_spacing": 1.0,
    # Structure -- Al 7075-T6, tube FEM
    "fem_model_type": "tube",
    "E": 71.7e9,
    "G": 26.9e9,
    "yield_stress": 503.0e6,
    "mrho": 2810.0,
    "safety_factor": 1.5,
    "fem_origin": 0.35,
    "wing_weight_ratio": 2.0,
    "struct_weight_relief": False,
    "distributed_fuel_weight": True,
    "exact_failure_constraint": False,
    # Aero
    "with_viscous": True,
    "with_wave": True,
    "S_ref_type": "wetted",
    "CL0": 0.0,
    "CD0": 0.0078,
    "k_lam": 0.05,
    "t_over_c_cp": [0.12, 0.12, 0.11, 0.10, 0.09],
    "c_max_t": 0.303,
    # Initial structural sizing (root to tip)
    "thickness_cp": [0.015, 0.015, 0.012, 0.010, 0.008],
    "twist_cp": [4.0, 3.0, 2.0, 0.5, -1.0],
}

BASE_OPERATING_POINTS = {
    "velocity": 230.15,
    "alpha": 3.0,
    "Mach_number": 0.78,
    "re": 5.5e6,
    "rho": 0.3639,
    "CT": 9.8e-6,
    "R": 3.704e6,
    "W0": 40000.0,
    "speed_of_sound": 295.07,
    "load_factor": 1.0,
    "empty_cg": [14.0, 0.0, -1.0],
}

BASE_SOLVERS = {
    "nonlinear": {
        "type": "NonlinearBlockGS",
        "options": {
            "maxiter": 100,
            "atol": 1.0e-7,
            "rtol": 1.0e-30,
            "use_aitken": True,
            "err_on_non_converge": False,
        },
    },
    "linear": {
        "type": "DirectSolver",
        "options": {},
    },
}

BASE_OPTIMIZATION = {
    "design_variables": [
        {
            "name": "wing.twist_cp",
            "lower": -10.0,
            "upper": 15.0,
            "scaler": 0.1,
            "units": "deg",
            "traces_to": ["REQ-AERO-01"],
        },
        {
            "name": "wing.thickness_cp",
            "lower": 0.002,
            "upper": 0.05,
            "scaler": 100.0,
            "units": "m",
            "traces_to": ["REQ-STRUCT-01"],
        },
        {
            "name": "alpha",
            "lower": -2.0,
            "upper": 8.0,
            "scaler": 0.1,
            "units": "deg",
            "traces_to": ["REQ-AERO-01"],
        },
    ],
    "constraints": [
        {
            "name": "AS_point_0.wing_perf.failure",
            "upper": 0.0,
            "scaler": 1.0,
        },
        {
            "name": "AS_point_0.L_equals_W",
            "equals": 0.0,
            "scaler": 1.0,
        },
    ],
    "objective": {
        "name": "AS_point_0.fuelburn",
        "scaler": 1.0e-5,
        "units": "kg",
    },
    "optimizer": {
        "type": "SLSQP",
        "options": {
            "maxiter": 300,
            "ftol": 1.0e-9,
            "timeout_seconds": 180,
        },
    },
}

BASE_REQUIREMENTS = [
    {
        "id": "REQ-PERF-01",
        "text": "Minimize fuel burn over 2000 nmi design mission",
        "type": "objective",
        "traces_to": ["AS_point_0.fuelburn"],
    },
    {
        "id": "REQ-STRUCT-01",
        "text": "No structural failure under cruise loads (failure <= 0)",
        "type": "structural",
        "traces_to": ["AS_point_0.wing_perf.failure"],
    },
    {
        "id": "REQ-STRUCT-02",
        "text": "Structural integrity under 2.5g maneuver with safety factor",
        "type": "structural",
        "traces_to": ["AS_point_0.wing_perf.failure"],
    },
    {
        "id": "REQ-AERO-01",
        "text": "Trimmed cruise flight (L = W)",
        "type": "constraint",
        "traces_to": ["AS_point_0.L_equals_W"],
    },
    {
        "id": "REQ-MANU-01",
        "text": "Minimum tube wall thickness >= 2 mm",
        "type": "constraint",
        "traces_to": ["wing.thickness_cp"],
    },
]


# ---------------------------------------------------------------------------
# Plan writer
# ---------------------------------------------------------------------------


def write_plan(
    plan_dir: Path,
    plan_id: str,
    name: str,
    surface_overrides: dict | None = None,
    op_overrides: dict | None = None,
    solver_overrides: dict | None = None,
    optimization: dict | None = None,
    requirements: list | None = None,
    decisions: list | None = None,
) -> None:
    """Write a complete plan directory from base config + overrides."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "components").mkdir(exist_ok=True)

    # Metadata
    meta = {**BASE_METADATA, "id": plan_id, "name": name}
    _write_yaml(plan_dir / "metadata.yaml", meta)

    # Surface
    surface = copy.deepcopy(BASE_SURFACE)
    if surface_overrides:
        surface.update(surface_overrides)
    comp = {
        "id": "wing",
        "type": "oas/AerostructPoint",
        "config": {"surfaces": [surface]},
    }
    _write_yaml(plan_dir / "components" / "wing.yaml", comp)

    # Operating points
    ops = copy.deepcopy(BASE_OPERATING_POINTS)
    if op_overrides:
        ops.update(op_overrides)
    _write_yaml(plan_dir / "operating_points.yaml", ops)

    # Solvers
    solvers = copy.deepcopy(BASE_SOLVERS)
    if solver_overrides:
        _deep_update(solvers, solver_overrides)
    _write_yaml(plan_dir / "solvers.yaml", solvers)

    # Optimization (optional -- analysis-only plans omit this)
    if optimization is not None:
        _write_yaml(plan_dir / "optimization.yaml", optimization)

    # Requirements (optional)
    if requirements is not None:
        _write_yaml(plan_dir / "requirements.yaml", {"requirements": requirements})

    # Decisions (optional)
    if decisions is not None:
        _write_yaml(plan_dir / "decisions.yaml", {"decisions": decisions})


def _write_yaml(path: Path, data: Any) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, width=120)


def _deep_update(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


# ---------------------------------------------------------------------------
# Case generators
# ---------------------------------------------------------------------------


def gen_baseline() -> None:
    """01 -- Baseline analysis at initial geometry."""
    write_plan(
        STUDY_DIR / "01-baseline",
        plan_id="regional-wing-baseline",
        name="Baseline analysis -- initial geometry, no optimization",
        decisions=[
            {
                "id": "DEC-001",
                "decision": "28m span rectangular planform with sweep/taper/dihedral transforms",
                "reason": "Matches E190-class regional jet geometry",
                "stage": "Setup",
            },
            {
                "id": "DEC-002",
                "decision": "Al 7075-T6 tube FEM with 5 control points",
                "reason": "Reliable convergence, adequate fidelity for trade studies",
                "stage": "Setup",
            },
        ],
        requirements=BASE_REQUIREMENTS,
    )


def gen_mesh_convergence() -> None:
    """02 -- Mesh convergence study at 5 spanwise resolutions."""
    for ny in [7, 11, 15, 21, 25]:
        # Scale twist/thickness CPs to match half-span node count
        n_cp = (ny + 1) // 2
        # Interpolate from 5-CP base to n_cp
        import numpy as np
        base_twist = np.array([4.0, 3.0, 2.0, 0.5, -1.0])
        base_thick = np.array([0.015, 0.015, 0.012, 0.010, 0.008])
        base_toc = np.array([0.12, 0.12, 0.11, 0.10, 0.09])
        xi_base = np.linspace(0, 1, len(base_twist))
        xi_new = np.linspace(0, 1, n_cp)
        twist_cp = [float(x) for x in np.interp(xi_new, xi_base, base_twist).round(4)]
        thick_cp = [float(x) for x in np.interp(xi_new, xi_base, base_thick).round(6)]
        toc_cp = [float(x) for x in np.interp(xi_new, xi_base, base_toc).round(4)]

        write_plan(
            STUDY_DIR / f"02-mesh-ny{ny:02d}",
            plan_id=f"regional-wing-mesh-ny{ny}",
            name=f"Mesh convergence -- num_y={ny} ({n_cp} CPs)",
            surface_overrides={
                "num_y": ny,
                "twist_cp": twist_cp,
                "thickness_cp": thick_cp,
                "t_over_c_cp": toc_cp,
            },
        )


def gen_main_optimization() -> None:
    """03 -- Main fuel burn optimization at publication fidelity."""
    write_plan(
        STUDY_DIR / "03-opt-fuelburn",
        plan_id="regional-wing-opt-fuelburn",
        name="Fuel burn optimization -- num_y=21, SLSQP, 300 iter",
        optimization=BASE_OPTIMIZATION,
        requirements=BASE_REQUIREMENTS,
        decisions=[
            {
                "id": "DEC-OPT-01",
                "decision": "Objective is fuel burn (Breguet range equation)",
                "reason": "Direct measure of mission efficiency, accounts for aero and structural weight",
                "stage": "Optimization",
            },
            {
                "id": "DEC-OPT-02",
                "decision": "DVs: twist (5 CP), thickness (5 CP), alpha",
                "reason": "Twist controls spanwise lift distribution, thickness sizes structure, alpha trims",
                "stage": "Optimization",
            },
            {
                "id": "DEC-OPT-03",
                "decision": "SLSQP with 300 iterations and ftol=1e-9",
                "reason": "Gradient-based optimizer suitable for smooth VLM+FEM, tight tolerance for convergence",
                "stage": "Optimization",
            },
        ],
    )


def gen_mach_sensitivity() -> None:
    """04 -- Mach number sensitivity (off-design cruise speeds)."""
    # ISA conditions at FL370 for each Mach
    a = 295.07
    for mach in [0.72, 0.75, 0.81, 0.84]:
        v = mach * a
        tag = str(mach).replace(".", "")
        write_plan(
            STUDY_DIR / f"04-sens-mach-{tag}",
            plan_id=f"regional-wing-sens-mach-{tag}",
            name=f"Mach sensitivity -- M={mach}",
            surface_overrides={"num_y": 15},
            op_overrides={"Mach_number": mach, "velocity": round(v, 2)},
            optimization=_sens_optimization(),
        )


def gen_weight_sensitivity() -> None:
    """04 -- Gross weight sensitivity."""
    for w0 in [35000, 45000, 50000]:
        tag = f"{w0 // 1000}k"
        write_plan(
            STUDY_DIR / f"04-sens-w0-{tag}",
            plan_id=f"regional-wing-sens-w0-{tag}",
            name=f"Weight sensitivity -- W0={w0} kg",
            surface_overrides={"num_y": 15},
            op_overrides={"W0": float(w0)},
            optimization=_sens_optimization(),
        )


def gen_range_sensitivity() -> None:
    """04 -- Design range sensitivity."""
    for r_nmi in [1500, 2500, 3000]:
        r_m = r_nmi * 1852.0
        write_plan(
            STUDY_DIR / f"04-sens-range-{r_nmi}",
            plan_id=f"regional-wing-sens-range-{r_nmi}",
            name=f"Range sensitivity -- R={r_nmi} nmi",
            surface_overrides={"num_y": 15},
            op_overrides={"R": r_m},
            optimization=_sens_optimization(),
        )


def gen_robustness_sf() -> None:
    """05 -- Safety factor robustness."""
    for sf in [1.25, 2.0]:
        tag = str(sf).replace(".", "")
        write_plan(
            STUDY_DIR / f"05-robust-sf-{tag}",
            plan_id=f"regional-wing-robust-sf-{tag}",
            name=f"Robustness -- safety_factor={sf}",
            surface_overrides={"safety_factor": sf},
            optimization=BASE_OPTIMIZATION,
        )


def gen_robustness_maneuver() -> None:
    """05 -- 2.5g maneuver load case."""
    write_plan(
        STUDY_DIR / f"05-robust-lf25",
        plan_id="regional-wing-robust-lf25",
        name="Robustness -- 2.5g maneuver load",
        op_overrides={"load_factor": 2.5},
        optimization=BASE_OPTIMIZATION,
    )


def gen_robustness_initial_conditions() -> None:
    """05 -- Alternate initial conditions to test convergence robustness."""
    # Strong washout initial twist
    write_plan(
        STUDY_DIR / "05-robust-init-wash",
        plan_id="regional-wing-robust-init-wash",
        name="Robustness -- strong washout initial twist",
        surface_overrides={
            "twist_cp": [8.0, 5.0, 2.0, -2.0, -5.0],
        },
        optimization=BASE_OPTIMIZATION,
    )
    # Uniform heavy initial thickness
    write_plan(
        STUDY_DIR / "05-robust-init-thick",
        plan_id="regional-wing-robust-init-thick",
        name="Robustness -- uniform heavy initial thickness",
        surface_overrides={
            "thickness_cp": [0.03, 0.03, 0.03, 0.03, 0.03],
        },
        optimization=BASE_OPTIMIZATION,
    )


def _sens_optimization() -> dict:
    """Optimization config for sensitivity studies (num_y=15, fewer iters)."""
    opt = copy.deepcopy(BASE_OPTIMIZATION)
    opt["optimizer"]["options"]["maxiter"] = 200
    opt["optimizer"]["options"]["timeout_seconds"] = 120
    return opt


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Generating regional wing optimization study plans...")
    print(f"  Study directory: {STUDY_DIR}")

    gen_baseline()
    print("  [OK] 01-baseline")

    gen_mesh_convergence()
    print("  [OK] 02-mesh-ny{07,11,15,21,25}")

    gen_main_optimization()
    print("  [OK] 03-opt-fuelburn")

    gen_mach_sensitivity()
    print("  [OK] 04-sens-mach-{072,075,081,084}")

    gen_weight_sensitivity()
    print("  [OK] 04-sens-w0-{35k,45k,50k}")

    gen_range_sensitivity()
    print("  [OK] 04-sens-range-{1500,2500,3000}")

    gen_robustness_sf()
    print("  [OK] 05-robust-sf-{125,20}")

    gen_robustness_maneuver()
    print("  [OK] 05-robust-lf25")

    gen_robustness_initial_conditions()
    print("  [OK] 05-robust-init-{wash,thick}")

    # Count total
    dirs = sorted(d for d in STUDY_DIR.iterdir() if d.is_dir())
    print(f"\n  Total: {len(dirs)} plan directories generated")
    for d in dirs:
        print(f"    {d.name}/")


if __name__ == "__main__":
    main()
