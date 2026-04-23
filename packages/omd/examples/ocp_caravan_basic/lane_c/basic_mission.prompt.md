# Task: Caravan Basic Mission Analysis

Run a three-phase mission analysis (climb / cruise / descent) for a
Cessna 208 Caravan turboprop through the omd plan pipeline.

## Requirements

- Component type: `ocp/BasicMission`
- Aircraft: Caravan (built-in template `caravan`)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Climb: 850 ft/min at 104 kn
- Cruise: 129 kn
- Descent: 400 ft/min at 100 kn
- Analysis nodes per phase: 11

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `ocp-specifics.md` companion file for OpenConcept
  templates, propulsion architectures, and mission-parameter naming
  (suffixed units like `cruise_altitude_ft`, `mission_range_NM`).

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `fuel_burn_kg`, `OEW_kg`, and `MTOW_kg` from the run
   summary.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the template, propulsion
     architecture, and node count.
   - `result_interpretation` with reasoning about whether the fuel
     burn is consistent with a Caravan on a 250 NM mission.
4. Mission-profile and weight plots via `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
