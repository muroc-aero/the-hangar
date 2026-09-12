"""Lane A: raw Aviary BWB sizing on the fixed-profile benchmark mission.

Deliberately minimal: upstream aviary only, no hangar imports beyond
``shared``. The mission is the upstream BWB benchmark phase_info with the
same fixed-profile adaptation the 'bwb_fixed' mission template applies --
duplicated here inline because Lane A must not import hangar code; the
A-vs-B parity test is what proves the two constructions are identical.

Run standalone (inside .venv-avy):
    .venv-avy/bin/python packages/avy/examples/bwb_sizing/lane_a/sizing.py
"""

from __future__ import annotations

import copy
import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import (  # noqa: E402
    CLIMB_ALT_FINAL_FT,
    CLIMB_MACH_FINAL,
    DECK,
    MAX_ITER,
    OPTIMIZER,
)


def run() -> dict:
    """Size the BWB on the fixed-profile 7750 nmi mission; return metrics."""
    from openmdao.core.problem import _clear_problem_names
    from aviary.interface.run_aviary import run_aviary
    from aviary.variable_info.variables import Mission

    bench = importlib.import_module(
        "aviary.validation_cases.benchmark_tests.test_bwb_FwFm"
    )
    phase_info = copy.deepcopy(bench.phase_info)
    for phase in ("climb", "cruise", "descent"):
        phase_info[phase]["user_options"]["mach_optimize"] = False
        phase_info[phase]["user_options"]["altitude_optimize"] = False
    climb = phase_info["climb"]["user_options"]
    climb["mach_final"] = (CLIMB_MACH_FINAL, "unitless")
    climb["altitude_final"] = (CLIMB_ALT_FINAL_FT, "ft")

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
        "operating_mass_lbm": float(
            prob.get_val(Mission.OPERATING_MASS, units="lbm")[0]
        ),
        "range_nmi": float(prob.get_val(Mission.RANGE, units="nmi")[0]),
        "final_time_min": float(prob.get_val(Mission.FINAL_TIME, units="min")[0]),
    }


if __name__ == "__main__":
    for key, val in run().items():
        print(f"{key}: {val:.4f}")
