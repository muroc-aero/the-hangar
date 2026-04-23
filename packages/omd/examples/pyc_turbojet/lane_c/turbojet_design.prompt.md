# Task: Single-Spool Turbojet Sea-Level Static Design Point

Run a pyCycle single-spool turbojet design-point analysis through the
omd plan pipeline.

## Requirements

- Component type: `pyc/TurbojetDesign`
- Compressor: PR = 13.5, efficiency = 0.83
- Turbine efficiency: 0.86
- Shaft speed: 8,070 rpm
- Thermo method: CEA (chemical equilibrium)
- Operating point: sea-level static (`alt = 0 ft`, `MN ~ 0`)
- Targets: `Fn_target = 11,800 lbf`, `T4_target = 2,370 °R`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `pycycle-specifics.md` companion file for
  pyCycle component types, operating-point conventions, and
  available plot types.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `Fn`, `TSFC`, `OPR`, and `Fg` from the run summary.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the archetype, design point,
     and thermo method.
   - `result_interpretation` covering whether `Fn` matches the target,
     whether `TSFC` is in the typical 0.8-1.5 lbm/hr/lbf turbojet
     band, and whether `OPR` equals the compressor PR (single-spool).
4. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
