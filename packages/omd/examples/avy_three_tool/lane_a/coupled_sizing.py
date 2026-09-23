"""Lane A: raw Aviary level-2 sizing with an OAS wingbox and a pyCycle engine.

The oracle for the three-tool composition, without the omd factory:
upstream's ``OASWingMassBuilder`` driven exactly as its
``run_OAS_wing_mass_example.py`` does (the post-``setup()`` ``set_val``
block, values verbatim, as in the per-tool ``single_aisle_oas_wing`` Lane
A), plus the pyCycle HBTF deck handed to ``load_external_subsystems`` as
an in-memory ``EngineDeck``. ``hangar.omd.pyc.aviary_deck`` is the pyCycle
tool's Aviary output format (a sweep tabulated the way Aviary reads decks),
the way ``hangar.omd.pyc.surrogate`` is pyCycle's deck facility for the
OpenConcept cases -- pyCycle itself has neither.

Run standalone (from the workspace venv):
    uv run python packages/omd/examples/avy_three_tool/lane_a/coupled_sizing.py
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import DECK, ENGINE_DECK, MAX_ITER, OPTIMIZER, PHASE_INFO_MODULE  # noqa: E402


def run() -> dict:
    """Three-tool coupled sizing; return headline metrics."""
    import importlib

    from openmdao.core.problem import _clear_problem_names

    import aviary.api as av
    from aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_builder import (
        OASWingMassBuilder,
    )
    from aviary.utils.process_input_decks import create_vehicle
    from aviary.variable_info.variables import Aircraft, Mission

    from hangar.omd.pyc.aviary_deck import build_aviary_engine_deck

    phase_info = copy.deepcopy(importlib.import_module(PHASE_INFO_MODULE).phase_info)
    aircraft, _guesses = create_vehicle(DECK)
    engine, engine_info = build_aviary_engine_deck(
        ENGINE_DECK["provider"], ENGINE_DECK["config"], aircraft
    )

    old_cwd = os.getcwd()
    workdir = tempfile.mkdtemp(prefix="avy_lane_a_three_tool_")
    os.chdir(workdir)
    try:
        _clear_problem_names()
        prob = av.AviaryProblem(reports=False)
        prob.load_inputs(aircraft, phase_info, verbosity=0)
        prob.load_external_subsystems([engine, OASWingMassBuilder()], verbosity=0)
        prob.check_and_preprocess_inputs(verbosity=0)
        prob.build_model(verbosity=0)
        prob.add_driver(optimizer=OPTIMIZER, max_iter=MAX_ITER, verbosity=0)
        prob.add_design_variables(verbosity=0)
        prob.add_objective(verbosity=0)
        prob.setup()

        # The upstream example's OAS input block, values verbatim.
        OAS_sys = 'pre_mission.wing_mass.aerostructures.'
        # fmt: off
        box_x = np.array([
            0.1, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.2, 0.21, 0.22,
            0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29, 0.3, 0.31, 0.32, 0.33, 0.34, 0.35,
            0.36, 0.37, 0.38, 0.39, 0.4, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47, 0.48,
            0.49, 0.5, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.6,
        ])
        box_upper_y = np.array([
            0.0447, 0.046, 0.0472, 0.0484, 0.0495, 0.0505, 0.0514, 0.0523, 0.0531, 0.0538,
            0.0545, 0.0551, 0.0557, 0.0563, 0.0568, 0.0573, 0.0577, 0.0581, 0.0585, 0.0588,
            0.0591, 0.0593, 0.0595, 0.0597, 0.0599, 0.06, 0.0601, 0.0602, 0.0602, 0.0602,
            0.0602, 0.0602, 0.0601, 0.06, 0.0599, 0.0598, 0.0596, 0.0594, 0.0592, 0.0589,
            0.0586, 0.0583, 0.058, 0.0576, 0.0572, 0.0568, 0.0563, 0.0558, 0.0553, 0.0547,
            0.0541,
        ])
        box_lower_y = np.array([
            -0.0447, -0.046, -0.0473, -0.0485, -0.0496, -0.0506, -0.0515, -0.0524, -0.0532,
            -0.054, -0.0547, -0.0554, -0.056, -0.0565, -0.057, -0.0575, -0.0579, -0.0583,
            -0.0586, -0.0589, -0.0592, -0.0594, -0.0595, -0.0596, -0.0597, -0.0598, -0.0598,
            -0.0598, -0.0598, -0.0597, -0.0596, -0.0594, -0.0592, -0.0589, -0.0586, -0.0582,
            -0.0578, -0.0573, -0.0567, -0.0561, -0.0554, -0.0546, -0.0538, -0.0529, -0.0519,
            -0.0509, -0.0497, -0.0485, -0.0472, -0.0458, -0.0444,
        ])
        # fmt: on
        prob.set_val(OAS_sys + 'box_upper_x', box_x, units='unitless')
        prob.set_val(OAS_sys + 'box_lower_x', box_x, units='unitless')
        prob.set_val(OAS_sys + 'box_upper_y', box_upper_y, units='unitless')
        prob.set_val(OAS_sys + 'box_lower_y', box_lower_y, units='unitless')
        prob.set_val(OAS_sys + 'twist_cp', np.array([-6.0, -6.0, -4.0, 0.0]), units='deg')
        prob.set_val(
            OAS_sys + 'spar_thickness_cp', np.array([0.004, 0.005, 0.008, 0.01]), units='m'
        )
        prob.set_val(
            OAS_sys + 'skin_thickness_cp', np.array([0.005, 0.01, 0.015, 0.025]), units='m'
        )
        prob.set_val(
            OAS_sys + 't_over_c_cp', np.array([0.08, 0.08, 0.10, 0.08]), units='unitless'
        )
        prob.set_val(OAS_sys + 'airfoil_t_over_c', 0.12, units='unitless')
        prob.set_val(OAS_sys + 'fuel', 40044.0, units='lbm')
        prob.set_val(OAS_sys + 'fuel_reserve', 3000.0, units='lbm')
        prob.set_val(OAS_sys + 'CD0', 0.0078, units='unitless')
        prob.set_val(OAS_sys + 'cruise_Mach', 0.785, units='unitless')
        prob.set_val(OAS_sys + 'cruise_altitude', 11303.682962301647, units='m')
        prob.set_val(OAS_sys + 'cruise_range', 3500, units='nmi')
        prob.set_val(OAS_sys + 'cruise_SFC', 0.53 / 3600, units='1/s')
        prob.set_val(OAS_sys + 'engine_mass', 7400, units='lbm')
        prob.set_val(OAS_sys + 'engine_location', np.array([25, -10.0, 0.0]), units='m')

        prob.run_aviary_problem(make_plots=False)
    finally:
        os.chdir(old_cwd)

    assert prob.result.success, "Lane A optimizer did not converge"

    return {
        "gross_mass_lbm": float(prob.get_val(Mission.GROSS_MASS, units="lbm")[0]),
        "total_fuel_mass_lbm": float(
            prob.get_val(Mission.TOTAL_FUEL_MASS, units="lbm")[0]
        ),
        "wing_mass_lbm": float(prob.get_val(Aircraft.Wing.MASS, units="lbm")[0]),
        "range_nmi": float(prob.get_val(Mission.RANGE, units="nmi")[0]),
        "final_time_min": float(prob.get_val(Mission.FINAL_TIME, units="min")[0]),
        "engine_scale_factor": float(
            np.ravel(prob.get_val(Aircraft.Engine.SCALE_FACTOR))[0]
        ),
        "engine_reference_sls_thrust_lbf": engine_info["reference_sls_thrust_lbf"],
        "engine_deck_points_used": engine_info["n_used"],
    }


if __name__ == "__main__":
    for key, val in run().items():
        print(f"{key}: {val:.4f}" if isinstance(val, float) else f"{key}: {val}")
