"""Lane A stage 2: raw Aviary sizing with an overridden wing mass.

Runs in .venv-avy (raw upstream aviary only). Takes the wing mass in lbm
as argv[1], sets it on the deck's AviaryValues -- Aviary's
override_aviary_vars then renames the FLOPS wing-mass output away and the
deck value feeds every consumer -- and sizes on the default energy_state
mission (1906 nmi). Prints ``key: value`` metrics for the orchestrator.

    .venv-avy/bin/python avy_override_sizing.py 12634.4
"""

from __future__ import annotations

import copy
import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import DECK, MAX_ITER, OPTIMIZER, OVERRIDE_VAR, PHASE_INFO_MODULE  # noqa: E402


def run(wing_mass_lbm: float) -> dict:
    from openmdao.core.problem import _clear_problem_names

    from aviary.interface.run_aviary import run_aviary
    from aviary.utils.process_input_decks import create_vehicle
    from aviary.variable_info.variables import Aircraft, Mission

    phase_info = copy.deepcopy(importlib.import_module(PHASE_INFO_MODULE).phase_info)

    aircraft_values, _guesses = create_vehicle(DECK)
    assert OVERRIDE_VAR == Aircraft.Wing.MASS
    aircraft_values.set_val(Aircraft.Wing.MASS, wing_mass_lbm, "lbm")

    old_cwd = os.getcwd()
    workdir = tempfile.mkdtemp(prefix="avy_lane_a_override_")
    os.chdir(workdir)
    try:
        _clear_problem_names()
        prob = run_aviary(
            aircraft_values,
            phase_info,
            optimizer=OPTIMIZER,
            max_iter=MAX_ITER,
            make_plots=False,
            verbosity=0,
        )
    finally:
        os.chdir(old_cwd)

    assert prob.result.success, "Lane A optimizer did not converge"

    return {
        "wing_mass_lbm": float(prob.get_val(Aircraft.Wing.MASS, units="lbm")[0]),
        "gross_mass_lbm": float(prob.get_val(Mission.GROSS_MASS, units="lbm")[0]),
        "total_fuel_mass_lbm": float(
            prob.get_val(Mission.TOTAL_FUEL_MASS, units="lbm")[0]
        ),
        "range_nmi": float(prob.get_val(Mission.RANGE, units="nmi")[0]),
        "final_time_min": float(prob.get_val(Mission.FINAL_TIME, units="min")[0]),
    }


if __name__ == "__main__":
    for key, val in run(float(sys.argv[1])).items():
        print(f"{key}: {val:.6f}")
