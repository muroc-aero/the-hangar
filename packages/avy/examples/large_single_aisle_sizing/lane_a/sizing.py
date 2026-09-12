"""Lane A: raw Aviary Level 1 sizing of the large single aisle -- the reference.

Deliberately minimal: upstream aviary only, no hangar imports beyond
``shared``.

Run standalone (inside .venv-avy):
    .venv-avy/bin/python packages/avy/examples/large_single_aisle_sizing/lane_a/sizing.py
"""

from __future__ import annotations

import copy
import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import DECK, MAX_ITER, OPTIMIZER, TARGET_RANGE_NM  # noqa: E402


def run() -> dict:
    """Size the large single aisle at 2500 nmi on the default mission."""
    from openmdao.core.problem import _clear_problem_names
    from aviary.interface.run_aviary import run_aviary
    from aviary.variable_info.variables import Mission

    mission_mod = importlib.import_module(
        "aviary.models.missions.energy_state_default"
    )
    phase_info = copy.deepcopy(mission_mod.phase_info)
    phase_info["post_mission"]["constrain_range"] = True
    phase_info["post_mission"]["target_range"] = (TARGET_RANGE_NM, "nmi")

    old_cwd = os.getcwd()
    workdir = tempfile.mkdtemp(prefix="avy_lane_a_")
    os.chdir(workdir)
    try:
        _clear_problem_names()
        prob = run_aviary(
            DECK,
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
        "gross_mass_lbm": float(prob.get_val(Mission.GROSS_MASS, units="lbm")[0]),
        "total_fuel_mass_lbm": float(
            prob.get_val(Mission.TOTAL_FUEL_MASS, units="lbm")[0]
        ),
        "range_nmi": float(prob.get_val(Mission.RANGE, units="nmi")[0]),
        "final_time_min": float(prob.get_val(Mission.FINAL_TIME, units="min")[0]),
    }


if __name__ == "__main__":
    for key, val in run().items():
        print(f"{key}: {val:.4f}")
