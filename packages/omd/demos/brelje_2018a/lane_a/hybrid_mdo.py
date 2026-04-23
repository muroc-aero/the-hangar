"""Lane A: Brelje 2018a King Air series-hybrid MDO using hangar OCP factory.

Reproduces the Fig 5 MDO formulation (minimize fuel_burn + MTOW/100)
at a single grid point.  DVs, constraints, and bounds come verbatim
from upstream HybridTwin.py lines 372-418.

Usage:
    uv run python packages/omd/demos/brelje_2018a/lane_a/hybrid_mdo.py
    uv run python ... --range 500 --spec-energy 450
    uv run python ... --objective fuel|cost    (cost requires Stage 4)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import openmdao.api as om

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import (
    AIRCRAFT,
    DEFAULT_DESIGN_RANGE_NM,
    DEFAULT_SPEC_ENERGY_WHKG,
    DESIGN_VARIABLES,
    MISSION_BASE,
    SCALAR_CONSTRAINTS,
    VECTOR_CONSTRAINTS,
)

from hangar.omd.factories.ocp.builder import build_ocp_full_mission
from hangar.omd.factories.ocp.mission_values import _set_mission_values


def build_mdo_problem(
    design_range_nm: float,
    spec_energy_whkg: float,
    objective: str = "fuel",
) -> om.Problem:
    mission_params = dict(MISSION_BASE)
    mission_params["mission_range_NM"] = float(design_range_nm)
    mission_params["battery_specific_energy"] = float(spec_energy_whkg)
    # Starting guesses for per-phase hybridization (HybridTwin.py line 250).
    mission_params["cruise_hybridization"] = 0.05840626452293813
    # Avoid starting climb/descent hybridization at 0 (outside DV bounds).
    mission_params["climb_hybridization"] = 0.05
    mission_params["descent_hybridization"] = 0.05

    config = dict(
        aircraft_template=AIRCRAFT["template"],
        architecture=AIRCRAFT["architecture"],
        num_nodes=MISSION_BASE["num_nodes"],
        mission_params=mission_params,
        propulsion_overrides={"battery_specific_energy": float(spec_energy_whkg)},
    )
    if objective == "cost":
        config["include_cost_model"] = True  # implemented in Stage 4

    prob, metadata = build_ocp_full_mission(
        component_config=dict(config, _defer_setup=True),
        operating_points={},
    )

    num_nodes = MISSION_BASE["num_nodes"]
    for dv in DESIGN_VARIABLES:
        kwargs = {k: v for k, v in dv.items() if k != "name" and v is not None}
        prob.model.add_design_var(dv["name"], **kwargs)

    for c in SCALAR_CONSTRAINTS:
        kwargs = {k: v for k, v in c.items() if k != "name"}
        prob.model.add_constraint(c["name"], **kwargs)

    for c in VECTOR_CONSTRAINTS:
        kwargs = {k: v for k, v in c.items() if k != "name"}
        if "upper" in kwargs:
            kwargs["upper"] = kwargs["upper"] * np.ones(num_nodes)
        if "lower" in kwargs:
            kwargs["lower"] = kwargs["lower"] * np.ones(num_nodes)
        prob.model.add_constraint(c["name"], **kwargs)

    if objective == "fuel":
        prob.model.add_objective("mixed_objective")
    elif objective == "cost":
        prob.model.add_objective("doc_per_nmi")
    else:
        raise ValueError(f"Unknown objective '{objective}'")

    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["tol"] = 1e-6
    prob.driver.options["maxiter"] = 150

    prob.setup(check=False, mode="fwd")

    arch_info = metadata.get("architecture")
    _set_mission_values(
        prob,
        mission_params,
        metadata["phases"],
        num_nodes,
        metadata["is_hybrid"],
        metadata["mission_type"],
    )

    return prob


def run_mdo(design_range_nm: float, spec_energy_whkg: float, objective: str) -> dict:
    prob = build_mdo_problem(design_range_nm, spec_energy_whkg, objective)
    fail = prob.run_driver()
    outputs = {
        "objective": objective,
        "design_range_nm": design_range_nm,
        "spec_energy_whkg": spec_energy_whkg,
        "converged": not fail,
        "MTOW_kg": float(prob.get_val("ac|weights|MTOW", units="kg")[0]),
        "MTOW_lb": float(prob.get_val("ac|weights|MTOW", units="lbm")[0]),
        "fuel_burn_kg": float(prob.get_val("descent.fuel_used_final", units="kg")[0]),
        "fuel_burn_lb": float(prob.get_val("descent.fuel_used_final", units="lbm")[0]),
        "W_battery_kg": float(prob.get_val("ac|weights|W_battery", units="kg")[0]),
        "S_ref_m2": float(prob.get_val("ac|geom|wing|S_ref", units="m**2")[0]),
        "cruise_hybridization": float(prob.get_val("cruise.hybridization")[0]),
        "climb_hybridization": float(prob.get_val("climb.hybridization")[0]),
        "descent_hybridization": float(prob.get_val("descent.hybridization")[0]),
        "engine_rating_hp": float(prob.get_val("ac|propulsion|engine|rating", units="hp")[0]),
        "motor_rating_hp": float(prob.get_val("ac|propulsion|motor|rating", units="hp")[0]),
        "generator_rating_hp": float(prob.get_val("ac|propulsion|generator|rating", units="hp")[0]),
        "MTOW_margin_lb": float(prob.get_val("margins.MTOW_margin", units="lbm")[0]),
        "rotate_range_ft": float(prob.get_val("rotate.range_final", units="ft")[0]),
        "Vstall_kn": float(prob.get_val("v0v1.Vstall_eas", units="kn")[0]),
        "SOC_final": float(prob.get_val("descent.propmodel.batt1.SOC_final")[0]),
    }
    if objective == "fuel":
        outputs["mixed_objective_kg"] = float(
            prob.get_val("mixed_objective", units="kg")[0]
        )
    else:
        outputs["doc_per_nmi_usd"] = float(prob.get_val("doc_per_nmi")[0])
    outputs["fuel_mileage_lb_per_nmi"] = outputs["fuel_burn_lb"] / design_range_nm
    outputs["electric_percent"] = 100.0 * outputs["cruise_hybridization"]
    return outputs


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--range", type=float, default=DEFAULT_DESIGN_RANGE_NM)
    p.add_argument("--spec-energy", type=float, default=DEFAULT_SPEC_ENERGY_WHKG)
    p.add_argument("--objective", choices=["fuel", "cost"], default="fuel")
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    result = run_mdo(args.range, args.spec_energy, args.objective)
    print(json.dumps(result, indent=2))

    out_path = args.out
    if out_path is None:
        results_dir = Path(__file__).resolve().parent.parent / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        out_path = results_dir / f"lane_a_{args.objective}_r{int(args.range)}_e{int(args.spec_energy)}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nSaved -> {out_path}")
    return 0 if result["converged"] else 1


if __name__ == "__main__":
    sys.exit(main())
