# Task: Series-Hybrid Electric Mission

Run a full mission analysis for a King Air C90GT with a twin
series-hybrid electric propulsion architecture.

## Requirements

- Component type: `ocp/FullMission`
- Aircraft: King Air C90GT (built-in template `kingair`)
- Propulsion: `twin_series_hybrid`
- Mission: 250 NM range, 28,000 ft cruise altitude
- Hybrid sizing: 50 kg battery, motor / generator ratings appropriate
  for the King Air power class

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `ocp-specifics.md` companion file for hybrid
  architecture configuration (`battery_weight`, `motor_rating`,
  `generator_rating`).

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `fuel_burn_kg`, `OEW_kg`, `MTOW_kg`, and `TOFL`.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the architecture and battery /
     motor sizing rationale.
   - `result_interpretation` covering whether the hybrid architecture
     reduces fuel burn versus a conventional twin turboprop and what
     the weight penalty from battery / motors is.
4. Mission-profile and weight plots via `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
