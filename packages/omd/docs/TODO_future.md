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
- No engine weight estimation
- T4, OPR, flow station details not surfaced through slot interface


## P5: Three-Tool Composition (OCP + OAS + pyCycle)

**Status: PARTIAL** (factory builds, convergence blocked)

Goal: validate that both OCP slots (drag + propulsion) can be filled
simultaneously in a single mission.

Completed:
- Factory builds without errors when both slots are provided
- Field removal sets are disjoint (no conflicts)
- Example in `examples/ocp_three_tool/` (lane_b plan, lane_c prompt)
- `TestThreeToolMission::test_three_tool_factory_builds` passes

Blocked:
- **Dual-surrogate convergence**: VLM surrogate drag + pyCycle surrogate
  propulsion together produce a singular Jacobian in the DirectSolver.
  Both surrogates provide FD-based partials that make the Newton system
  ill-conditioned. The test is marked xfail.
- Potential fixes: (a) use NLBGS instead of Newton, (b) use direct-coupled
  VLM drag (`oas/vlm-direct`) instead of surrogate (analytic partials),
  (c) use direct-coupled pyCycle (`pyc/turbojet`) instead of surrogate.
  Options b and c validated independently in two-tool tests.


## P6: Full OCP Mission Convergence with Direct pyCycle

**Status: DONE**

Goal: prove that the outer OCP Newton can drive throttle while pyCycle's
inner Newton converges inside a full BasicMission (climb/cruise/descent).

Completed:
- Surrogate mission convergence test passes (4 min, mostly deck generation).
  Requires engine designed near cruise conditions and grid covering the
  full flight envelope.
- **Direct turbojet mission convergence test passes (24 sec)**. This proves
  the outer Newton can drive throttle while pyCycle's inner Newton converges.
  TABULAR thermo, 3 nodes, Caravan at 18000 ft.
- Weight model fix: OEW passthrough when propulsion slot is active.
- OEW values added to all aircraft templates (caravan, kingair, tbm850).


## P7: Per-Phase Profile Extraction

**Status: DONE**

Goal: extract per-phase arrays (altitude, speed, Mach, thrust, drag,
fuel flow, weight) from solved OCP missions, not just scalar summaries.

Completed:
- `_OCP_PROFILE_VARS` constant maps output keys to (variable, units) tuples
- `_extract_ocp_profiles()` helper extracts arrays for all phases
- Integrated into `_extract_ocp_summary()` and `_extract_composite_summary()`
- `summary["profiles"][phase]` contains lists keyed by altitude_m, velocity_ms,
  mach, thrust_kN, drag_N, fuel_flow_kgs, weight_kg
- Test: `test_ocp_profile_extraction` verifies per-phase arrays


## P8: Design Variable Exposure Through Slots

**Status: DONE**

Goal: slot providers declare their internal design variables so the
optimizer can see them. The OCP factory collects slot DVs into var_paths.

Completed:
- `design_variables` attribute on all slot provider functions mapping
  short names to relative paths (e.g., `comp_PR` -> `cycle.DESIGN.comp.PR`)
- OCP factory collects slot DVs into var_paths, handling pipe-separated
  (promoted to top level) vs dot-separated (nested inside phase.subsystem)
- Turbojet: comp_PR, comp_eff, turb_eff. HBTF: fan_PR, fan_eff, hpc_PR, hpc_eff.
  OAS: twist_cp, toverc_cp. Surrogates: empty (DVs baked into deck).
- Tests: provider attribute checks + factory var_paths verification


## P9: Weight Slot Provider

**Status: DONE**

Goal: make OCP's weight model pluggable via a third slot type. First
concrete provider: parametric weight model that sums component weights.

Completed:
- `_ParametricWeightGroup` (ExplicitComponent): OEW = sum of W_struct,
  W_engine, W_systems, W_payload_equip. Analytic partials (all 1.0).
- `_parametric_weight_provider` with config-driven defaults and
  `use_wing_weight` option for aerostruct coupling
- Weight slot handling in ocp.py: weight_slot > propulsion passthrough >
  WeightClass > CFM56 passthrough
- `ocp/parametric-weight` registered in `_register_builtins()`
- Prerequisite fix: OEW passthrough when propulsion slot is active,
  OEW field registered, OEW values added to caravan/kingair/tbm850 data
- Tests: standalone component, provider interface, factory integration


## P10a: Direct-Coupled HBTF Off-Design Robustness

**Status: NOT STARTED**

The direct-coupled HBTF (`pyc/hbtf` slot provider) fails at extreme
off-design conditions -- specifically climb start at sea level, far from
the 35kft/M0.8 design point. The nozzle area-matching balances (W, BPR)
become ill-conditioned when the nozzle is unchoked at high back-pressure.

Root cause: the HBTF off-design has 5 coupled balance equations (W, FAR,
BPR, lp_Nmech, hp_Nmech) vs the turbojet's 3 (W, FAR, Nmech). The two
extra balances (bypass nozzle area, dual shaft power) are sensitive to
back-pressure, which changes dramatically between 35kft (~3.5 psi) and
SL (~14.7 psi). The current `guess_nonlinear` provides cruise-tuned
guesses (5.2 psi Pt, 440 degR Tt) regardless of actual conditions.

Upstream pyCycle handles this via explicit continuation -- solving one
flight point at a time, warm-starting from the previous converged
solution. Neither upstream nor hangar uses altitude-aware guesses.

Fixes (priority order):

1. **Condition-aware `guess_nonlinear`** in `pyc/hbtf.py` (2-3 hr)
   Read `inputs["fc.Fl_O:stat:P"]` or altitude and set regime-appropriate
   guesses for fc.balance.Pt, fc.balance.Tt, balance.W, balance.BPR.
   Use coarse if/else regime detection (SL vs mid-alt vs cruise), not
   smooth interpolation. Risk: if altitude inputs are poorly initialized
   on the first OCP Newton iteration, condition-aware guesses could be
   worse than fixed defaults.

