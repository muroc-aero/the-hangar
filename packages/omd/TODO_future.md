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

**Status: DONE**

Implemented `oas/vlm-direct` slot provider in `slots.py`. Uses OpenConcept's
`VLM` group (atmosphere + AeroPoint) per node with a shared
`TrapezoidalPlanformMesh`. A `BalanceComp` with nn residuals drives alpha
to match OCP's `fltcond|CL`, solved by the parent Newton.

Key details:
- `_DirectVLMDragGroup`: nn independent VLM instances, shared twisted mesh,
  `_NodeSlicer`/`_NodeGatherer` helper components for vectorization
- Converges in 2 Newton iterations (~30s total for nn=11, num_y=5)
- Fuel burn within 0.01% of surrogate-coupled (`oas/vlm`) result
- Three-lane example in `examples/ocp_oas_direct/` with parity test
- The `oas/aerostruct` direct-coupled variant is a natural extension


## Multi-Component Composition Open Questions

**Status: DONE** (core items implemented)

Completed:
- **drag_source: external** -- OCP factory now checks
  `slots.drag_source` and skips adding any drag component when set to
  `"external"`, leaving drag to be supplied via explicit connections in
  a composite plan.
- **Solver scoping** -- `_configure_solvers()` now accepts a list of
  solver specs, each with an optional `target` path. The materializer
  resolves targets via `prob.model._get_subsystem()` after setup.
  Backward compatible with the existing single-dict format.
- **Connection unit validation** -- `_validate_connection_units()` runs
  after setup for composite problems, warning when explicit connections
  have incompatible units via OpenMDAO's unit system.


## P3: pyCycle Propulsion Slot

**Status: DONE** (both surrogate and direct paths working)

Completed:
- OCP factory declares `"propulsion"` slot alongside `"drag"`
- Propulsion slot check in `_make_aircraft_model_class()`
- Three-lane example structure in `examples/ocp_pyc_coupled/`

**Path 1 (surrogate-coupled):** `pyc/surrogate` slot provider
- `hangar.omd.pyc.surrogate` module: deck generation, save/load, MetaModel
- `generate_deck()` runs pyCycle off-design across (alt, MN, throttle) grid
- Individual point evaluation for robustness (one failed point doesn't kill chunk)
- `PyCycleSurrogateGroup` wraps `MetaModelUnStructuredComp` with Kriging
- Supports both turbojet and HBTF archetypes
- Pre-computed decks via `save_deck()`/`load_deck()` for fast startup
- No convergence risk at mission level (smooth surrogate)

**Path 2 (direct-coupled):** `pyc/turbojet` and `pyc/hbtf` slot providers
- `_DirectPyCyclePropGroup` wraps MPTurbojet with slicer/gatherer pattern
- `_DirectPyCycleHBTFPropGroup` wraps MPHbtf with T4 throttle mapping

Root causes of convergence blocker (all fixed):
1. **Execution order**: cycle was added before slicers, so OD points
   ran with default inputs. Fixed by reordering: slicers first, then cycle.
2. **FC balance guesses**: `fc.balance.Pt` and `fc.balance.Tt` were not
   included in `guess_nonlinear`. Without these, the FlightConditions
   sub-solver diverges.
3. **Path naming**: `apply_initial_guesses` used `fc.conv.balance.Pt`
   (from hangar.pyc) but correct path is `fc.balance.Pt`.
4. **Promotion handling**: pathname-based paths failed when group was
   promoted. Fixed with try/fallback approach.
5. **Unit conversion**: ExecComp passthrough with mismatched units.
   Fixed by using same units on input and output, letting OpenMDAO
   convert at connection boundaries.

All 6 engine archetypes available in `hangar.omd.pyc`: turbojet, hbtf,
ab_turbojet, single_spool_turboshaft, multi_spool_turboshaft, mixedflow_turbofan.
`guess_nonlinear` added to Turbojet and HBTF for embedded convergence.

Remaining:
- Full OCP mission convergence test (outer Newton driving throttle/CL
  with pyCycle in the loop) not yet validated -- standalone slot tests pass
- Design variables (comp_PR, eff, Nmech) not exposed through slot
- No engine weight estimation
- T4, OPR, flow station details not surfaced through slot interface


## P4: Component Catalog System

**Status: DONE**

Completed:
- `catalog/ocp/BasicMission.yaml` -- inputs, outputs, available_slots, known_issues
- `catalog/ocp/FullMission.yaml` -- extends BasicMission with takeoff
- `catalog/ocp/MissionWithReserve.yaml` -- extends with reserve/loiter
- `catalog/pyc/Turbojet.yaml` -- design conditions, component params, thermo_method
- `catalog/slots/oas_vlm.yaml` -- surrogate-coupled, with performance notes
- `catalog/slots/oas_vlm_direct.yaml` -- direct-coupled, analytic partials
- `catalog/slots/oas_aerostruct.yaml` -- surrogate aerostructural
- `catalog/slots/pyc_turbojet.yaml` -- direct pyCycle with known issues
- Range-safety structural validator extended with:
  - OCP num_nodes odd check
  - OCP aircraft_template validation against known templates
  - OCP architecture validation against known architectures
  - pyCycle T4_target limit check (> 3600 degR warning)
