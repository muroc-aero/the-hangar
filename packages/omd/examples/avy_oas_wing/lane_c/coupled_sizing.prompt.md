# Task: OAS Wing-Mass Coupled Sizing via omd (closed prompt)

Size the advanced single-aisle transport with a physics-based
OpenAeroStruct wingbox wing mass replacing the empirical FLOPS estimate,
through the omd plan tools.

## Requirements

- Component type: `avy/Sizing` with config:
  - `deck: models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv`
  - `phase_info_module: hangar.avy.config.missions_oas_wing`
  - `external_subsystems: [{name: oas_wing_mass}]`
  - `optimizer: SLSQP`, `max_iter: 60`, `run_timeout_s: 1800`
- Run mode: `analysis` (the component is self-driving -- every Aviary run
  is an optimization). Expect ~90 s.

## Tools

Only the `mcp__omd__*` tools. Workflow:

1. `start_session`
2. `plan_init` -> `plan_add_component` (config above) -> `assemble_plan`
3. `validate_plan`
4. `run_plan(mode="analysis")`
5. Verify the `converged` output is 1.0 before reporting numbers
6. `log_decision(decision_type="result_interpretation", prior_call_id=...)`
7. `export_session_graph`

## Deliverables

Report, as a fenced JSON block:

```json
{
  "gross_mass_lbm": <number>,
  "total_fuel_mass_lbm": <number>,
  "wing_mass_lbm": <number>,
  "range_nmi": <number>,
  "final_time_min": <number>,
  "converged": <number>
}
```

`wing_mass_lbm` is the OAS wingbox value that overrode the FLOPS estimate.
