# Provenance — Recording Decisions and Tracing Workflows

The CLI has built-in provenance recording: every tool call is automatically
logged to a SQLite database (`~/.oas_provenance/sessions.db`, override via
`OAS_PROV_DB` env var). Three additional tools let you group calls into named
sessions, record reasoning, and export the full DAG.

## When to use provenance

**Always** call `start_session` at the beginning of a multi-step workflow in
interactive or script mode. Use `log_decision` before major choices (mesh
resolution, design variables, interpreting surprising results). Call
`export_session_graph` at the end to save the audit trail.

## The three provenance tools

| Tool | Purpose |
|------|---------|
| `start_session` | Begin a named session — groups all subsequent calls |
| `log_decision` | Record why a choice was made (DV selection, mesh, etc.) |
| `export_session_graph` | Export the session DAG as JSON |

## Decision types

Use these standard `decision_type` values with `log_decision`:

| `decision_type` | When to use |
|-----------------|-------------|
| `mesh_resolution` | Choosing `num_x` / `num_y` |
| `dv_selection` | Choosing design variables and their bounds |
| `constraint_choice` | Choosing optimization constraints |
| `result_interpretation` | Explaining what a result means and next steps |
| `convergence_assessment` | Assessing whether an optimizer converged |

## Required decision points

Agents MUST call `log_decision` at each of these points during a workflow:

| After this step | `decision_type` | `prior_call_id`? |
|-----------------|-----------------|------------------|
| `create_surface` | `mesh_resolution` | No |
| Any analysis tool | `result_interpretation` | Yes — from `_provenance.call_id` |
| Before `run_optimization` | `dv_selection` | Optional |
| Before `run_optimization` | `constraint_choice` | Optional |
| After `run_optimization` | `convergence_assessment` | Yes — from `_provenance.call_id` |

## Chaining prior_call_id

Every successful tool call returns a `_provenance` field in its result dict:
```json
{"ok": true, "result": {"CL": 0.5, ..., "_provenance": {"call_id": "uuid-...", "session_id": "sess-..."}}}
```

Pass this `call_id` as `prior_call_id` in `log_decision` to create a causal
link between the analysis result and your decision. This makes the provenance
graph show *which result informed which decision*.

## Interactive mode example (Python)

```python
# Start session
sess = call("start_session", notes="CRM drag study")

# Create surface
call("create_surface", name="wing", wing_type="CRM", num_y=7,
     symmetry=True, with_viscous=True, CD0=0.015)

# Log mesh decision
call("log_decision",
     decision_type="mesh_resolution",
     reasoning="num_y=7 for fast iteration; will refine later",
     selected_action="num_y=7")

# Run analysis
result = call("run_aero_analysis", surfaces=["wing"], alpha=5.0,
              velocity=248.136, Mach_number=0.84, density=0.38,
              reynolds_number=1e6)

# Log interpretation, linking to the analysis call_id
call("log_decision",
     decision_type="result_interpretation",
     reasoning=f"CL={result['results']['CL']:.3f}, L/D={result['results']['L_over_D']:.1f} — reasonable",
     selected_action="proceed to optimization",
     prior_call_id=result["_provenance"]["call_id"])

# Export the graph
graph = call("export_session_graph", output_path="study_provenance.json")
```

## Script mode with provenance

```json
[
  {"tool": "start_session", "args": {"notes": "CRM aero optimization"}},
  {"tool": "create_surface", "args": {
    "name": "wing", "wing_type": "CRM", "num_y": 7,
    "symmetry": true, "with_viscous": true, "CD0": 0.015
  }},
  {"tool": "log_decision", "args": {
    "decision_type": "dv_selection",
    "reasoning": "Twist and alpha give best L/D improvement for aero-only",
    "selected_action": "twist (3 cp, -10..10), alpha (-5..15)",
    "confidence": "high"
  }},
  {"tool": "run_optimization", "args": {
    "surfaces": ["wing"], "analysis_type": "aero", "objective": "CD",
    "design_variables": [
      {"name": "twist", "lower": -10, "upper": 10, "n_cp": 3},
      {"name": "alpha", "lower": -5, "upper": 15}
    ],
    "constraints": [{"name": "CL", "equals": 0.5}],
    "Mach_number": 0.84, "density": 0.38, "velocity": 248.136,
    "reynolds_number": 1e6
  }},
  {"tool": "export_session_graph", "args": {"output_path": "provenance.json"}}
]
```

Note: in script mode you cannot pass `prior_call_id` referencing a previous
step's `_provenance.call_id` because there's no interpolation for nested
fields. The automatic call recording still captures the full sequence; explicit
`prior_call_id` links are only possible in interactive mode (Python) where you
can extract the value from the response dict.

## One-shot mode limitation

Each one-shot invocation is a separate process, so `start_session` in one call
does not carry over to the next. All calls are still recorded in the provenance
DB under session `"default"`, but they won't be grouped into a named session.
**Use interactive or script mode for provenance-tracked workflows.**

## Viewing the provenance graph

- **CLI**: `oas-cli viewer` starts the viewer server on localhost:7654
- **Browser**: Open `http://localhost:7654/viewer?session_id=<id>`
- **Offline**: Open `oas_mcp/provenance/viewer/index.html` and drop the
  exported JSON file onto the page
