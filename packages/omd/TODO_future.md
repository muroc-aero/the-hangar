# omd Future Work

## Unit Consistency Review

**Status: DONE** (core items implemented)

Completed:
- Plan schema now accepts `{value: ..., units: ...}` objects in
  operating_points alongside bare numbers (backward compatible)
- Materializer passes `units` from DV/constraint/objective config to
  OpenMDAO's `add_design_var()`, `add_constraint()`, `add_objective()`
- Range-safety heuristics warn on likely unit confusion: velocity > 500
  (probably knots), altitude > 50000 (probably feet), OCP mission_params
  with suspiciously low cruise_altitude_ft or high mission_range_NM
- OAS result extraction uses explicit units (structural_mass in kg,
  S_ref in m^2); OCP already used explicit units
- Unit conventions documented in omd-cli-guide skill

Remaining (lower priority):
- Cross-tool unit interfaces: when OAS outputs (SI) feed into OCP
  inputs (mixed imperial/SI via OpenConcept conventions), unit
  conversion must happen at the boundary. The slot system handles this
  via OpenMDAO's internal unit conversion, but explicit connections in
  composite plans may not validate unit compatibility.


## Decision Logging in omd-cli-guide Skill

**Status: DONE**

The omd-cli-guide skill now includes:
- CLI vs MCP mechanism table (decisions.yaml vs log_decision())
- Step-by-step CLI workflow for when to write decision entries
- Agent checklist (before/after analysis, before/after optimization, on replan)
- Good vs insufficient decision entry examples with explanation
- Expanded decision type descriptions with specific guidance on what to log


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


## Multi-Component Composition Open Questions

The multi-component materializer (`_materialize_composite`) works for
side-by-side components and the slot system handles intra-component
substitution. These open questions remain for more complex compositions:

- **OCP drag_source: external** -- The OCP aircraft model always adds
  PolarDrag internally. Replacing it via explicit inter-component
  connections (not slots) requires either a config flag the factory
  respects, or post-setup connection overrides. The slot system already
  solves this for the surrogate-coupled case.
- **Solver scoping** -- When two tools are composed, which Group gets
  the Newton solver? The plan YAML `solvers:` section currently targets
  the top-level model or the coupled group. Supporting solver targeting
  for specific subsystems (e.g., `solvers.target: mission.coupled`)
  would be needed for complex compositions.
- **Variable promotion conflicts** -- OAS and OCP both promote
  `fltcond|*` at different levels. The materializer uses no promotions
  for composite components (each lives under its namespace), but
  explicit connections need fully-qualified paths.


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
