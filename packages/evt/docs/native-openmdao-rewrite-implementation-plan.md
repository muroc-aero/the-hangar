# Implementation plan: native OpenMDAO formulation of evtolpy (hangar-side)

Status: **DONE (hangar-side native).** Implemented in `hangar.omd.evt`; the
`evt/Sizing` and `evt/Mission` factories now build the native model, with the
black box kept as `evt/SizingFD`. All five domain components match the black box
to floating point; the assembled sizing loop reproduces the AIAA SciTech 2026
grid; analytic total derivatives through the MTOW-closure loop agree with FD to
~1e-7. Parity suite: `packages/evt/examples/native_parity`. The rest of this doc
is the build plan as executed (kept for the rationale and the phase/parity
record). Companion: `native-openmdao-rewrite-upstream-plan.md` (design rationale
and the upstream-vs-fork analysis).

Outcome notes vs the plan:
- Sized MTOW matches the black box to ~1e-6, not 1e-9: the native loop converges
  tighter than evtolpy's loose `|delta| < 1e-3 kg` stop. Energy/power/masses
  (read pre-sizing or per-evaluation) match to floating point. 1e-5 is the
  established sized-MTOW convention across the evt parity suites.
- Divergence (the two Joby S4 60-mile cases) is reported as `converged == 0`
  (outcome parity), not raised: the NewtonSolver runs with
  `err_on_non_converge=False`.
- Per-iteration MTOW history (`mtow_history_kg`/`n_iterations`) is not recorded
  yet; the `mtow_convergence` plot degrades to a placeholder. Deferred as
  best-effort (would need a solver recorder).

The design priority, in order: (1) model evtolpy's physics and behavior
faithfully, equation for equation; (2) express it with correct, idiomatic
OpenMDAO patterns (feed-forward components, one implicit balance, real units,
complex-step partials). The pyc subpackage is precedent only for *where the code
lives and how it stays solver-light*. Its internal conventions (model-is-root,
archetype registry, hand-set Newton guesses for CEA thermo) are pyCycle-specific
and are **not** a template for evt. evtolpy is a different kind of model (closed-
form algebra with one mass-balance loop), so it gets the modeling pattern that
fits it, not pyc's.

## Goal

A set of OpenMDAO-native objects (`ExplicitComponent`s grouped under a
`Group` with a real MTOW balance) that reproduce evtolpy's physics to floating
point and expose **analytic/complex-step derivatives**, so evt can be driven by
gradient-based optimizers and coupled into a single converged solver with OAS or
pyCycle. The existing black box (`EvtolSizingComp`) stays as the validation
oracle and the no-gradient fallback.

## Decision (settled)

- **Location:** `packages/omd/src/hangar/omd/evt/`, self-contained, no runtime
  dependency on `hangar.evt` physics or on `upstream/evtolpy`. Living under
  `hangar.omd` (like `hangar.omd.pyc`) is purely so it imports without the
  upstream library and stays dashboard-importable; the internal structure is
  driven by the physics, not by pyc's layout.
- **upstream/evtolpy stays the oracle, not a dependency.** The parity suite
  imports evtolpy to generate golden values; the shipped native model does not
  import it. If upstream later adopts a native model, the hangar can re-point to
  it then. We own the physics fork and its parity suite in the meantime.
- The black-box `EvtolSizingComp` and its `evt/Sizing` + `evt/Mission` factories
  are **not deleted**. They become the FD fallback and the parity reference.

## Target file layout

```
packages/omd/src/hangar/omd/evt/
  __init__.py
  config.py        # 5-section schema load/merge, defaults, key->section routing
  environ.py       # EnvironComp: atmosphere/constants passthrough (g, rho, a, mu)
  geometry.py      # GeometryComp: wing/tail/fuselage areas, chords, AR, MAC
  aero.py          # AeroComp: cruise CL/CD buildup, L/D, drag coefficients
  propulsion.py    # PropulsionComp: disk loading, solidity, RPM, torque, disk area
  mission.py       # MissionEnergyComp + the segment kernel (18 segments)
  mass.py          # MassBuildupComp: ~15 component masses + empty mass; battery mass
  physics.py       # EvtolPhysicsGroup: the feed-forward physics, MTOW as an input
  sizing.py        # SizingGroup: physics(report) + physics(sized) + MTOW balance + Newton
  builders.py      # build_problem(mode=...) assembling the group(s)
  results.py       # extract scalars/segment tables/mass breakdown into the omd summary dict
packages/omd/src/hangar/omd/factories/evt.py   # re-point evt/Sizing + evt/Mission, add evt/SizingFD
packages/omd/tests/...                          # native parity + check_partials/check_totals
packages/evt/examples/native_parity/            # native-vs-blackbox golden suite (new)
```

