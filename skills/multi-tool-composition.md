# Multi-Tool Composition

How to compose multiple Hangar analysis tools into integrated workflows.
There are two routes:

1. **Declarative (preferred when it fits): an omd plan with slots.** One
   YAML plan composes OAS drag, pyCycle propulsion, and parametric weight
   models inside an OpenConcept mission; omd materializes and solves the
   coupled problem in a single OpenMDAO model. See
   `omd-cli-guide/slots-and-fidelity.md`.
2. **Agent-orchestrated handoffs.** Each tool server runs independently;
   the agent reads results from one tool and passes them as inputs to
   another. Use this when the coupling you need has no slot provider, or
   when the tools genuinely run as separate studies.

## When to use

Use this skill when:
- An analysis requires results from multiple tool servers
- The user wants to chain aerodynamic, structural, propulsion, or mission analyses
- A design study needs to combine metrics from different disciplines
- You need to decide between an omd slot plan and manual handoffs

## Current tool servers

| Server | Package | CLI | Key outputs |
|--------|---------|-----|-------------|
| OAS | `hangar.oas` | `oas-cli` | CL, CD, L/D, fuelburn, structural_mass |
| OpenConcept | `hangar.ocp` | `ocp-cli` | fuel_burn_kg, OEW_kg, MTOW_kg, mission profiles |
| pyCycle | `hangar.pyc` | `pyc-cli` | TSFC, Fn, OPR, flow stations |
| omd | `hangar.omd` | `omd-cli` | plan runner composing all of the above |

## Route 1: omd slot composition (declarative)

OCP mission components in an omd plan declare provider slots (`drag`,
`propulsion`, `weight`); each slot substitutes a higher-fidelity model from
another tool inside the mission solver:

```yaml
components:
- id: mission
  type: ocp/BasicMission
  config:
    aircraft_template: caravan
    architecture: turboprop
    num_nodes: 11
    mission_params: { mission_range_NM: 250, cruise_altitude_ft: 18000 }
    slots:
      drag:
        provider: oas/vlm        # OAS VLM drag instead of parabolic polar
        config: { num_x: 2, num_y: 7, num_twist: 4 }
```

Available providers: `oas/vlm`, `oas/vlm-direct`, `oas/aerostruct` (drag);
`pyc/turbojet`, `pyc/hbtf`, `pyc/surrogate` (propulsion);
`ocp/parametric-weight` (weight).

Why prefer this route when a slot provider exists:
- The coupling is solved by OpenMDAO (Newton/NLBGS) instead of a manual
  fixed-point loop driven by the agent
- One run, one run_id, one provenance record, one set of plots
- Surrogate vs direct-coupled fidelity is an explicit per-slot choice

The full provider table, surrogate-vs-direct trade-offs, and the
`pyc/surrogate` deck configuration are in
`omd-cli-guide/slots-and-fidelity.md`. Solver guidance for combined slots
(at least one direct-coupled provider when mixing drag + propulsion;
NLBGS for dual-surrogate) lives there too.

## Route 2: agent-orchestrated handoffs

Each Hangar tool server is an independent MCP server with its own session
state, provenance tracking, and artifact storage. Tools do not share an
OpenMDAO problem. The agent (Claude) is the integration layer, reading
results from one tool and passing them as inputs to another.

```
Agent (Claude)
  |
  +-- OAS server (aerostruct analysis)
  |     create_surface -> run_aerostruct_analysis -> CD, structural_mass
  |
  +-- pyCycle server (engine sizing)
  |     run_design_point(Fn=drag) -> TSFC, engine deck
  |
  +-- OpenConcept server (mission)
        run_mission_analysis -> fuel_burn_kg, range margins
```

The MCP-specific mechanics (tool prefixes, `link_cross_tool_result`,
session strategy across servers) are in `hangar-mcp-guide/cross-tool.md`.

### Pattern 1: Sequential handoff

Run one tool, extract results, feed into the next.

```
1. OAS: run_aerostruct_analysis -> get CD, structural_mass, fuelburn
2. Extract: drag = CD * q * S_ref
3. Log handoff decision (required -- see below)
4. pyCycle: run_design_point sized for thrust_required = drag * safety_margin
5. OpenConcept: run_mission_analysis with the engine deck and empty weight
```

