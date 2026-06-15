# Provenance -- Recording Decisions and Tracing Workflows

The CLI has built-in provenance recording: every tool call is automatically
logged to a SQLite database. Three additional tools let you group calls into
named sessions, record reasoning, and export the full DAG.

## When to use provenance

**Always** call `start_session` at the beginning of a multi-step workflow in
interactive or script mode. Use `log_decision` before major choices (vehicle
selection, parameter changes, interpreting surprising results). Call
`export_session_graph` at the end to save the audit trail.

## The three provenance tools

| Tool | Purpose |
|------|---------|
| `start_session` | Begin a named session -- groups all subsequent calls |
| `log_decision` | Record why a choice was made (vehicle, parameters, etc.) |
| `export_session_graph` | Export the session DAG as JSON |

## Decision types

Use these standard `decision_type` values with `log_decision`:

| `decision_type` | When to use |
|-----------------|-------------|
| `architecture_choice` | Choosing a vehicle template / configuration and why |
| `parameter_choice` | Choosing config overrides (battery energy, rotor sizing, etc.) |
| `result_interpretation` | Explaining what a result means and next steps |
| `convergence_assessment` | Assessing MTOW-iteration convergence quality |

## Required decision points

Agents should call `log_decision` at each of these points during a workflow:

| After this step | `decision_type` | `prior_call_id`? |
|-----------------|-----------------|------------------|
| `load_vehicle_template` | `architecture_choice` | No |
| `run_mission_analysis` | `result_interpretation` | Yes -- from `_provenance.call_id` |
| `run_sizing` | `convergence_assessment` | Yes -- from `_provenance.call_id` |

## Chaining prior_call_id

Every successful tool call returns a `_provenance` field in its result dict:

```json
{"ok": true, "result": {"run_id": "...", ..., "_provenance": {"call_id": "uuid-...", "session_id": "sess-..."}}}
```

Pass this `call_id` as `prior_call_id` in `log_decision` to create a causal link
between the analysis result and your decision, so the provenance graph shows
*which result informed which decision*.

## Interactive mode example (Python)

```python
sess = call("start_session", notes="eVTOL battery sensitivity study")

call("load_vehicle_template", template="test_all")
call("log_decision",
     decision_type="architecture_choice",
     reasoning="test_all lift+cruise reference is the validated baseline",
     selected_action="load test_all template")

m = call("run_mission_analysis")
call("log_decision",
     decision_type="result_interpretation",
     reasoning=f"total energy={m['results']['totals']['total_mission_energy_kw_hr']:.2f} kW*hr",
     selected_action="proceed to MTOW sizing",
     prior_call_id=m["_provenance"]["call_id"])

s = call("run_sizing")
call("log_decision",
     decision_type="convergence_assessment",
     reasoning=f"MTOW converged to {s['results']['sized_mtow_kg']:.0f} kg in {s['results']['iterations']} iters",
     selected_action="accept sized MTOW",
     prior_call_id=s["_provenance"]["call_id"])

graph = call("export_session_graph")
```

## Script mode with provenance

```json
[
  {"tool": "start_session", "args": {"notes": "eVTOL mission + sizing"}},
  {"tool": "load_vehicle_template", "args": {"template": "test_all"}},
  {"tool": "log_decision", "args": {
    "decision_type": "architecture_choice",
    "reasoning": "test_all lift+cruise reference baseline",
    "selected_action": "load test_all"
  }},
  {"tool": "run_mission_analysis", "args": {}},
  {"tool": "run_sizing", "args": {}},
  {"tool": "export_session_graph", "args": {}}
]
```

Note: in script mode you cannot pass `prior_call_id` referencing a previous
step's `_provenance.call_id` because there's no interpolation for nested fields.
The automatic call recording still captures the full sequence; explicit
`prior_call_id` links are only possible in interactive mode (Python) where you
can extract the value from the response dict.

## Cross-tool provenance

evt supports cross-tool workflows with the other hangar tools (e.g. handing an
eVTOL mission-energy result to a pyCycle or OAS study). Use
`link_cross_tool_result` to document data handoffs, and pass the same
`session_id` to each tool's `start_session` to share a provenance session:

```python
call("link_cross_tool_result",
     source_call_id=mission["_provenance"]["call_id"],
     source_tool="evt",
     target_tool="ocp",
     variables={"total_mission_energy_kw_hr": 166.78},
     notes="eVTOL mission energy used to size battery in the OpenConcept study")
```

## One-shot mode limitation

Each one-shot invocation is a separate process, so `start_session` in one call
does not carry over to the next. All calls are still recorded in the provenance
DB under session `"default"`, but they won't be grouped into a named session.
**Use interactive or script mode for provenance-tracked workflows.**

## Viewing the provenance graph

- **CLI**: `evt-cli viewer` starts the viewer server on localhost:7654
- **Browser**: Open `http://localhost:7654/viewer?session_id=<id>`
- **Offline**: Open the viewer HTML and drop the exported JSON file onto the page
