# Task: Caravan Full Mission with Takeoff

Run a full mission analysis for a Cessna 208 Caravan that includes
balanced-field takeoff in addition to climb / cruise / descent.

## Requirements

- Component type: `ocp/FullMission`
- Aircraft: Caravan (built-in template `caravan`)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Speed profile: same as the basic mission

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `ocp-specifics.md` companion file for mission
  types and parameter naming.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `fuel_burn_kg`, `OEW_kg`, `MTOW_kg`, and takeoff field
   length (`TOFL`).
3. Comparison against the `ocp_caravan_basic` baseline: full mission
   should burn slightly more fuel because of the takeoff phase.
4. `decisions.yaml` entries:
   - `formulation_decision` documenting the mission type and
     architecture.
   - `result_interpretation` covering the fuel-burn delta versus the
     basic mission and TOFL reasonableness.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