**Required:** Before each tool-to-tool handoff, log a decision:
```
log_decision(
    decision_type="tool_handoff",
    reasoning="OAS aerostruct results: CD=0.032, structural_mass=27200 kg.
               Extracting drag force = CD * q * S_ref = 45.2 kN for propulsion sizing.
               Units: force in Newtons, mass in kg.",
    selected_action="Pass drag=45.2 kN to pyCycle as thrust requirement",
    prior_call_id=<oas_analysis_call_id>
)
```

Key: clearly identify the interface variables and their units.

### Pattern 2: Iterative coupling

When tools have circular dependencies (e.g. drag depends on weight, weight
depends on engine size, engine size depends on drag):

```
1. Initialize: assume engine_weight = 5000 kg
2. OAS: run with W0 including engine_weight -> get drag, fuelburn
3. pyCycle: size engine for drag -> get new engine_weight
4. Check: has engine_weight converged? (|new - old| < tolerance)
5. If not, log handoff decision (required) and go to step 2
6. If yes, log convergence decision (required) and record final state
```

**Required:** At convergence (step 6), log a decision:
```
log_decision(
    decision_type="coupling_convergence",
    reasoning="Weight-drag coupling converged in 4 iterations.
               Final engine_weight=4820 kg, delta=12 kg (<1% tolerance).
               Drag=44.8 kN, fuelburn=12340 kg.",
    selected_action="Accept converged state; proceed to reporting",
    confidence="high"
)
```

Typically converges in 3--5 outer iterations for weight-drag coupling.
If the same coupling exists as an omd slot (e.g. wing weight from
`oas/aerostruct` feeding `ocp/parametric-weight`), prefer Route 1 and let
the mission solver close the loop.

### Pattern 3: Parallel independent analyses

When tools provide independent metrics that are combined in a comparison:

```
1. OAS: compute drag polar -> aero metrics
2. pyCycle: run_design_point at candidate thrust levels -> engine metrics
3. OpenConcept: run_mission_analysis per candidate -> fuel/range metrics
4. Combine all metrics in a single comparison table
```

### Pattern 4: Sensitivity cascade

Vary a parameter in one tool and propagate the effect through others:

```
For each span in [25, 30, 35, 40] m:
  1. OAS: analyze wing at this span -> CD, mass
  2. pyCycle: size engine for CD -> engine_mass, sfc
  3. OpenConcept: run mission -> range_nm
  Record: {span, CD, mass, engine_mass, range}
```

For a cascade like this, also consider one omd plan with the swept
parameter as a design variable or per-run config: each sweep point becomes
`omd-cli run` on a plan variant, and the coupling inside each point is
solved rather than hand-iterated.

## Provenance across tools

Each tool server maintains its own provenance. For cross-tool studies:

1. Start a session in each tool server involved
2. **Required:** Log a decision at every tool-to-tool handoff and at coupling
   convergence (see patterns above for templates). At minimum:
   - `decision_type="tool_handoff"` before passing data between tools
   - `decision_type="coupling_convergence"` when iterative loops converge
   - `decision_type="result_interpretation"` when combining results from
     independent analyses (Pattern 3)
3. Reference `prior_call_id` from the source analysis in each handoff decision
4. Use `link_cross_tool_result` to register the cross-reference so the
   viewer can draw cross-server edges
5. Export each tool's provenance graph separately

An omd slot run needs none of this: the composition is one plan, one run,
one provenance record.

## Interface variable conventions

When passing data between tools, use consistent units:

| Variable | Units | Source tool | Consumer tool |
|----------|-------|------------|---------------|
| CD, CL | dimensionless | OAS | OpenConcept, pyCycle |
| drag force | N | OAS (CD * q * S) | pyCycle (thrust target) |
| structural mass | kg | OAS aerostruct | OpenConcept (empty weight) |
| fuel burn | kg | OpenConcept | comparisons, Breguet cross-checks |
| Fn (thrust) | lbf | pyCycle | OpenConcept (engine sizing) |
| TSFC | lbm/hr/lbf | pyCycle | OpenConcept (mission fuel) |
| MTOW, W0 | kg | OpenConcept | OAS aerostruct (W0 input, in kg not N) |

OAS speaks SI; pyCycle speaks imperial; OpenConcept is mixed depending on
the template. Unit mismatches are the most common bug class in cross-tool
studies -- state units in every handoff decision.

## Adding a new tool to the composition

1. Create the tool package: `packages/<toolname>/`
2. Define the tool's MCP interface (inputs, outputs, units)
3. Document the interface variables in the tool's skills
4. To make it composable inside missions, add an omd slot provider
   (`packages/omd/src/hangar/omd/slots.py`) and an omd factory
5. See the `new-tool` skill for the full scaffolding guide
