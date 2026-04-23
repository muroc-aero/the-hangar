# Task: Caravan Mission with Direct-Coupled VLM Drag

Run a Cessna 208 Caravan basic mission (climb / cruise / descent)
through the omd plan pipeline using direct-coupled VLM drag (live
solve every Newton iteration), not a pre-trained surrogate.

## Requirements

- Component type: `ocp/BasicMission`
- Aircraft: Caravan (built-in template `caravan`)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Drag slot: replace the default parabolic polar with the
  `oas/vlm-direct` slot provider (a true tight-coupled VLM solve)
- VLM mesh: `num_x=2`, `num_y=5`, `num_twist=4` (kept coarse to limit
  per-iteration cost)

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `slots-and-fidelity.md` companion file for the
  drag-slot providers and the surrogate-vs-direct trade-off, including
  any solver settings needed for direct coupling.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `fuel_burn_kg`, `OEW_kg`, and `MTOW_kg`. Runtime will be
   minutes rather than seconds because the full VLM runs every Newton
   iteration.
3. Comparison against the surrogate-coupled (`oas/vlm`) result from
   `ocp_oas_coupled`.
4. `decisions.yaml` entries:
   - `formulation_decision` documenting the slot choice
     (`oas/vlm-direct`), mesh fidelity, and the solver implications.
   - `result_interpretation` covering the direct-vs-surrogate fuel
     delta and whether convergence was clean.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
