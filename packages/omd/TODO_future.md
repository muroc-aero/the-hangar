# omd Future Work

## Unit Consistency Review

Audit how units flow through the full pipeline: plan YAML authoring,
materialization, execution, result extraction, and display. The risk is
that an agent or user specifies a value in one unit system in the plan
but the factory or OpenMDAO expects a different unit, causing silent
incorrect results rather than an error.

Areas to review:

1. **Plan YAML has no unit declarations.** Operating points values
   (velocity, rho, alpha, re) are bare numbers with no units field.
   The factories assume SI (m/s, kg/m^3, deg, 1/m) but the plan schema
   does not enforce or document this. An agent writing velocity=248 could
   mean m/s or knots. The catalog YAML files have unit annotations but
   they are reference data, not validated against plan values.

2. **OCP mission params mix unit systems.** The OCP factory accepts
   cruise_altitude_ft (ft), mission_range_NM (NM), climb_vs_ftmin
   (ft/min), climb_Ueas_kn (kn). These are converted internally via
   OpenMDAO's set_val() with explicit units. But if someone passes
   cruise_altitude in meters thinking the suffix "_ft" is just a name,
   the analysis runs with wrong values silently.

3. **Result extraction and display.** The run.py summary extracts values
   from prob.get_val() sometimes with units (OCP: `units="kg"`) and
   sometimes without (OAS: bare get_val). The results printed to terminal
   and stored in the DB should always include units so downstream
   consumers know what they are looking at.

4. **Design variables and constraints.** The plan schema supports a
   `units` field on DVs and constraints but it is optional and most
   examples omit it. When present, it should be passed to
   prob.model.add_design_var(units=...). Check whether the materializer
   does this.

5. **Cross-tool unit interfaces.** When OAS outputs (SI) feed into OCP
   inputs (mixed imperial/SI via OpenConcept conventions), unit
   conversion must happen at the boundary. The slot system handles this
   via OpenMDAO's internal unit conversion (promotes with compatible
   units), but explicit connections in composite plans may not.

Recommendations:
- Add a `units` field to operating_points in the plan schema (optional
  but recommended, validated against known unit strings)
- Add range-safety heuristic checks: warn if velocity > 500 (probably
  knots not m/s), warn if altitude > 50000 (probably feet not meters)
- Ensure the materializer passes DV/constraint `units` to OpenMDAO
- Add units to result summary output and DB storage
- Document the assumed unit system for each component type in the catalog


## Decision Logging in omd-cli-guide Skill

The omd-cli-guide skill has a "Decision Logging (Required)" section with a
table of when to log decisions and a decisions.yaml format example. But the
guidance is not concrete enough for agents to follow reliably. Problems:

1. The table says "After choosing mesh/fidelity" and "After each analysis
   run" but does not show the exact CLI or file workflow for recording a
   decision in a plan-based (non-MCP) workflow. Agents need to know: write
   an entry in decisions.yaml, then re-assemble the plan.

2. The lane_c task prompts say "record a result interpretation decision"
   but the skill does not explain what a good vs bad decision entry looks
   like. Add concrete examples: a good interpretation that notes specific
   values and physics reasoning, vs a vague one that just says "looks ok."

3. The skill does not explain the difference between decisions.yaml entries
   (recorded at plan authoring time, persisted in the plan store) and
   `log_decision()` MCP tool calls (recorded in the SDK provenance DB
   during interactive sessions). Agents need to know which mechanism to
   use depending on whether they are in CLI or MCP mode.

4. The decision types (formulation_decision, result_interpretation,
   dv_selection, convergence_assessment, replan_reasoning) need short
   descriptions of what each one means and when it fires. The current
   table is a start but agents skip it because the "When" column is too
   terse.

Update the skill to include:
- A step-by-step workflow for decision logging in CLI mode
- Before/after examples of decision entries (good vs insufficient)
- Clear distinction between decisions.yaml and log_decision() MCP tool
- A checklist agents can follow: "before running, log formulation;
  after running, log interpretation; before optimizing, log dv_selection;
  after optimizing, log convergence_assessment"


