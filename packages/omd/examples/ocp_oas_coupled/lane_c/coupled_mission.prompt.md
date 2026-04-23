# Task: Caravan Mission with VLM-Surrogate Drag

Run a Cessna 208 Caravan basic mission (climb / cruise / descent)
through the omd plan pipeline using VLM-based drag instead of the
default parabolic polar. Drag should come from OpenAeroStruct via the
slot system on an OCP mission component.

## Requirements

- Component type: `ocp/BasicMission`
- Aircraft: Caravan (built-in template `caravan`)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Drag slot: replace the default parabolic polar with the `oas/vlm`
  slot provider
- VLM mesh: `num_x=2`, `num_y=7`, `num_twist=4`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `slots-and-fidelity.md` companion file for slot
  configuration, the available drag providers, and the surrogate-vs-
  direct trade-off.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `fuel_burn_kg`, `OEW_kg`, and `MTOW_kg`.
3. Comparison against the baseline Caravan mission (parabolic polar)
   from the `ocp_caravan_basic` example. The two drag models will not
   agree exactly because they make different assumptions.
4. `decisions.yaml` entries:
   - `formulation_decision` documenting the slot choice (`oas/vlm`)
     and mesh fidelity.
   - `result_interpretation` covering whether the fuel-burn delta vs.
     parabolic polar is physically reasonable.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