`hangar.omd.evt` depends only on `numpy` and `openmdao`, never on `evtolpy`,
so it imports in the dashboard env (the same constraint the study-plot providers
honor).

## Architecture: idiomatic OpenMDAO over a faithful transcription

The model is the textbook conceptual-design MDAO shape: a feed-forward physics
chain closed by exactly one implicit mass balance. Build it that way rather than
as a monolithic component.

### One reusable physics group, parameterized by MTOW

`EvtolPhysicsGroup` holds the whole feed-forward chain with `max_takeoff_mass_kg`
as a group **input**, so the same group can be driven either by a fixed config
value (reporting) or by the balance state (sizing). Dependency order, from the
verified upstream graph:

```
EnvironComp        -> g, rho_sl, rho_alt, a, mu               (config passthrough)
GeometryComp       -> wing_area, AR, MAC, chords, tail areas, wetted area
                      (reads MTOW, stall_speed, environ, geom config)
PropulsionComp     -> disk_area, disk_loading, solidity, RPM, torque
                      (reads MTOW, rotor config, environ)
AeroComp           -> cruise_cl, cruise_cd, L/D, CD0 buildup
                      (reads geometry, mission cruise speed, environ)
MissionEnergyComp  -> per-segment shaft/electric power, per-segment energy,
                      total_mission_energy, total_reserve_energy, peak_power
                      (reads geometry, aero, propulsion, mission, environ, MTOW)
MassBuildupComp    -> ~15 component masses, empty_mass, battery_mass
                      (reads geometry, aero, propulsion, mission, environ, MTOW,
                       total_mission_energy)
```

Wire it with **promoted variable names and connections**, not manual src/tgt
plumbing where promotion is natural. Each domain output keeps the evtolpy name
(`wing_area_m2`, `disk_area_m2`, `cruise_l_p_d`, ...) so the graph reads like the
source and the parity suite can probe any intermediate. Because the chain is
acyclic, the group needs no solver of its own; OpenMDAO executes it in a single
forward pass.

### Real units, declared (a correctness win the black box skips)

The black box declares everything `units=None` because it just shuttles numbers
through evtolpy. The native components should declare **real OpenMDAO units**
(`kg`, `m`, `m/s`, `kW`, `kW*h`, `N`, `m**2`, ...) on every variable. This is the
idiomatic pattern and it is the entire point of going native: with real units,
OpenMDAO auto-converts on connection and the evt mass loop can be coupled to an
OAS aero point or a pyCycle deck without hand-matched unit conventions. The
seven promoted DV inputs and the documented scalar/vector outputs keep their
exact names so the factory `var_paths` contract is unchanged; units are added
metadata, not a renamed surface.

### Complex-step partials at the component level (the payoff, made cheap)

Each `ExplicitComponent` writes a numpy-clean `compute` and declares
`self.declare_partials('*', '*', method='cs')`. OpenMDAO then complex-steps the
component to get **exact** partials with zero hand-derived Jacobians, and
assembles total derivatives analytically through the group. This only works if
`compute` is complex-safe, which is exactly why every `math.*` call becomes
`numpy.*` (see the transcription section). Requirements that follow from this
choice:

- the problem is set up with `force_alloc_complex=True` so CS partials allocate;
- no Python `float()` casts, `abs()`, or comparisons that strip the imaginary
  part inside `compute`;
- hand-written analytic partials are a later optimization only if a profile shows
  component CS is the bottleneck. Start with CS everywhere; it is exact and
  faithful.

### MTOW closure: one implicit balance, Newton in production

`MTOW = empty_mass + payload + battery_mass`, with empty/battery depending on
MTOW. This is the single feedback loop. Two solver variants, both over the same
`EvtolPhysicsGroup`:

