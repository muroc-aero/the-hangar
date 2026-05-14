# Canonical Workflows

Every Hangar MCP server is shipped with `instructions=` text on its
FastMCP object that prescribes a required workflow. Agents are expected
to follow it. The middle steps differ per server; the provenance
scaffolding (start, decisions, export) is identical.

## OAS workflow

```
0. start_session                  notes="<study description>"
1. create_surface                 define geometry; required before any analysis
   log_decision                   decision_type="mesh_resolution"
2. run_aero_analysis | run_aerostruct_analysis | compute_drag_polar | ...
   log_decision                   decision_type="result_interpretation",
                                  prior_call_id=<result._provenance.call_id>
3. run_optimization               (optional)
   log_decision                   decision_type="dv_selection" (before)
   log_decision                   decision_type="constraint_choice" (before)
   log_decision                   decision_type="convergence_assessment" (after)
4. visualize                      generate plots for any run
5. export_session_graph           output_path="study.json"
6. reset                          (optional - clear between unrelated experiments)
```

For aerostruct analysis the surface from step 1 must include
`fem_model_type` (`"tube"` or `"wingbox"`) and material props.

## OCP workflow

```
0. start_session                  notes="<mission analysis>"
1. load_aircraft_template | define_aircraft
   log_decision                   decision_type="architecture_choice"
2. set_propulsion_architecture
   log_decision                   decision_type="architecture_choice"
3. configure_mission              (optional - defaults are reasonable)
4. run_mission_analysis
   log_decision                   decision_type="result_interpretation",
                                  prior_call_id=<result._provenance.call_id>
5. run_parameter_sweep            (optional)
6. run_optimization               (optional)
   log_decision                   convergence_assessment after
7. export_session_graph
```

Order matters - calling `run_mission_analysis` without an aircraft or
propulsion architecture returns `USER_INPUT_ERROR`. Setting a new
architecture invalidates the cached problem.

## pyc workflow

```
0. start_session                  notes="<engine cycle study>"
1. create_engine                  archetype="turbojet", params...
   log_decision                   decision_type="archetype_selection"
2. run_design_point               size the engine - REQUIRED before off-design
   log_decision                   decision_type="result_interpretation"
3. run_off_design                 evaluate at different flight conditions
   log_decision                   decision_type="result_interpretation"
4. visualize                      ts_diagram, station_properties, etc.
5. export_session_graph
```

Skipping `run_design_point` produces a `USER_INPUT_ERROR` from
`run_off_design` because the engine geometry has not been sized.

## The two senses of `session_id` - in practice

Every analysis tool takes a `session_id="default"` kwarg. This is the
**tool session** (problem cache container). It is unrelated to the
**provenance session** that `start_session` creates.

```python
# Pseudocode for an OAS workflow:

# 1. Open a provenance session. This writes "sess-abc123" into the
#    middleware's module-level _server_session_id.
sess = await start_session(notes="trade study")
# sess["session_id"] == "sess-abc123"

# 2. The kwarg you pass here is the TOOL session (problem cache key).
#    Whether you pass "default" or "wing-A" does not affect provenance
#    grouping - that's already locked to sess-abc123 by the call above.
surf = await create_surface(name="wing", wing_type="CRM", num_y=7,
                            session_id="default")

# 3. The captured tool call is recorded under sess-abc123, regardless
#    of the session_id kwarg on the analysis tool.
res = await run_aero_analysis(surfaces=["wing"], alpha=5.0,
                              velocity=248.136, Mach_number=0.84,
                              density=0.38, reynolds_number=1e6,
                              session_id="default")
# res["_provenance"]["session_id"] == "sess-abc123"

# 4. Export the DAG for sess-abc123.
g = await export_session_graph(session_id=sess["session_id"],
                               output_path="dag.json")
```

If you skip step 1 (no `start_session`), every captured call lands in
the server's auto-created startup session (`auto-XXXX`). The viewer
still shows it; it just is not named.

Past bug: a ContextVar shadowing issue caused `start_session()` to be
silently ignored, with every call landing in the auto session. Fixed
2026-05-14. If you see `export_session_graph(sess-...)` return 0 nodes
today, the running server has stale code - restart it. Regression test
at `packages/sdk/tests/test_provenance.py::test_start_session_overrides_startup_seeded_default`.

## Chaining `prior_call_id`

Every successful tool call returns a `_provenance` field:

```json
{ "results": {...},
  "_provenance": {"call_id": "uuid-...", "session_id": "sess-..."} }
```

Pass that `call_id` as `prior_call_id` when you call `log_decision` for
the result interpretation - this is what wires the causal edge in the
DAG (`tool_call -> decision (informs)`). Without it, the decision sits
disconnected from the analysis that prompted it.

```python
res = await run_aero_analysis(...)
await log_decision(
    decision_type="result_interpretation",
    reasoning=f"CL={res['results']['CL']:.3f}, L/D={res['results']['L_over_D']:.1f}; reasonable",
    selected_action="proceed to optimisation",
    prior_call_id=res["_provenance"]["call_id"],
)
```

## When to call `reset`

`reset` clears all in-memory tool session state (surfaces, cached
OpenMDAO problems) for a given tool session. It does NOT clear
provenance - those rows stay in the DB.

Use it:
- Between unrelated experiments that would otherwise collide on tool
  session names like `"default"`.
- After changing a `create_surface` parameter set substantially and
  wanting to make sure no stale cached problem is in play.
- Almost never inside one workflow. The cache is the point.
