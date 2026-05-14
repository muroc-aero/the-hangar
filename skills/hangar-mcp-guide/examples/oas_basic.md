# Example - Basic OAS Workflow via MCP

A minimal aero analysis with full provenance. Equivalent to the
interactive-mode example in `oas-cli-guide/examples/aero_sortie.md`.

This is what the agent does when the user says "run a CRM wing at
alpha=5".

```python
# Pseudocode - in practice these are tool calls dispatched by the agent
# with the mcp__OpenAeroStruct__ prefix.

# 1. Begin a named provenance session.
sess = await start_session(notes="CRM single-point aero check")
session_id = sess["session_id"]   # e.g. "sess-ba3923d1c765"

# 2. Define the wing.
surf = await create_surface(
    name="wing",
    wing_type="CRM",
    num_y=7,          # MUST be odd
    symmetry=True,
    with_viscous=True,
    CD0=0.015,
)

# 3. Document the mesh choice.
await log_decision(
    decision_type="mesh_resolution",
    reasoning="num_y=7 for fast iteration; CRM template handles sweep+taper",
    selected_action="num_y=7",
)

# 4. Run the analysis.
res = await run_aero_analysis(
    surfaces=["wing"],
    alpha=5.0,
    velocity=248.136,
    Mach_number=0.84,
    density=0.38,
    reynolds_number=1e6,
)

# Always check validation before trusting the numbers.
assert res["validation"]["passed"], res["validation"]["findings"]

CL = res["results"]["CL"]
LD = res["results"]["L_over_D"]
call_id = res["_provenance"]["call_id"]

# 5. Interpret the result, wiring the causal edge.
await log_decision(
    decision_type="result_interpretation",
    reasoning=f"CL={CL:.3f}, L/D={LD:.1f}; consistent with CRM at M=0.84",
    selected_action="accept; proceed to plotting",
    prior_call_id=call_id,
)

# 6. Plot lift distribution (visualize returns a LIST, not a dict).
viz = await visualize(
    run_id="latest",
    plot_type="lift_distribution",
    output="file",
)
plot_path = viz[0]["file_path"]

# 7. Export the provenance graph.
g = await export_session_graph(
    session_id=session_id,
    output_path="crm_aero_check.json",
)
# g["nodes"] should be non-empty.
```

Expected DAG (post-export):

```
nodes: 4 edges: 3
 - tool_call <id>  | create_surface
 - decision <id>   | mesh_resolution
 - tool_call <id>  | run_aero_analysis
 - decision <id>   | result_interpretation
edges:
 - create_surface -> mesh_resolution (informs)
 - run_aero_analysis -> result_interpretation (informs)
 - mesh_resolution -> run_aero_analysis (decides)
```

(The `visualize` and `export_session_graph` calls themselves are also
captured as tool_call nodes; they just are not analysis-grade so they
typically aren't surfaced in the DAG count.)

## Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Skipped `start_session` | Calls land in `auto-XXXX` session | Always call `start_session` first |
| Used even `num_y` | `USER_INPUT_ERROR` from `create_surface` | Use 3, 5, 7, 9, ... |
| Forgot `reynolds_number` | `USER_INPUT_ERROR` | Always pass `reynolds_number` |
| Indexed `viz` as a dict | `KeyError` or `TypeError` | `viz` is a list: `viz[0]["file_path"]` |
| Used a stale `run_id` | `CACHE_EVICTED_ERROR` | Use `"latest"` or save the id immediately |
| No `prior_call_id` on decisions | DAG decisions float disconnected | Always pass `res["_provenance"]["call_id"]` |