## Direct-Coupled OAS Drag Slot Provider

The current `oas/vlm` slot provider uses OpenConcept's `VLMDragPolar`,
which pre-trains a surrogate at initialization and interpolates at runtime.
The full VLM never runs inside the Newton loop. This is surrogate-coupled,
not direct-coupled.

Build a new slot provider (`oas/vlm-direct` or similar) that wraps raw OAS
aero groups (Geometry + AeroPoint) and runs the VLM solver at every Newton
iteration. This would be true tight coupling in the MDO sense.

Considerations:
- Performance: VLM per-node per-iteration will be slow for high node counts.
   May need to limit to coarse meshes or low node counts for practical use.
- Interface: the provider must accept the same flight condition promotes as
   VLMDragPolar (`fltcond|CL`, `fltcond|M`, `fltcond|h`, `fltcond|q`) and
   produce `drag` output, but internally it builds an OAS AeroPoint that
   takes velocity/alpha/Mach/rho and computes forces. The mapping between
   OCP flight condition variables and OAS inputs needs careful handling.
- Derivatives: OAS provides analytic partials, so gradient-based optimization
   through the direct-coupled path is possible. This is the main advantage
   over surrogate coupling for optimization problems.
- The `oas/aerostruct` slot provider has the same surrogate limitation
   (uses `AerostructDragPolar`). A direct-coupled aerostruct provider would
   also be valuable.

Create an example `ocp_oas_direct/` with three lanes once the provider
works. The parity test should compare against the surrogate-coupled result
and document the accuracy/performance tradeoff.


## P3: pyCycle Propulsion Slot

Implement a `pyc/turbojet` slot provider in `slots.py` that replaces OCP's
TurbopropPropulsionSystem with a pyCycle thermodynamic model. The provider
callable signature matches the existing pattern:
`(nn, flight_phase, config) -> (component, promotes_in, promotes_out)`.

Steps:
1. Add `"propulsion"` to the OCP factory's `declared_slots` metadata
2. Implement propulsion slot consumption in the OCP aircraft model's setup(),
   alongside the existing drag slot pattern (lines 520-531 in ocp.py)
3. Write the `_pyc_turbojet_provider()` function in `slots.py` with
   `removes_fields` (OCP propulsion fields like `ac|propulsion|engine|rating`)
   and `adds_fields` (pyCycle-specific params)
4. Register with `register_slot_provider("pyc/turbojet", ...)`
5. Create example `ocp_pyc_coupled/` with three lanes (raw Python, plan YAML,
   agent prompt) and a parity test

This proves the slot pattern generalizes beyond drag to propulsion, and beyond
OAS to pyCycle. A future OAS factory could similarly declare slots (e.g.,
`"viscous_model"`) using the same pattern.


## P4: Component Catalog System

Expand `catalog/oas/` (which has AeroPoint.yaml and AerostructPoint.yaml)
into a full component catalog covering all registered component types and
slot providers.

New catalog entries needed:
- `catalog/ocp/BasicMission.yaml`
- `catalog/ocp/FullMission.yaml`
- `catalog/ocp/MissionWithReserve.yaml`
- `catalog/pyc/Turbojet.yaml`
- `catalog/slots/oas_vlm.yaml`
- `catalog/slots/oas_aerostruct.yaml`

Each entry should include:
- `type`: component type string matching the factory registry
- `inputs`: schema with types, units, defaults, descriptions
- `outputs`: with units and descriptions
- `recommended_solvers`, `recommended_dvs`, `recommended_constraints`
- `known_issues`: list of gotchas
- `available_slots`: which slots this component declares (for slot-aware types)

The range-safety structural validator already loads from `catalog/` via
`_load_catalog()`. Extend the validator to:
- Validate OCP-specific config fields (architecture, mission_params) using
  catalog schemas
- Validate pyCycle-specific config fields
- Cross-check slot provider config against catalog slot provider entries

Consider whether the catalog replaces or supplements factory-provided
`var_paths` from P2. The catalog is reference data for plan authoring
(what agents read), while var_paths are runtime data for the materializer.
Both may be needed.
