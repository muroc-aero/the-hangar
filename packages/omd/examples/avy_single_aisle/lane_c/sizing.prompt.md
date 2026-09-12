# Task: Aviary Single-Aisle Sizing (closed prompt)

Size the advanced single-aisle transport on its design mission through the
omd plan pipeline.

## Requirements

- Component type: `avy/Sizing`
- Deck: `models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv`
- Mission: `phase_info_module=aviary.models.missions.energy_state_default`,
  `target_range_nm=1906.0`
- Optimizer: `optimizer=SLSQP`, `max_iter=50`
- Run with `mode=analysis` -- the component is self-driving (every Aviary
  run is an embedded optimization).

## Tools

The `mcp__omd__*` tools: `plan_init` -> `plan_add_component` ->
`assemble_plan` -> `validate_plan` -> `run_plan` -> `get_results`, with
`log_decision` at the component-choice and result-interpretation points.

## Deliverables

Verify `converged == 1.0` in the summary (Aviary optimizer non-convergence
does not raise), then report as a fenced JSON block:

```json
{
  "gross_mass_lbm": <float>,
  "total_fuel_mass_lbm": <float>,
  "range_nmi": <float>,
  "final_time_min": <float>,
  "run_id": "<run id>",
  "friction": ["<any tool-surface problems you hit>"]
}
```
