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

**Status: PARTIAL** (mechanism works, full mission convergence needs work)

Completed:
- OCP factory now declares `"propulsion"` slot alongside `"drag"`
- Propulsion slot check added before the existing propulsion code block
  in `_make_aircraft_model_class()`
- `pyc/turbojet` provider registered in `slots.py` using
  `_PyCycleTurbojetDirect` -- builds a pyCycle multipoint problem
  (1 design + nn off-design) and runs all points in a single solve
- Component works correctly in isolation: 22s for 11 nodes, physically
  reasonable thrust (10-44 kN) and fuel flow (0.2-1.3 kg/s)
- Three-lane example structure in `examples/ocp_pyc_coupled/`

Remaining:
- **Newton convergence in OCP mission**: The ExplicitComponent+FD
  approach is architecturally wrong. pyCycle is a Group with implicit
  balance components and its own Newton solver. Wrapping it as
  ExplicitComponent hides the internal solver from the outer Newton,
  and FD partials through a nested Newton are noisy by nature (FD step
  1e-4 vs cycle convergence tolerance 1e-6).

  The fix is **native Group integration** -- add pyCycle Turbojet
  instances directly as OpenMDAO subsystems (like `_DirectVLMDragGroup`
  does with nn VLM instances). pyCycle's element-level
  `compute_partials` then propagate through the linear solver chain,
  giving the outer Newton a clean Jacobian.

  Implementation plan (in progress):
  `_DirectPyCyclePropGroup` (om.Group) wraps MPTurbojet with nn
  off-design Turbojet instances. Slicer/Gatherer pattern from VLM
  direct handles (nn,) vectorization. Alt/MN connections to FC work
  (verified data reaches `readAtmTable.alt`), and Fn_target connects
  correctly to the off-design balance.

  Current blocker: the off-design Newton converges to wrong solutions
  when MPTurbojet is embedded inside the Group. The standalone
  `build_multipoint_problem` works correctly for the same conditions.
  Root cause is likely initial-guess propagation -- the `set_input_defaults`
  from MPTurbojet's setup and the `apply_initial_guesses` calls may
  conflict with how the outer Group resolves promoted paths.

  Next steps:
  1. Debug initial-guess flow: compare `prob[path]` for all balance
     variables (FAR, W, Nmech, fc Pt/Tt) between standalone
     `build_multipoint_problem` and Group-embedded MPTurbojet right
     after setup, before run_model. The difference will pinpoint
     which guesses are lost during embedding.
  2. May need to call `set_val` on absolute paths (not promoted) for
     the balance outputs -- promotion through nested Groups can lose
     values when `set_input_defaults` and `set_val` interact.
  3. Consider overriding `guess_nonlinear()` on the Turbojet class
     to apply guesses inside the Newton solve loop rather than
     relying on one-time set_val before run_model.
  4. Add variable scaling (`ref`/`ref0`) for thrust, fuel_flow,
     throttle to improve conditioning.

  Architecture observations from review:
  - pyCycle's FlightConditions promotes `alt` (from Ambient) and `MN`
    (from FlowStart) as Group inputs -- they ARE connectable. The
    auto_ivc issue does NOT apply here. Connections from slicers to
    `cycle.OD_{i}.fc.alt` and `cycle.OD_{i}.fc.MN` are accepted and
    data reaches the atmosphere model (verified via get_val).
  - The off-design Turbojet balance variables (FAR val=0.3, Nmech
    val=1.5) have terrible defaults. The standalone builder fixes
    this by calling `_apply_turbojet_od_guesses` after setup. When
    embedded in a Group, `apply_initial_guesses()` tries to do the
    same via `prob.set_val()`, but the balance outputs may already be
    at wrong values from a previous Group-level default resolution.
  - Key diagnostic: standalone OD converges to FAR=0.0166, W=47,
    Nmech=7679. Group-embedded converges to FAR=0.003, W=58,
    Nmech=5854. The W and Nmech are in the right ballpark but FAR
    is 5x too low, suggesting the FAR guess didn't propagate.
  - pyCycle MCP server timing: design point ~4s, off-design ~3-6s.
    The multipoint approach (all nn in one solve) takes ~22s for
    nn=11, so amortized cost is ~2s/node -- acceptable for mission
    analysis if the convergence issue is resolved.

  Additional gaps to address:
  - Only turbojet archetype implemented (HBTF, turbofan, turboshaft
    params exist in defaults.py but no archetype classes)
  - Design variables (comp_PR, eff, Nmech) not exposed through slot
  - No engine weight estimation
  - T4, OPR, flow station details not surfaced through slot interface
- Parity test blocked on mission convergence


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
