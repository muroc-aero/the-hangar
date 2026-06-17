"""Lane A: native eVTOL MTOW sizing via the OpenMDAO library directly.

Builds the native evtolpy formulation (``hangar.omd.evt``) as a bare OpenMDAO
problem -- no omd plan pipeline -- and runs the MTOW fixed-point closure to a
sized takeoff mass. This is the "direct script" lane: the same components the
``evt/Sizing`` factory assembles, driven as a plain library.

The native model carries complex-step partials and a real (Newton) closure
solver, so unlike the legacy black box it yields **analytic total derivatives**
through the sizing loop. ``run_gradient`` demonstrates that headline capability.
"""

from __future__ import annotations

import json
import os
import sys

import openmdao.api as om

from hangar.omd.evt.builders import build_problem

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import CONFIG_PATH, SOLVER


def _build() -> tuple[om.Problem, dict]:
    """Build + set up the sized problem with config initial values applied."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = json.load(fh)

    prob, metadata = build_problem(config, mode="sizing", solver=SOLVER)
    # Native components declare complex-step partials; the vectors must be
    # complex-allocated for the Newton/derivative paths to work.
    prob.setup(force_alloc_complex=bool(metadata.get("force_alloc_complex")))
    for name, value in metadata["initial_values"].items():
        prob.set_val(name, value)
    return prob, metadata


def run() -> dict:
    """Size the eVTOL and return the key sized quantities."""
    prob, _ = _build()
    prob.run_model()

    return {
        "sized_mtow_kg": float(prob.get_val("sized_mtow_kg")[0]),
        "total_mission_energy_kw_hr": float(prob.get_val("total_mission_energy_kw_hr")[0]),
        "peak_power_kw": float(prob.get_val("peak_power_kw")[0]),
        "empty_mass_kg": float(prob.get_val("empty_mass_kg")[0]),
        "battery_mass_kg": float(prob.get_val("battery_mass_kg")[0]),
        "converged": float(prob.get_val("converged")[0]),
    }


def run_gradient() -> dict:
    """Analytic d(sized_MTOW)/d(payload) through the closure vs finite diff.

    The sizing loop is an implicit fixed point (MTOW closes against empty +
    payload + battery). The native model's complex-step partials plus the
    DirectSolver let OpenMDAO assemble the *total* derivative through that loop
    analytically -- something finite-differencing the black box can only
    approximate. We confirm it against a coarse forward difference.
    """
    prob, _ = _build()
    prob.run_model()

    of, wrt = "sized_mtow_kg", "payload_kg"
    totals = prob.compute_totals(of=[of], wrt=[wrt])
    analytic = float(totals[(of, wrt)][0, 0])

    # Coarse forward difference: re-solve at a perturbed payload.
    base_payload = float(prob.get_val(wrt)[0])
    step = 1.0  # kg
    m0 = float(prob.get_val(of)[0])
    prob.set_val(wrt, base_payload + step)
    prob.run_model()
    m1 = float(prob.get_val(of)[0])
    fd = (m1 - m0) / step

    return {"analytic": analytic, "fd": fd, "payload_kg": base_payload}


if __name__ == "__main__":
    print(json.dumps({"sizing": run(), "gradient": run_gradient()}, indent=2))
