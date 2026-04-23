# Task: Caravan Mission with pyCycle Turbojet Propulsion

Run a Cessna 208 Caravan basic mission (climb / cruise / descent)
through the omd plan pipeline using a pyCycle turbojet for propulsion
in place of the default turboprop. The turbojet is intentionally
unrealistic for this airframe; the point is to exercise the
propulsion-slot mechanism.

## Requirements

- Component type: `ocp/BasicMission`
- Aircraft: Caravan (built-in template `caravan`)
- Propulsion slot: `pyc/turbojet` (replacing the default turboprop)
- Mission: 250 NM range, 18,000 ft cruise altitude
- Turbojet design point: 18,000 ft, Mach 0.35, 4,000 lbf, T4 = 2,370 °R

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `slots-and-fidelity.md` companion file for
  propulsion-slot providers, and `pycycle-specifics.md` for pyCycle
  design-point and thermo-method options.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`. (Expect a one-time pyCycle deck
   training step at startup.)
2. Reported `fuel_burn_kg`, `OEW_kg`, and `MTOW_kg`.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the slot choice and the design
     point, and noting that this is a slot-mechanism demonstration
     rather than a physical design.
   - `result_interpretation` covering whether the propulsion slot wired
     correctly (e.g. fuel burn responds to thrust profile) regardless
     of physical plausibility.
4. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
