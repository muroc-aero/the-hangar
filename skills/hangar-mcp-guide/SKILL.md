---
name: hangar-mcp-guide
description: >
  How to drive the Hangar MCP servers (OpenAeroStruct, OpenConcept, pyCycle)
  directly via the Model Context Protocol, instead of via their local CLIs.
  Covers server startup and transports, the auto-started provenance viewer,
  the two senses of session_id, the canonical workflow each server enforces,
  and cross-tool orchestration. Use this skill whenever the user wants to
  call an MCP tool (mcp__OpenAeroStruct__*, mcp__OpenConcept__*, mcp__pyCycle__*),
  inspect the provenance viewer, or chain results between Hangar tool servers.
  For tool parameters and analysis semantics, defer to the per-tool CLI
  guides (oas-cli-guide, ocp-cli-guide, pyc-cli-guide) - the tool surface
  is identical between MCP and CLI.
---

# Hangar MCP Guide

The Hangar workspace ships three MCP servers - OpenAeroStruct (`oas`),
OpenConcept (`ocp`), pyCycle (`pyc`) - plus a shared SDK that gives them
common provenance, an artifact store, and a browser viewer. This skill
documents the MCP-specific bits. Tool semantics (parameters, units,
workflow ordering) are documented in the per-tool CLI guides; tool names
and arguments are identical between MCP and CLI usage.

**Supporting reference files** (read when you need deeper detail):
- `servers.md` - per-server startup, transport, tool catalogue
- `workflows.md` - canonical workflow per server + the session_id gotcha
- `cross-tool.md` - multi-tool orchestration patterns
- `examples/` - worked examples (OAS-only, OAS->OCP cross-tool)

## When to use MCP vs CLI vs omd

| Situation | Use |
|-----------|-----|
| Interactive agent session (this conversation) | **MCP** - the tools surface directly |
| Local benchmarking, parameter sweeps, CI | **CLI** (oas-cli, ocp-cli, pyc-cli) - faster startup, scriptable |
| Reproducible optimisation problems with provenance | **omd-cli** with a plan YAML |
| Comparing CLI and MCP results | **CLI** in scripts, MCP for the agent run, then diff |

There is a standing preference in user memory to prefer the local CLIs for
comparison/benchmark work. MCP is the right tool when the agent is
orchestrating a workflow live.

## Narrate while you work

MCP tool calls and their JSON results are folded by default in the user's
view. The user follows the run through your text, not through tool output.
Before each MCP call (or each tight group of calls) write one short
sentence in plain English saying what you are doing. Keep it terse.

Good:
- "Starting provenance session for the trade study."
- "Creating the aluminum wing (Cessna 172 geometry, num_y=7)."
- "Running aerostruct opt at 2.5g, objective=structural_mass."
- "First opt failed - widening twist bounds and rerunning."
- "Plotting stress distribution for the composite case."

Bad:
- Silent run-throughs of 5+ tool calls.
- "Calling mcp__OpenAeroStruct__run_optimization with the following
   arguments..." (the user does not read tool args).
- Long narration that repeats what the next tool call already shows.

Speak up when:
- You change direction (constraint sign was wrong, retrying).
- A result is worth flagging (failure margin -0.21 means 20% headroom).
- Something needs a decision from the user (mesh refinement?
  different load case?).

If the run is fully on autopilot, one sentence per call is enough.

## Tool name prefixes

Depending on how the MCP server is connected, tool names appear with
different prefixes in this session:

| Connection | Prefix | Example |
|------------|--------|---------|
| Local stdio (claude code) | `mcp__OpenAeroStruct__` | `mcp__OpenAeroStruct__create_surface` |
| claude.ai connector | `mcp__claude_ai_OpenAeroStruct__` | `mcp__claude_ai_OpenAeroStruct__create_surface` |

Both refer to the same underlying tool. Use whichever appears in the
deferred-tool list for the current session.

## Two senses of `session_id` (read this first)

The MCP tools have two distinct things called `session_id`:

1. **Provenance session** - groups DAG nodes (tool calls, decisions).
   Driven by `start_session()` which writes to module-level
   `_server_session_id` in `hangar.sdk.provenance.middleware`. Every
   tool call afterwards is recorded under this id.
2. **Tool session** - the container for surfaces, cached OpenMDAO
   problems, per-session config. Each analysis tool takes a
   `session_id="default"` kwarg.

The kwarg you pass to `create_surface(session_id=...)` only controls #2.
Provenance recording reads from the middleware's globals. Calling
`start_session()` changes #1 only.

See [[mcp-session-id-routing]] memory for the past bug that conflated
these (fixed 2026-05-14): servers used to seed `_prov_session_id`
(ContextVar) at startup with an `auto-XXXX` id, which shadowed every
later `start_session()` call. Symptom was `export_session_graph(<your sid>)`
returning 0 nodes. If you see that today, the server is running stale code -
restart it.

## Server lifecycle

Each Hangar MCP server is a normal FastMCP process. For local development
they are started either by Claude Code (via the `.mcp.json` config) or
manually:

```bash
uv run python -m hangar.oas.server         # OAS, stdio transport (default)
uv run python -m hangar.ocp.server
uv run python -m hangar.pyc.server

# HTTP transport (for claude.ai connectors or remote use):
uv run python -m hangar.oas.server --transport http --port 8000
```

On stdio startup each server prints its viewer URL to stderr:

```
------------------------------------------------------
  OAS Provenance Viewer
------------------------------------------------------
  Viewer    http://localhost:7654/viewer
  Sessions  http://localhost:7654/sessions
  Plot API  http://localhost:7654/plot?run_id=<id>&plot_type=<type>
------------------------------------------------------
```