- **Validation-first: `NonlinearBlockGS`.** Mirrors evtolpy's fixed-point
  substitution `mtow -> empty+payload+battery -> mtow` step for step. Build this
  first so any parity gap is a transcription error, not a solver-scheme
  difference, and so `mtow_history_kg` matches the upstream iterate exactly.
- **Production: `BalanceComp` + `NewtonSolver(solve_subsystems=False)` +
  `DirectSolver`.** Residual `R = (empty + payload + battery) - mtow`. Quadratic
  convergence and clean total derivatives. Add a `linesearch`
  (`BoundsEnforceLS` or `ArmijoGoldsteinLS`) so the solve is robust, and
  `guess_nonlinear` seeding the balance state with the as-configured MTOW so
  Newton starts from the same point the fixed-point loop did, and so it stays
  robust if `evt/Sizing` is later embedded in an outer Newton (e.g. coupled with
  OAS). Validate the Newton converged MTOW against the GS variant to separate
  solver scheme from transcription.

Expose the solver choice as a build option so the parity suite runs both.

### Faithful divergence behavior

evtolpy raises `ValueError` on divergence via a specific heuristic (10
consecutive growing deltas, runaway >10x initial, non-finite masses;
`aircraft_iteration.py`). Newton will not reproduce that heuristic mechanism, and
it should not try to. The faithful requirement is the **outcome**, not the
mechanism: the two documented Joby S4 60-mile cases must end **non-converged**.
Map non-convergence to the contract by running the Newton solve with
`err_on_non_converge=False`, reading the solver's converged state plus a finite
check, and setting `converged=0.0` with `sized_mtow_kg` flagged exactly as the
black box flags a divergent case. Document that the detection mechanism differs
while the reported outcome matches; the parity suite asserts the outcome.

### The dual-MTOW reporting split (critical parity requirement)

The black box reports two MTOW states in a single sizing call (verified in
`packages/evt/src/hangar/evt/omd_component.py:128-190`):

- **At the as-configured MTOW (before the loop):** `segment_energy_kw_hr`,
  `segment_power_kw`, `total_mission_energy_kw_hr`,
  `total_reserve_mission_energy_kw_hr`, `peak_power_kw`,
  `disk_loading_kg_p_m2`, `max_takeoff_mass_kg`.
- **At the converged MTOW:** `sized_mtow_kg`, `empty_mass_kg`,
  `battery_mass_kg`, `payload_mass_frac`, `mass_breakdown_kg`, `converged`.

This is faithful to evtolpy's intent, where mission-energy reporting and MTOW
sizing are deliberately separate analyses (`run_mission_analysis` reads the
unsized aircraft; `run_sizing` runs the loop). A single Newton-converged group
produces one self-consistent state and would silently collapse that distinction.
The native `SizingGroup` reproduces it by adding **two instances of the reusable
`EvtolPhysicsGroup`**:

1. `report`: MTOW connected from the `max_takeoff_mass_kg` input (as configured),
   no balance. Drives the segment tables, totals, peak power, disk loading,
   `max_takeoff_mass_kg`. This instance **is** `evt/Mission` mode, reused as-is.
2. `sized`: MTOW connected from the `BalanceComp` state. Drives `sized_mtow_kg`,
   empty/battery mass, `mass_breakdown_kg`, `payload_mass_frac`, `converged`.

Two instances of one group with promoted-then-aliased outputs is ordinary
OpenMDAO composition, and it keeps `evt/Sizing` outputs aligned with the black
box value for value. `evt/Mission` mode builds only instance (1). Call this split
out prominently in `sizing.py`; it is the least obvious part of the contract and
the easiest thing for a future change to "simplify" and break.

### The 18-segment mission kernel (faithful structure)

