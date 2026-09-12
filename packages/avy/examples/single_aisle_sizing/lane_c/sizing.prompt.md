# Task: Advanced Single-Aisle Sizing (closed prompt)

Size the advanced technology single-aisle transport on its design mission
through the Aviary MCP server.

## Requirements

- Template: `advanced_single_aisle` (FLOPS mass + aero, energy_state)
- Mission: the default 3-phase energy_state climb/cruise/descent with a
  range constraint of `1906 nmi`
- Optimizer: `SLSQP`, `max_iter=50`

## Tools

Only the `mcp__Aviary__*` tools. Workflow:

1. `start_session`
2. `load_aircraft_template(template="advanced_single_aisle")`
3. `log_decision(decision_type="architecture_choice", ...)`
4. `configure_mission(target_range_nm=1906)`
5. `run_sizing(optimizer="SLSQP", max_iter=50)`
6. Verify `validation.passed` (the `optimizer.success` finding) before
   reporting numbers
7. `log_decision(decision_type="result_interpretation", prior_call_id=...)`
8. `export_session_graph`

## Deliverables

Report, as a fenced JSON block:

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
