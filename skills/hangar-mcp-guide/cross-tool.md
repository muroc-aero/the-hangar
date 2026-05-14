# Cross-Tool Orchestration

The Hangar servers do not share runtime state - no shared OpenMDAO
problem, no shared cache. The agent is the integration layer.

What they DO share:
- The provenance SQLite DB (one DB, one path per `HANGAR_PROV_DB`).
- The artifact store (`hangar_data/artifacts/`).
- The viewer (port 7654; first server to start binds it).

So cross-tool workflows live in two places: tool-call orchestration
(in the agent's hands) and provenance-graph stitching (via
`link_cross_tool_result`).

## When to reach for which tool

| Question | Server |
|----------|--------|
| What is the CL/CD/L/D of this wing at this Mach and alpha? | OAS |
| What is the structural mass if I size this wing for a 2.5g pull-up? | OAS aerostruct |
| How much fuel does this aircraft burn over a 1500 NM mission? | OCP |
| Will a series-hybrid drivetrain meet this mission? | OCP |
| What is the SFC of this turbojet at 35k ft / Mach 0.8? | pyc |
| Multi-discipline trade study | All three, with handoffs |

## The four composition patterns

These are explained in detail in `skills/multi-tool-composition.md`.
Summarised here with the MCP-specific mechanics.

### Pattern 1 - Sequential handoff

Run tool A, extract a result, feed into tool B.

```
OAS: run_aero_analysis -> CD, CL
Agent: drag_N = CD * 0.5 * rho * V^2 * S_ref
OAS log_decision(tool_handoff, prior_call_id=<oas_call_id>)
pyc: run_off_design with the required Fn = drag_N
pyc log_decision(result_interpretation, prior_call_id=<pyc_call_id>)
```

Critical: the `log_decision(tool_handoff)` step is what gives the
viewer a chance to surface the dependency. Without it the cross-tool
edge does not appear.

You may also call `link_cross_tool_result` to register an explicit
cross-reference row in the DB:

```python
await link_cross_tool_result(
    source_run_id=oas_res["run_id"],
    source_tool="oas",
    target_session_id=pyc_sess["session_id"],
    target_tool="pyc",
    variable_name="thrust_required_N",
    value=drag_N,
    notes="OAS cruise drag becomes pyc thrust requirement",
)
```

This is what the viewer reads to draw cross-server edges.

### Pattern 2 - Iterative coupling

For weight-drag style loops:

```
1. Guess engine mass = 5000 kg
2. OAS run_aerostruct_analysis with W0 including engine -> drag, fuelburn
3. pyc run_design_point sized for drag -> new engine mass
4. If |delta| > tol: log_decision(tool_handoff); back to step 2
5. log_decision(coupling_convergence) when converged
```

Each iteration is its own captured call. The DAG ends up with
N OAS->pyc handoffs and one final `coupling_convergence` decision.

### Pattern 3 - Parallel independent analyses

Run multiple analyses, combine into a comparison table.

```
OAS: compute_drag_polar -> aero metrics
pyc: run_design_point at multiple thrust levels -> engine deck
Agent: stitch into a table
log_decision(result_interpretation) with both prior_call_ids
```

A single decision can reference multiple prior call_ids only if the
server supports a list. Today `log_decision.prior_call_id` is a single
string. For multi-source decisions, log one decision per source and
chain them with `notes`, or rely on the parallel structure being
obvious from the DAG.

### Pattern 4 - Sensitivity cascade

Sweep a parameter through the whole stack.

```
for span in [25, 30, 35, 40]:
    OAS: re-create_surface with span; run_aero_analysis
    pyc: size engine for cruise drag at this span
    OCP: run mission with both the OAS wing and the pyc deck
    record (span, CD, mass, range)
```

Each iteration of the loop should be its own provenance session, or
all in one session with iteration tagged in the decision `notes`.
Per-iteration sessions are easier to view but produce more DAGs.

## Session strategy across servers

There is no single "study session" that spans servers. Each
`start_session()` is local to the server it was called on. Two reasonable
patterns:

**A. One session per server.** Start a session in each server at the
beginning of the workflow. Log handoffs in each session pointing at
the other server's call_ids. Export each DAG separately, then in
the report cite both files.

**B. Mirrored session ids.** Use the same `notes=` string in both
`start_session` calls and put the *other* server's session id in the
notes (e.g. `notes="aero+mission study; OCP session sess-def456"`). The
viewer doesn't auto-link these, but a reader can navigate by id.

Pattern A is preferred. The `link_cross_tool_result` table is the
official mechanism for the viewer to draw the cross-server edges; the
viewer will eventually surface those even without manual cross-references.

## Interface variables and units

| Variable | Units | From | To |
|----------|-------|------|-----|
| CD, CL | dimensionless | OAS | OCP, pyc |
| Drag force | N | OAS (CD * q * S) | pyc (thrust target), OCP |
| Structural mass | kg | OAS aerostruct | OCP (empty weight component) |
| Fuelburn (per Breguet) | kg | OAS | OCP (sanity check) |
| Fn (thrust) | lbf | pyc | OCP (engine sizing) |
| TSFC | lbm/hr/lbf | pyc | OCP (mission fuel) |
| MTOW, W0 | kg | OCP | OAS aerostruct (W0 input) |

Be explicit about units in every `log_decision(tool_handoff)` reasoning
field. OAS speaks SI; pyc speaks imperial; OCP is mixed depending on
the template. Mismatches here are the most common bug class in
cross-tool studies.

## Running the agent across the three servers

In a Claude Code session you typically have all three MCP servers
listed in `.mcp.json` and they auto-start with the harness. The agent
sees them as separate tool prefixes:

```
mcp__OpenAeroStruct__*    # OAS server
mcp__OpenConcept__*       # OCP server
mcp__pyCycle__*           # pyc server
```

When connected via the claude.ai connector the same servers appear
with the `claude_ai_` prefix:

```
mcp__claude_ai_OpenAeroStruct__*
mcp__claude_ai_OpenConcept__*
mcp__claude_ai_pyCycle__*
```

A single workflow may use both prefixes if both connections are active.
Pick the one that fires (deferred tools become available after the
first call from the harness).
