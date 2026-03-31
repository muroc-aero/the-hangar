# Provenance — Recording Decisions and Tracing Workflows

The CLI has built-in provenance recording: every tool call is automatically
logged to a SQLite database. Three additional tools let you group calls into
named sessions, record reasoning, and export the full DAG.

## When to use provenance

**Always** call `start_session` at the beginning of a multi-step workflow in
interactive or script mode. Use `log_decision` before major choices (architecture
selection, mission parameters, interpreting results). Call `export_session_graph`
at the end to save the audit trail.

## The three provenance tools

| Tool | Purpose |
|------|---------|
| `start_session` | Begin a named session — groups all subsequent calls |
| `log_decision` | Record why a choice was made |
| `export_session_graph` | Export the session DAG as JSON |

## Decision types

Use these standard `decision_type` values with `log_decision`:

| `decision_type` | When to use |
|-----------------|-------------|
| `architecture_choice` | Choosing propulsion architecture or aircraft template |
| `mission_params` | Choosing mission range, altitude, hybridization |
| `dv_selection` | Choosing design variables and their bounds |
| `constraint_choice` | Choosing optimization constraints |
| `result_interpretation` | Explaining what a result means and next steps |
| `convergence_assessment` | Assessing whether an optimizer converged |

## Required decision points

Agents MUST call `log_decision` at each of these points during a workflow:

| After this step | `decision_type` | `prior_call_id`? |
|-----------------|-----------------|------------------|
| `load_aircraft_template` | `architecture_choice` | No |
| `set_propulsion_architecture` | `architecture_choice` | No |
| Any analysis tool | `result_interpretation` | Yes — from `_provenance.call_id` |
| Before `run_optimization` | `dv_selection` | Optional |
| Before `run_optimization` | `constraint_choice` | Optional |
| After `run_optimization` | `convergence_assessment` | Yes — from `_provenance.call_id` |

## Interactive mode example (Python)

```python
# Start session
sess = call("start_session", notes="Hybrid design study")

# Load aircraft
call("load_aircraft_template", template="kingair")

# Log architecture decision
call("log_decision",
     decision_type="architecture_choice",
     reasoning="King Air is hybrid-ready with motor/generator data",
     selected_action="kingair + twin_series_hybrid")

# Set architecture
call("set_propulsion_architecture", architecture="twin_series_hybrid",
     battery_specific_energy=450)

# Configure and run
call("configure_mission", mission_range=500, cruise_altitude=29000,
     cruise_hybridization=0.05, payload=1000)

result = call("run_mission_analysis")

# Log interpretation with prior_call_id link
call("log_decision",
     decision_type="result_interpretation",
     reasoning=f"Fuel burn={result['results']['fuel_burn_kg']:.0f} kg, SOC={result['results'].get('battery_SOC_final', 'N/A')}",
     selected_action="proceed to hybridization sweep",
     prior_call_id=result["_provenance"]["call_id"])

# Export the graph
call("export_session_graph")
```

## Script mode with provenance

```json
[
  {"tool": "start_session", "args": {"notes": "Caravan mission analysis"}},
  {"tool": "load_aircraft_template", "args": {"template": "caravan"}},
  {"tool": "set_propulsion_architecture", "args": {"architecture": "turboprop"}},
  {"tool": "log_decision", "args": {
    "decision_type": "architecture_choice",
    "reasoning": "Caravan is a well-characterized single turboprop",
    "selected_action": "caravan + turboprop"
  }},
  {"tool": "configure_mission", "args": {"mission_range": 250, "cruise_altitude": 18000}},
  {"tool": "run_mission_analysis", "args": {}},
  {"tool": "export_session_graph", "args": {}}
]
```

## One-shot mode limitation

Each one-shot invocation is a separate process, so `start_session` in one call
does not carry over to the next. **Use interactive or script mode for
provenance-tracked workflows.**
