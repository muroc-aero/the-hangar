# Task: OAS Wing-Mass Coupled Sizing (closed prompt)

Size the advanced single-aisle transport with a physics-based
OpenAeroStruct wingbox wing mass replacing the empirical FLOPS estimate,
through the Aviary MCP server.

## Requirements

- Template: `advanced_single_aisle` (FLOPS mass + aero, energy_state)
- External subsystem: `oas_wing_mass` with default config
- Mission: the `oas_wing_example` mission template (3 fixed-profile
  phases, 1800 nmi, no takeoff/landing)
- Optimizer: `SLSQP`, `max_iter=60`, `subsystem_mode="coupled"`
- Expect the run to take ~1 minute (the subsystem adds a nested wingbox
  sub-optimization).

## Tools

Only the `mcp__Aviary__*` tools. Workflow:

1. `start_session`
2. `load_aircraft_template(template="advanced_single_aisle")`
3. `log_decision(decision_type="architecture_choice", ...)`
4. `add_external_subsystem(subsystem="oas_wing_mass")`
5. `configure_mission(mission_template="oas_wing_example")`
6. `run_sizing(optimizer="SLSQP", max_iter=60, subsystem_mode="coupled")`
7. Verify `validation.passed` (the `optimizer.success` and
   `subsystem.wing_mass_applied` findings) before reporting numbers
8. `log_decision(decision_type="result_interpretation", prior_call_id=...)`
9. `export_session_graph`

## Deliverables

Report, as a fenced JSON block:

```json
{
  "gross_mass_lbm": <number>,
  "total_fuel_mass_lbm": <number>,
  "wing_mass_lbm": <number>,
  "range_nmi": <number>,
  "final_time_min": <number>,
  "optimizer_converged": <bool>
}
```

`wing_mass_lbm` is `results.design.wing_mass_lbm` -- the OAS wingbox
value that overrode the FLOPS estimate.
