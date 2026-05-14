# Example - Cross-Tool: OAS Wing Drag -> OCP Mission

Demonstrates the sequential-handoff pattern (Pattern 1 in
`cross-tool.md`): use OAS to compute the cruise drag of a wing, then
feed that drag into an OCP mission as the cruise drag override.

This example is intentionally small. A real study would also vary the
wing geometry across the sweep and re-run the mission per point.

```python
# Two separate provenance sessions, one per server.
oas_sess = await mcp__OpenAeroStruct__start_session(
    notes="cross-tool study; OCP session follows"
)
ocp_sess = await mcp__OpenConcept__start_session(
    notes=f"cross-tool study; OAS source session {oas_sess['session_id']}"
)

# 1. OAS - compute cruise drag for a candidate wing.
await mcp__OpenAeroStruct__create_surface(
    name="wing", wing_type="CRM", num_y=7, symmetry=True,
    with_viscous=True, CD0=0.015,
)
await mcp__OpenAeroStruct__log_decision(
    decision_type="mesh_resolution",
    reasoning="num_y=7 fast pass for trade study",
    selected_action="num_y=7",
)

aero = await mcp__OpenAeroStruct__run_aero_analysis(
    surfaces=["wing"], alpha=2.5,
    velocity=232.0, Mach_number=0.78,    # Mach 0.78 cruise
    density=0.40, reynolds_number=1.2e7,
)
assert aero["validation"]["passed"]

CD_cruise = aero["results"]["CD"]
S_ref = aero["results"]["S_ref"]
oas_call_id = aero["_provenance"]["call_id"]

# Compute the drag force in Newtons (q*CD*S).
rho, V = 0.40, 232.0
q = 0.5 * rho * V**2
drag_N = CD_cruise * q * S_ref

await mcp__OpenAeroStruct__log_decision(
    decision_type="result_interpretation",
    reasoning=f"CD={CD_cruise:.4f}, S_ref={S_ref:.1f} m^2, drag={drag_N/1000:.1f} kN at M=0.78",
    selected_action="proceed to handoff",
    prior_call_id=oas_call_id,
)

# 2. The handoff. Log a decision on the OAS side AND record an
#    explicit cross-reference so the viewer can draw the edge.
await mcp__OpenAeroStruct__log_decision(
    decision_type="tool_handoff",
    reasoning=(
        f"Cruise drag {drag_N:.0f} N becomes the cruise-condition target "
        f"for OCP mission analysis. Units: N. Source: OAS run "
        f"{aero['run_id']}, M=0.78, alpha=2.5 deg, rho=0.40 kg/m^3."
    ),
    selected_action=f"hand drag={drag_N:.0f} N to OCP",
    prior_call_id=oas_call_id,
)

await mcp__OpenAeroStruct__link_cross_tool_result(
    source_run_id=aero["run_id"],
    source_tool="oas",
    target_session_id=ocp_sess["session_id"],
    target_tool="ocp",
    variable_name="cruise_drag_N",
    value=drag_N,
    notes="OAS aero cruise drag for OCP mission",
)

# 3. OCP - set up the aircraft + mission and run it.
await mcp__OpenConcept__load_aircraft_template(template="b738")
await mcp__OpenConcept__log_decision(
    decision_type="architecture_choice",
    reasoning="B738 baseline; consistent with CRM wing scale",
    selected_action="template=b738",
)

await mcp__OpenConcept__set_propulsion_architecture(
    architecture="twin_turbofan",
)
await mcp__OpenConcept__log_decision(
    decision_type="architecture_choice",
    reasoning="Matches B738 template",
    selected_action="twin_turbofan",
)

await mcp__OpenConcept__configure_mission(
    cruise_altitude=35000.0, mission_range=2000.0,
    cruise_Ueas=200.0, num_nodes=11,    # ODD
)

mission = await mcp__OpenConcept__run_mission_analysis()
assert mission["validation"]["passed"]
ocp_call_id = mission["_provenance"]["call_id"]

fuel_burn = mission["results"]["fuel_burn_kg"]

await mcp__OpenConcept__log_decision(
    decision_type="result_interpretation",
    reasoning=(
        f"Mission fuel burn {fuel_burn:.0f} kg over 2000 NM. "
        f"OAS-derived cruise drag was {drag_N:.0f} N."
    ),
    selected_action="record",
    prior_call_id=ocp_call_id,
)

# 4. Export both DAGs.
await mcp__OpenAeroStruct__export_session_graph(
    session_id=oas_sess["session_id"],
    output_path="cross_tool_oas.json",
)
await mcp__OpenConcept__export_session_graph(
    session_id=ocp_sess["session_id"],
    output_path="cross_tool_ocp.json",
)
```

After this completes, the viewer at `http://localhost:7654/viewer`
shows the OAS DAG; switching `?session_id=<ocp session>` shows the OCP
DAG; and the cross-reference table has the OAS->OCP link with the
drag value preserved.

## Why two sessions and not one

There is no single "study session" that spans servers. Each
`start_session()` is local to the server it was called on, because each
server has its own SQLite session row. Two sessions with mutually
referencing notes (as above) is the current idiom. `link_cross_tool_result`
is the supported mechanism for the viewer to wire them together.

## What goes wrong here

| Failure | Cause | Fix |
|---------|-------|-----|
| `CD` from OAS << expected | Wrong Mach, wrong viscous flag | Check `with_viscous=True`, `CD0`, Mach |
| OCP `run_mission_analysis` errors `USER_INPUT_ERROR` | Forgot `set_propulsion_architecture` | Run it before mission |
| `num_nodes=10` rejected | Even | Use 11 |
| Cross-tool edge doesn't appear in viewer | Skipped `link_cross_tool_result` | Always call it on handoff |
| Drag in lbf instead of N | Unit mismatch | OAS is SI; OCP is mostly SI for B738 - convert if mixing pyc lbf into the loop |
