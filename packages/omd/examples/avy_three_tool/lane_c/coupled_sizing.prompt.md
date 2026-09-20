# Task: Three-Tool Coupled Sizing via omd (closed prompt)

Size the advanced single-aisle transport with a physics-based
OpenAeroStruct wingbox wing mass replacing the empirical FLOPS estimate
and a pyCycle high-bypass turbofan replacing the file engine deck, through
the omd plan tools.

## Requirements

- Component type: `avy/Sizing` with config:
  - `deck: models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv`
  - `phase_info_module: hangar.avy.config.missions_oas_wing`
  - `external_subsystems: [{name: oas_wing_mass}]`
  - `engine_deck: {provider: pyc/hbtf, config: {design_alt_ft: 35000,
    design_MN: 0.8, design_Fn_lbf: 5900, design_T4_degR: 2857,
    engine_params: {thermo_method: TABULAR},
    grid: {alt_ft: [0, 10000, 20000, 30000, 37000], MN: [0, 0.25, 0.5, 0.8],
    throttle: [0.5, 0.7, 0.85, 1.0]}}}`
  - `optimizer: SLSQP`, `max_iter: 60`
- Run mode: `optimize` (every Aviary run is an optimization; the component
  brings its own design variables and objective). Expect ~2 min, plus
  ~5 min for the pyCycle sweep if no cached deck exists yet.

## Tools

Only the `mcp__omd__*` tools. Workflow:

1. `start_session`
2. `plan_init` -> `plan_add_component` (config above) -> `assemble_plan`
3. `validate_plan`
4. `run_plan(mode="optimize")`
5. Verify the summary's `converged` flag is true before reporting numbers
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
  "engine_scale_factor": <number>,
  "converged": <bool>
}
```

`wing_mass_lbm` is the OAS wingbox value that overrode the FLOPS estimate;
`engine_scale_factor` is `summary.engine_deck.scale_factor`, the factor
Aviary applied to the pyCycle deck to meet the airframe's SLS thrust.
