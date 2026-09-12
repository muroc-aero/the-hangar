"""Standalone Aviary sizing worker -- executed INSIDE .venv-avy.

The omd ``avy/Sizing`` factory cannot import aviary in the main workspace
venv (aviary needs numpy>=2, the openconcept pin caps numpy<2), so it runs
this script with the isolated venv's interpreter:

    .venv-avy/bin/python avy_worker.py <spec.json> <out.json>

The spec names the deck, the phase_info module, and run settings; results
are written as JSON to ``out.json``. This module imports NOTHING from
hangar.omd (it runs in a venv where hangar-omd is not installed) and uses
upstream aviary APIs directly. Subprocess isolation also removes the
process-global hazards the in-process avy server has to lock around
(cwd-relative reports, colliding OpenMDAO problem names).

Spec schema::

    {
      "deck": "models/aircraft/.../x.csv",       # aviary-relative or absolute
      "phase_info_module": "aviary.models.missions.energy_state_default",
      "target_range_nm": 1906.0,                 # optional; sets constrain_range
      "overrides": {"aircraft:wing:aspect_ratio": 13.0,
                    "aircraft:design:gross_mass": [150000, "lbm"]},  # optional
      "external_subsystems": [                   # optional; hangar.avy registry
          {"name": "oas_wing_mass", "config": {"cruise_mach": 0.785}}
      ],
      "optimizer": "SLSQP",
      "max_iter": 50,
      "workdir": "/abs/path/scratch"             # cwd for the run
    }

The phase_info module may be any importable module exposing ``phase_info``
-- aviary's own mission modules or hangar.avy's adapted ones (hangar-avy is
installed in .venv-avy by scripts/setup-avy-venv.sh).
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import sys


def run(spec: dict) -> dict:
    from openmdao.core.problem import _clear_problem_names
    from aviary.interface.run_aviary import run_aviary
    from aviary.utils.process_input_decks import create_vehicle
    from aviary.variable_info.variable_meta_data import _MetaData
    from aviary.variable_info.variables import Aircraft, Mission

    phase_mod = importlib.import_module(spec["phase_info_module"])
    phase_info = copy.deepcopy(phase_mod.phase_info)

    subsystems = []
    subsystem_specs = spec.get("external_subsystems") or []
    if subsystem_specs:
        # hangar.avy IS installed in .venv-avy (unlike hangar.omd); its
        # registry validates names/configs with typo suggestions.
        from hangar.avy.subsystems import build_external_subsystems

        subsystems = build_external_subsystems(subsystem_specs)

    target_range_nm = spec.get("target_range_nm")
    if target_range_nm is not None:
        phase_info["post_mission"]["constrain_range"] = True
        phase_info["post_mission"]["target_range"] = (float(target_range_nm), "nmi")

    aircraft_data = spec["deck"]
    overrides = spec.get("overrides") or {}
    if overrides:
        aircraft_data, _guesses = create_vehicle(aircraft_data)
        for name, value in overrides.items():
            if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[1], str):
                aircraft_data.set_val(name, value[0], value[1])
            else:
                aircraft_data.set_val(name, value, _MetaData[name]["units"])

    workdir = spec.get("workdir")
    if workdir:
        os.makedirs(workdir, exist_ok=True)
        os.chdir(workdir)

    _clear_problem_names()
    prob = run_aviary(
        aircraft_data,
        phase_info,
        optimizer=spec.get("optimizer", "SLSQP"),
        max_iter=int(spec.get("max_iter", 50)),
        subsystems=subsystems,
        make_plots=False,
        verbosity=0,
    )

    def val(name: str, units: str) -> float:
        return float(prob.get_val(name, units=units)[0])

    return {
        "success": bool(prob.result.success),
        "gross_mass_lbm": val(Mission.GROSS_MASS, "lbm"),
        "total_fuel_mass_lbm": val(Mission.TOTAL_FUEL_MASS, "lbm"),
        "operating_mass_lbm": val(Mission.OPERATING_MASS, "lbm"),
        "wing_mass_lbm": val(Aircraft.Wing.MASS, "lbm"),
        "range_nmi": val(Mission.RANGE, "nmi"),
        "final_time_min": val(Mission.FINAL_TIME, "min"),
    }


def main() -> int:
    spec_path, out_path = sys.argv[1], sys.argv[2]
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    result = run(spec)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