Port `7654` is the shared default for the viewer; the server itself
talks MCP over stdio (no port) or over the HTTP transport port.

If multiple Hangar servers run simultaneously and you don't see the
viewer at `7654`, the second-to-start server quietly fell back to
another port - check its stderr. Only one viewer instance per port.

## Provenance viewer URLs

| URL | Purpose |
|-----|---------|
| `http://localhost:7654/sessions` | List all sessions in the DB |
| `http://localhost:7654/viewer?session_id=<sid>` | DAG for one session |
| `http://localhost:7654/dashboard?run_id=<rid>` | Per-run dashboard with plots |
| `http://localhost:7654/plot?run_id=<rid>&plot_type=<t>` | Direct plot image |

The DB lives at `hangar_data/.provenance/sessions.db` by default
(override with `HANGAR_PROV_DB` env var).

## Canonical workflow

Every Hangar MCP server enforces the same skeleton; the middle steps
vary by tool. See `workflows.md` for the per-server detail.

```
1. start_session                  begin provenance session
2. <define geometry or aircraft>  create_surface / load_aircraft_template / create_engine
   log_decision                   record mesh / archetype / architecture choice
3. <run analysis>                 run_aero_analysis / run_mission_analysis / run_design_point
   log_decision                   result_interpretation, with prior_call_id
4. <optional: optimise>           run_optimization
   log_decision                   convergence_assessment
5. export_session_graph           save the DAG to disk
6. reset (optional)               clear in-memory state between unrelated experiments
```

The two `log_decision` calls flanking each analysis are not optional - the
server-side instructions in each FastMCP `instructions=` string require
them, and the viewer's DAG is much less useful without them.

## Response envelope

Every analysis tool returns the same envelope (schema_version="1.0"):

```json
{
  "results":    { "...": "tool-specific payload (CL, CD, fuelburn, ...)" },
  "validation": { "passed": true, "findings": [] },
  "telemetry":  { "duration_ms": 123, "cache_hit": false },
  "run_id":     "20260514T120000_a1b2c3",
  "_provenance": { "call_id": "uuid-...", "session_id": "sess-..." },
  "error":      null
}
```

When checking results, always check `validation.passed` before trusting
the numbers. `_provenance.call_id` is what you pass as `prior_call_id` to
`log_decision` to wire causal edges in the DAG.

## Critical constraints (cross-server)

These are common gotchas; the per-server sections in `servers.md` list
the rest.

- **OAS `num_y` must be ODD** (3, 5, 7, ...) - VLM symmetry requirement.
- **OCP `num_nodes` must be ODD** (3, 5, 7, 11, 21, ...) - Simpson's rule.
- **pyc `run_design_point` MUST precede `run_off_design`** - off-design
  inherits sized geometry from the design point.
- **OAS aerostruct tools require structural surface params** -
  `fem_model_type`, `E`, `G`, `yield_stress`, `mrho`, thickness CPs.

## Mesh density - scoping vs production

The defaults in the examples and quick-start scripts (`num_y=7`,
`num_nodes=11`) are SCOPING fidelity, not production. They exist so a
single opt finishes in a few seconds, which is right for design
exploration, debugging, and skill checks. They are wrong for any number
that will be acted on - sized to a stakeholder, used to set a target,
or quoted in a report.

| Use case | OAS `num_y` | OAS `num_x` | OCP `num_nodes` |
|----------|-------------|-------------|-----------------|
| Scoping, debugging, agent skill checks | 7 - 11 | 2 | 5 - 11 |
| Real trade study | 21 - 31 | 3 - 5 | 21 - 31 |
| Production sizing for a stakeholder | 41+ | 5+ | 51+ |

All values must remain odd. Always run a quick mesh refinement study
before quoting a production number: rerun the same opt at e.g. `num_y =
11, 21, 41` and confirm the objective changes by less than 1-2% between
the last two. If it does not, you are still in the scoping regime;
refine further.

Tell the user explicitly when you are running at scoping fidelity vs
production, and what the mesh refinement looked like. "Trade study at
num_y=7 (scoping)" and "production opt at num_y=41 after mesh-converged
between 21 and 41" are very different claims.

Production opts can run for minutes to hours at num_y=41+. Use
`pin_run` to keep the cached problem alive across related opts, and
rely on the artifact store (run_id is persisted to the DB) so the
result is not lost if the connection drops.

## Error envelope

```json
{"ok": false, "error": {"code": "USER_INPUT_ERROR", "message": "..."}}
```

| Code | Meaning |
|------|---------|
| `USER_INPUT_ERROR` | Bad params, missing prerequisite, malformed input |
| `SOLVER_CONVERGENCE_ERROR` | Newton/optimizer failed - back off mesh or DV bounds |
| `CACHE_EVICTED_ERROR` | Cached OpenMDAO problem cleared - rebuild surface/aircraft |
| `INTERNAL_ERROR` | Bug - surface to the user, do not auto-retry |

## Related skills

- `oas-cli-guide`, `ocp-cli-guide`, `pyc-cli-guide` - per-tool reference;
  the MCP and CLI tool surfaces are identical, so consult these for
  parameter names, units, and analysis semantics.
- `multi-tool-composition` (`skills/multi-tool-composition.md`) - the
  general agent-as-integrator pattern; `cross-tool.md` here covers the
  MCP-specific orchestration mechanics.
- `design-study-workflow` - the structured study template, MCP or CLI.