The mission is the physics core and the place where a naive vectorization would
distort the model. The 18 segments are independent (no segment consumes
another's output; total energy is `sum(segment energies)`), but they are **not
homogeneous**: hover segments have no wing lift, transition segments add a
flight-path-angle term (`atan2`, `cos(theta)`), descent segments may engage
spoiler drag when shaft power goes negative, and seven segments are reserve
copies reading reserve-prefixed mission keys. Model this faithfully:

- Write one differentiable **segment kernel** (a numpy function) that takes a
  segment's parameters (durations, velocities, climb rates) plus per-segment
  **feature flags** resolved from config at build time: `has_wing_lift`,
  `has_flightpath_term`, `has_spoiler_recovery`, `is_reserve`. The flags select
  which physics terms are active.
- Resolving the flags at **build time** (not inside `compute`) means the
  wing-vs-no-wing and segment-type choices become fixed structure, not runtime
  branches on float values, so they never introduce derivative kinks.
- Apply the kernel across the 18 segments. A single vectorized
  `MissionEnergyComp` is the goal, but only if the kernel stays uniform under the
  flags; if the spoiler-recovery recompute makes one code path genuinely
  different, keep that path explicit rather than forcing a branchless vector form
  that obscures the physics. Faithfulness beats elegance here.
- Preserve `results.SEGMENT_KEYS` order exactly so the (18,) output vectors line
  up with the black box, the summary extractor, and the plots.
- `peak_power_kw = max(per-segment electric power)` and the total/reserve sums
  reproduce `aircraft_performance.py`'s aggregation exactly.

The spoiler-recovery recompute (`shaft_power < 0` in `decel_descend` /
`trans_descend`) is the one true runtime branch on a computed value. Reproduce it
exactly for parity and treat the boundary as a documented kink (see the
differentiability caveats below).

## The complex-step transcription (the mechanical core)

Every `math.*` call is complex-step-unsafe and must become `numpy.*`. The
inventory from the source review (cite exact sites during the port):

- `math.sqrt` -> `np.sqrt`: ~19 sites, mostly induced-velocity
  `sqrt(T/(2 rho A))` in `aircraft_performance.py` (lines 162, 250, 332, 501,
  692, 781, 851, 946, 1033, 1203, 1408, 1478), plus `aircraft_aero.py:184` and
  `aircraft_mass.py` (44, 193, 194, 242, 243).
- `math.log10` -> `np.log10`: `aircraft_aero.py:62` (skin-friction).
- `math.log` -> `np.log`: `aircraft_battery.py:119` (CC-CV charge time; only
  matters if charge time is exposed).
- `math.atan2` -> `np.arctan2`: 8 sites (transition/climb/descent flight-path
  angle) in `aircraft_performance.py`.
- `math.cos` -> `np.cos`: 8 sites (`weight*cos(theta)`).
- `math.pi` -> `np.pi` (constant, safe either way): ~20 sites.
- `abs()` -> `np.abs`, and audit every `max(0.0, x)` / `min(...)` clip.

### Differentiability caveats (call these out, they are real)

Complex step gives exact partials only where the expression is smooth. The
source has non-smooth branches that are **fixed by config at a given operating
point** but are kinks across the design space:

- `max(0.0, thrust)` / `max(0.0, lift)` clips in the segments. At a baseline
  where the argument is strictly positive, CS is exact locally. Near the clip
  boundary the derivative is discontinuous. Keep the clip (parity), but log
  which segments sit near a clip for any given config so an optimizer does not
  silently stall on a kink. Consider a smooth-max only if a study needs to cross
  the boundary, and gate it behind an option so it never changes baseline parity.
- Spoiler-drag engagement in `decel_descend` / `trans_descend` (recompute when
  `shaft_power < 0`): a genuine if/else on a float. Same treatment: reproduce
  exactly for parity; document the branch.
- Wing-vs-no-wing branch (`wingspan>0 and wing_area>0`): fixed by config, not a
  runtime kink. Resolve it at build time (pick the component variant from
  config) rather than branching inside `compute`.
- `math.isfinite` divergence guards in `aircraft_iteration.py`: these belong to
  the fixed-point loop, not the physics. In the native build the NewtonSolver
  owns convergence/divergence, so they are dropped, not transcribed.

`check_partials`/`check_totals` with `method='cs'` vs `'fd'` is the gate that
proves the transcription is differentiable where it claims to be.

## Drop-in contract (must match exactly)

From `factories/evt.py` + `omd_component.py` + `run.py:_extract_evt_summary`:

- **Inputs:** the 7 `DEFAULT_INPUT_SPECS` short names
  (`batt_spec_energy_w_h_p_kg`, `payload_kg`, `wingspan_m`, `stall_speed_m_p_s`,
  `rotor_diameter_m`, `tip_mach`, `cruise_s`), `units=None`, configurable via
  `input_specs`.
- **Scalar outputs:** the 10 in `SCALAR_OUTPUTS` order.
- **Vector outputs:** `segment_energy_kw_hr` (18,), `segment_power_kw` (18,),
  `mass_breakdown_kg` (15,), in `SEGMENT_KEYS` / `MASS_COMPONENTS` order.
- **Sizing history:** `n_iterations` (scalar) and `mtow_history_kg`
  (max_history,) padded with the converged value. Newton has no fixed-point
  "guess history"; record the Newton residual/MTOW iterate per iteration via a
  solver recorder or a small `record_iteration` hook so the
  `mtow_convergence` plot still renders. If exact step-by-step history parity
  with the fixed-point loop is wanted, run the GS variant for history and Newton
  for the value, or accept that history differs (documented) while the converged
  MTOW matches.
- **Factory metadata:** `point_name="evtol"`, `output_names`=scalars,
  `var_paths` bare names (promotes `["*"]`), `component_family="evt"`,
  `evt_mode` in `{"sizing","mission"}`, plus `initial_values` for inputs.
  `run.py` and the EVT plot provider then work unchanged.

## Phase plan with gates

Each phase has a gate that must pass before the next starts. Almost all the cost
is phases 4-6 (transcription + parity), exactly as the design doc predicts.

**Phase 0 - scaffolding (small).**
Create `hangar/omd/evt/` package skeleton, `config.py` (reuse the 5-section
schema and key routing from `hangar.evt.config`, but copy the constants in so
there is no runtime import), `environ.py`. Add an `evt/SizingFD` alias in
`factories/evt.py` pointing at the current black box so the FD path keeps a
stable name after `evt/Sizing` is re-pointed.
Gate: `omd-cli` imports cleanly; `evt/SizingFD` runs the existing black box and
matches today's `evt/Sizing` output.

**Phase 1 - geometry + environ + propulsion (no loop).**
Transcribe `GeometryComp`, `PropulsionComp` at fixed MTOW. numpy math.
Gate: `check_partials(method='cs')` clean; component-level golden match vs
evtolpy properties (`wing_area_m2`, `disk_area_m2`, `rotor_solidity`, ...) to
1e-9 at the `test_all` baseline.

**Phase 2 - aero (no loop).**
`AeroComp`: CL/CD buildup, L/D, including the `log10` skin friction.
Gate: `check_partials` clean; golden match on `cruise_cl`, `cruise_cd`,
`cruise_l_p_d`, all CD0 components to 1e-9.

**Phase 3 - mission energy (no loop, vectorized 18 segments).**
`MissionEnergyComp`. This is the largest single component. Reproduce every
segment including the `atan2`/`cos` flight-path terms and the spoiler-drag
branch. Output per-segment power/energy vectors, totals, reserve total, peak.
Gate: per-segment energy and power, total/reserve energy, peak power all match
the black box `evt/Mission` to 1e-9 at `test_all` and at 2-3 AIAA configs.
`check_partials` clean away from clip boundaries.

**Phase 4 - mass buildup (no loop).**
`MassBuildupComp`: the ~15 NDARC/empirical regressions + empty mass, and
`battery_mass = total_energy / usable_spec_energy`. Highest transcription risk
(coefficients/units in the NDARC regressions).
Gate: each of the 15 component masses + empty mass + battery mass match to 1e-9
at fixed MTOW. This is the parity wall the design doc flags as non-negotiable.

**Phase 5 - MTOW closure (GS variant first).**
Assemble `SizingGroup` with the reporting instance + sizing instance + the
`NonlinearBlockGS` balance. Wire `evt/Sizing` mode.
Gate: `sized_mtow_kg`, sized masses, `mass_breakdown_kg`, and the reported
(as-configured) tables all match the black box to 1e-9 at `test_all`; iteration
count and `mtow_history_kg` match the fixed-point loop step for step (GS mirrors
the legacy substitution).

**Phase 6 - Newton variant + derivatives.**
Swap in `BalanceComp` + `NewtonSolver` + `DirectSolver`. Validate the converged
MTOW against the GS variant (isolates solver scheme from transcription).
Gate: `sized_mtow_kg` matches GS variant to solver tolerance;
`check_totals(method='cs')` from the 7 inputs to `sized_mtow_kg`,
`total_mission_energy_kw_hr`, `empty_mass_kg` is exact vs FD. A tiny
gradient-based optimization (e.g. minimize battery mass over `wingspan_m`)
converges in few iterations and beats the FD black box on call count.

**Phase 7 - re-point factories + summary + plots.**
Point `evt/Sizing` and `evt/Mission` at the native builders. Keep `evt/SizingFD`
on the black box. Confirm `run.py:_extract_evt_summary` and `EVT_PLOTS`
(`segment_energy`, `segment_power`, `mass_breakdown`, `mtow_convergence`) work
unchanged against the native metadata.
Gate: `packages/omd` and `packages/evt` test suites green, including the
existing `test_abu_reproduction.py` (it now guards the native path) and the
AIAA case-study parity suites.

**Phase 8 - docs + cleanup.**
Update `packages/omd/CLAUDE.md` (component table, the new `hangar.omd.evt`
subpackage, the dual-MTOW split, `evt/SizingFD`), `packages/evt/CLAUDE.md`, and
flip this doc + the upstream-plan doc status to "done (hangar-side native)".

## Parity / test strategy

- **Oracle:** the black box (`EvtolSizingComp`) is the reference for every
  number. New suite `packages/evt/examples/native_parity/` runs lane "native"
  vs lane "blackbox" across `test_all` + all 18 AIAA configs, asserting:
  sized MTOW, total/reserve energy, peak power, all 18 segment energies/powers,
  all 15 component masses. Tolerance budget per quantity: energy/power/masses to
  1e-9 (pure arithmetic, must match floating point); `sized_mtow_kg` to 1e-9 for
  the GS variant and to solver tolerance (~1e-6) for the Newton variant; the two
  documented Joby S4 60-mile divergences must reproduce as non-converged in both
  lanes.
- **Derivatives:** components declare CS partials in production
  (`declare_partials(method='cs')`, problem set up `force_alloc_complex=True`).
  The suite runs `check_partials` per component and `check_totals` on the
  assembled `SizingGroup` comparing CS against FD, and asserts the error is at
  CS-exact levels (not just "within FD tolerance"). A regression here means a
  `math.*`/`float()`/`abs()` leaked back in and broke complex-safety; the check
  is the tripwire for that.
- **Reuse existing guards:** `test_abu_reproduction.py` and the
  `abu_scitech_2026` / `mission_segments` example suites already pin golden
  values to 1e-9; once factories are re-pointed they guard the native path with
  no change. Run them as the integration gate (Phase 7).

## Backward compatibility

- `evt/Sizing` and `evt/Mission` keep their names and exact I/O, so existing
  plans, studies, demos (`packages/evt/examples/abu_scitech_2026`,
  `packages/omd/demos`), and the dashboard study views keep working.
- `evt/SizingFD` is the escape hatch: if a config exposes a non-smooth branch
  that breaks the native gradient path, fall back to the FD black box for that
  study without code changes.

## Risks

- **NDARC mass regressions (Phase 4):** subtle coefficient/units errors are easy
  and silent. The 1e-9 per-mass golden suite is the backstop; do not advance
  past Phase 4 without it green.
- **History parity under Newton (Phase 6):** Newton iterates differ from the
  fixed-point substitution, so `mtow_history_kg` will not match step for step
  unless the GS variant is used for history. Decided mitigation: GS variant owns
  the convergence plot's history; Newton owns the value and the derivatives.
- **Non-smooth clips/branches:** reproduced exactly for parity but they are
  kinks for the optimizer. Document per-config which segments sit near a clip;
  offer smooth-max only behind an option that never alters baseline parity.
- **Drift ownership:** forking the physics moves AIAA-reproduction drift
  ownership from upstream to us (the design doc's main caveat for this option).
  The parity suite against the black box, which is itself pinned to upstream,
  keeps "native == upstream" continuously checked, so drift surfaces as a test
  failure rather than silently.

## Effort

Weeks, dominated by Phases 3-6 (mission/mass transcription + the parity suite),
matching the design doc estimate. The component graph is small and mechanical;
the cost is correctness validation, not architecture.
