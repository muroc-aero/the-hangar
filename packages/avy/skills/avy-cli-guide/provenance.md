# Provenance -- Recording Decisions and Tracing Workflows

The CLI has built-in provenance recording: every tool call is automatically
logged to a SQLite database. Three additional tools let you group calls into
named sessions, record reasoning, and export the full DAG.

## When to use provenance

**Always** call `start_session` at the beginning of a multi-step workflow in
interactive or script mode. Use `log_decision` before major choices (template
selection, deck overrides, interpreting surprising results). Call
`export_session_graph` at the end to save the audit trail.

## The provenance tools

| Tool | Purpose |
|------|---------|
| `start_session` | Begin a named session -- groups all subsequent calls |
| `log_decision` | Record why a choice was made (template, mission, overrides) |
| `link_cross_tool_result` | Reference a run from another hangar server |
| `export_session_graph` | Export the session DAG as JSON |

## Decision types

Use these standard `decision_type` values with `log_decision`:

| `decision_type` | When to use |
|-----------------|-------------|
| `architecture_choice` | Choosing an aircraft template and why |
| `parameter_choice` | Deck overrides or mission configuration choices |
| `result_interpretation` | Explaining what a result means and next steps |
| `convergence_assessment` | Assessing optimizer convergence quality |

## Required decision points

Agents MUST call `log_decision` at each of these points during a workflow:

| After this step | `decision_type` | `prior_call_id`? |
|-----------------|-----------------|------------------|
| `load_aircraft_template` | `architecture_choice` | No |
| `run_sizing` | `result_interpretation` | Yes -- from `_provenance.call_id` |
| `run_off_design` / `run_payload_range` | `result_interpretation` | Yes |

For non-converged runs (failed `optimizer.success` finding), log a
`convergence_assessment` decision explaining the failure and the retry plan
before re-running.

## Chaining prior_call_id

Every successful tool call returns a `_provenance` field in its result dict:

```json
{"ok": true, "result": {"run_id": "...", ..., "_provenance": {"call_id": "uuid-...", "session_id": "sess-..."}}}
```

Pass that `call_id` as `prior_call_id` in the follow-up `log_decision` so the
DAG shows which result informed the reasoning.

## Cross-tool linking

When an Aviary result feeds another hangar tool (e.g. comparing against an
OpenConcept mission), call `link_cross_tool_result` with the foreign run_id
so the combined provenance graph joins across servers.