2. **Add compressor map R-line guesses** in `slots.py` (15 min)
   Set fan/lpc/hpc.map.RlineMap = 2.0 in `apply_initial_guesses` for
   all OD points. Upstream does this; hangar currently omits it. Very
   low risk.

3. **Switch linesearch to `BoundsEnforceLS`** in `pyc/hbtf.py` (30 min)
   Clips Newton steps to bounds, preventing unphysical values (negative
   pressures, BPR < 2). Risk: can cause solver to stall near bounds
   rather than diverge -- trades divergence for silent wrong answers.

4. **Increase Newton maxiter** from 50 to 100, add stall_limit=3 (5 min)
   Prevents premature termination. Risk: doubles wall clock for genuinely
   non-converging cases in Newton-in-Newton context.

5. **Pre-solve warmup/continuation** in `slots.py` (1-2 days)
   Before OCP Newton starts, run HBTF standalone through a short
   continuation sequence (design -> mid-alt -> SL) to seed balance
   variables. Closest to upstream's strategy. Risk: breaks stateless
   subsystem contract; cached states invalidated when OCP Newton updates
   flight conditions. Needs drift detection to re-trigger warmup.

Fixes 1+2+3 should resolve convergence for typical OCP mission profiles.
Fix 5 is the fallback if those are insufficient.


## P10b: Composite Provenance DAG Population

**Status: PARTIAL**

Completed:
- `_decompose_plan()` now creates `wasDerivedFrom` prov_edges from every
  sub-entity (surface_def, operating_point, solver_config, opt_setup,
  aircraft_config, mission_config, propulsion_config, slot_config) back
  to the plan entity. DAG renderer shows the plan decomposition tree.
- `_record_assessment()` creates per-slot `slot_results` entities for
  composite runs with `parent_id=run_id`.

Remaining:

1. **Build composite discipline graph** (medium)
   Extend `build_discipline_graph()` to walk inside OCP composite
   problems and identify slot boundaries. Create nodes for each slot
   provider (drag/oas, propulsion/pyc, weight/ocp) and edges for data
   flow: fltcond -> drag_slot -> CD -> mission, fltcond -> prop_slot ->
   thrust -> mission.


## P10c: Per-Slot Result Extraction and Plotting

**Status: PARTIAL**

Completed:
- Slot providers declare `result_paths` attribute (same pattern as
  `design_variables`). Maps short variable names to internal OpenMDAO
  paths relative to the slot subsystem root. All 7 providers updated:
  oas/vlm, oas/vlm-direct, oas/aerostruct, pyc/turbojet, pyc/hbtf,
  pyc/surrogate, ocp/parametric-weight.
- `_extract_composite_summary()` now extracts per-slot results via
  `result_paths`. Builds full paths using the OCP model structure
  (`{comp_id}.{phase}.acmodel.{subsys}.{path}`) with fallback.
  Results stored in `summary["slots"]`.
- Materializer stores `active_slots` in component metadata so the
  extractor can look up slot providers at extraction time.
- `_record_assessment()` creates `slot_results` entities for each
  active slot in composite runs.
- pyCycle plot provider registered: `station_properties` (grouped bar
  chart of Pt/Tt at flow stations) and `component_efficiency` (bar
  chart of compressor/turbine efficiency and pressure ratio). Uses
  pattern matching (`*Fl_O:tot:P`, `*DESIGN*.eff`) to discover pyCycle
  variables in recorder output. Works for both standalone and composite.
- OAS plot patterns audited: existing `fnmatch` wildcards (`*wing.def_mesh`,
  `*wing_perf.CL`) already match composite paths. `detect_surface_name()`
  correctly parses surface names from longer paths.

Remaining:

1. **Deep OAS slot extraction** -- currently extracts scalar metrics
   via `result_paths`. Spanwise CL distribution, twist/chord profiles,
   mesh coordinates not yet extracted from composite runs. The OAS plot
   functions can already find these in recorder output via pattern
   matching, but the summary dict does not include them.

2. **pyCycle flow station extraction** -- `result_paths` gives TSFC/Fn
   scalars. Full flow station data (per-station Pt, Tt, W, MN) and
   component performance (per-component PR, eff, power) not yet in
   summary. The pyCycle plot provider reads these directly from the
   recorder, so they are available for plotting but not for
   programmatic access via `summary["slots"]`.

3. **T-s diagram** -- not yet implemented in pyc plot provider. Would
   plot entropy vs temperature for the thermodynamic cycle.

4. **Design-vs-offdesign comparison** -- plot provider only handles
   single-point data. Multipoint comparison not yet supported.


## P10: Future Integration Items (Not Started)

These items are identified but not yet planned for implementation:

- **Aerostructural direct-coupled slot** (`oas/aerostruct-direct`): direct
  aerostructural analysis at each mission node. Computationally expensive
  but gives structural weight feedback per node.
- **Multi-surface support**: omd assumes single OAS surface. Upstream OAS
  supports wing + tail, wing + canard. Path resolution is wired for one
  surface name.
- **Per-phase profile plotting**: depends on P7 profile extraction. Plot
  altitude/speed/thrust/drag vs mission distance or time.
- **Result extraction unification**: each tool family has its own extraction
  path in run.py. Factories could provide custom extractors via metadata.
- **Sizing-mission iteration loop**: slot system is one-directional (OCP
  drives flight conditions into slots). No outer loop where mission results
  feed back into engine or wing sizing. Would require MDF or IDF wrapper.


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
