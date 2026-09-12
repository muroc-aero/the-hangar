# Plan: OAS inside Aviary — coupled aerostructural wing mass in hangar-avy and omd

Status: **implemented** (2026-07-10; all work packages landed -- see the
result annotations in WP1 and the "Implementation results" section at the
end. Remaining stretch items: WP4.3 upstream PR, blind-agent Lane C runs.)

Goal: run OpenAeroStruct *inside* an Aviary sizing loop through the hangar
stack — a physics-based wingbox wing mass replacing Aviary's empirical FLOPS
wing weight — exposed two ways:

1. **Native avy** — OAS as an Aviary *external subsystem*, everything inside
   `.venv-avy`, driven by the `hangar.avy` tools/CLI.
2. **Multitool omd** — an omd plan that couples the tools at the omd level:
   either the native path wrapped in `avy/Sizing` (tight coupling in the
   subprocess), or the existing main-venv `oas/Aerostruct` factory feeding a
   wing-mass override into `avy/Sizing` (loose coupling across the venv
   boundary).

This is the first *nested* tool composition in the hangar: today's omd plans
place tools side by side in one OpenMDAO model; here one tool runs inside
another tool's optimization loop.

## What upstream already provides

Aviary ships exactly this integration as its flagship external-subsystem
example: `aviary/models/external_subsystems/open_aero_struct/`.

- `OAS_wing_mass_analysis.py` — `OAStructures`, an `om.ExplicitComponent`
  whose `compute()` builds a *nested* OAS wingbox problem (AerostructGeometry
  + 2 AerostructPoints: cruise + 2.5g maneuver at M0.64/SL) and runs an
  internal SLSQP sub-optimization (fuelburn objective; skin/spar thickness,
  twist, t/c, maneuver alpha DVs; strength + fuel-volume constraints).
  Outputs the optimized `wing_mass` (and `fuel_burned`). The wing mesh is
  hard-coded to the advanced-single-aisle planform (`user_mesh()`), which
  upstream itself flags as a limitation.
- `OAS_wing_mass_builder.py` — `OASWingMassBuilder(av.SubsystemBuilder)`,
  a *pre-mission* builder: promotes `fuel` from
  `Aircraft.Fuel.WING_FUEL_MASS_CAPACITY` and `wing_mass` **onto
  `Aircraft.Wing.MASS`**, overriding the FLOPS wing weight for the whole
  sizing problem.
- `run_OAS_wing_mass_example.py` — full mission run: advanced single aisle
  FLOPS deck, 3-phase fixed-profile mission (mach/altitude_optimize False,
  1800 nmi, no takeoff/landing) — i.e. already shaped like our
  SLSQP-tractable missions. Sets ~15 OAS inputs (wingbox airfoil coords,
  thickness/twist CPs, cruise condition, engine mass/location) via
  `prob.set_val()` **after `prob.setup()`** — this is the one part that
  doesn't flow through `run_aviary()`.
- Tests: `test_OAS_wing_mass_analysis.py` (component alone, one nested
  sub-opt) and `test_OAS_wing_mass_builder.py` (builder contract via
  `av.TestSubsystemBuilder`, cheap).

Plumbing facts that shape the plan:

- `run_aviary(aircraft_data, phase_info, subsystems=[...])` already threads
  builders into `prob.load_external_subsystems()` — our runner's one-shot
  entry point needs only a new pass-through argument.
- There is **no post-setup hook** in `run_aviary()`: anything the upstream
  example sets with `set_val()` after `setup()` must instead be baked into
  the builder (`set_input_defaults` on the pre-mission group) for our
  config-dict-driven tools. That's the main piece of hangar-side code.
- `load_external_subsystems` merges subsystem metadata into the problem —
  no extra metadata registration needed for the wing-mass case.

## Phase 0 — feasibility spike (DONE, verified)

All verified on 2026-07-07 against the pinned uptreams (Aviary v1.0.1,
OAS v2.12.0):

- OAS v2.12.0 declares `numpy>=1.21` (no upper cap) and
  `openmdao>=3.35,!=3.40` → installs cleanly into `.venv-avy`
  (numpy 2.4.6, OpenMDAO 3.44.0) together with `ambiance` (the atmosphere
  dependency the component imports):
  `VIRTUAL_ENV=$PWD/.venv-avy uv pip install -e upstream/OpenAeroStruct ambiance`.
- The upstream component test passes in `.venv-avy`
  (`test_OAS_wing_mass_analysis.py`, 1 passed in ~45 s — that is one full
  nested wingbox sub-optimization under numpy 2).
- `OASWingMassBuilder` imports and instantiates in `.venv-avy`
  (`av.SubsystemBuilder` is public API).

So the numpy-2 venv split does **not** block this: the OAS pin is
numpy-2-clean even though the *main* venv holds it at numpy<2 for
openconcept's sake. OAS simply gets installed a second time, into
`.venv-avy`.

Runtime envelope (drives everything below): one *cold* nested sub-opt
≈ 45 s. Two facts found in the component soften and sharpen this:

- Upstream already **warm-starts** the nested optimization
  (`self.previous_DV_values` seeds each `compute()` with the previous
  optimum), so per-iteration cost after the first solve should be far
  below 45 s — the real coupled wall-clock needs measurement (WP1), not
  extrapolation.
- The component declares its outer partials as
  `declare_partials('*', wrt='fuel', method='fd')` — every outer gradient
  evaluation finite-differences **across the nested sub-optimization**
  (one extra warm-started sub-opt per gradient), and the derivative is
  only as clean as the sub-opt's convergence (`tol=1e-8`, hardcoded, no
  `maxiter`). This single line is the mechanism behind both the runtime
  and the SLSQP-robustness risks.

Upstream's own example says "use the most performant optimizer installed"
(prefers SNOPT/IPOPT). Treat wall-clock and gradient quality as the top
risks, not sub-opt feasibility.

## Architecture A — native avy: OAS as an Aviary external subsystem

Everything runs inside `.venv-avy`; the tool surface stays JSON-config.

### A1. Venv + pins

- Add `openaerostruct` (editable `upstream/OpenAeroStruct` at the existing
  `OAS_REF`) + `ambiance` to `scripts/setup-avy-venv.sh`.
- Add the same to `packages/avy/Dockerfile` (build ARG `OAS_REF` mirrors the
  existing `AVY_REF` pattern).
- No change to root `pyproject.toml` — the main venv is untouched.

### A2. Hangar-side builder (the real code)

`packages/avy/src/hangar/avy/subsystems/oas_wing_mass.py`:

- `build_oas_wing_mass(config: dict) -> SubsystemBuilder` — wraps upstream's
  `OAStructures` in our own thin builder (do NOT fork the 567-line component;
  import it from `aviary.models.external_subsystems.open_aero_struct`).
- Converts a JSON config dict into `set_input_defaults()` calls on the
  pre-mission group — replacing the example's post-setup `set_val()` block.
  Config keys: wingbox airfoil coords (default: the example's arrays),
  `twist_cp`, `spar_thickness_cp`, `skin_thickness_cp`, `t_over_c_cp`,
  `fuel_lbm`, `fuel_reserve_lbm`, `CD0`, `cruise_mach`, `cruise_altitude_m`,
  `cruise_range_nmi`, `cruise_SFC_1_per_s`, `engine_mass_lbm`,
  `engine_location_m`.
- Validates config keys strictly with difflib suggestions (same contract as
  `_merge_options` in `missions.py`).
- Registry: `EXTERNAL_SUBSYSTEMS = {"oas_wing_mass": ...}` with a
  description + config schema for discoverability, mirroring
  `MISSION_TEMPLATES`.
- Lazy imports throughout (`require_aviary()` pattern): in the main venv the
  module imports, listing works, and building raises the standard
  install-instruction error. New `require_openaerostruct()` alongside
  `require_aviary()` with `setup-avy-venv.sh` instructions.
- Known limitation carried from upstream, documented in the registry entry
  and reference.md: the wing mesh is hard-coded to the advanced-single-aisle
  planform — this subsystem is only physically meaningful on that deck until
  upstream generalizes `user_mesh()` to read `Aircraft.Wing.*`. The tools
  should *warn* (ValidationFinding, warning severity) when the deck is not
  `advanced_single_aisle` / `bench_FwFm`.

### A3. Runner + tools

- `runner.py`: `_solve_sizing(..., subsystems=())` → forwarded to
  `run_aviary(..., subsystems=list(subsystems))`. Same for
  `run_off_design_problem` / `run_payload_range_problem` (they re-run the
  sizing internally and take the same path).
- New tool `add_external_subsystem(name, subsystem, config=None)`
  (in `tools/aircraft.py`): validates against the registry + config schema,
  stores `(subsystem_name, config)` on the `AvySession` aircraft entry
  (same accumulate-then-run pattern as `define_aircraft` overrides). A
  `list_external_subsystems` tool surfaces the registry.
- `run_sizing`/`run_off_design`/`run_payload_range`: materialize builders
  from the stored (name, config) pairs in `_prepare_run` and pass them down.
- Results: `extract_sizing_results` gains `design.wing_mass_lbm`
  (`Aircraft.Wing.MASS`) so the override is observable; add a
  `subsystem.wing_mass_applied` ValidationFinding (info) recording
  FLOPS-vs-OAS wing mass delta.
- New optional `run_sizing` kwarg `max_iter` already exists; expose the
  nested sub-opt's `maxiter` via builder config (`sub_opt_max_iter`,
  default upstream's) to keep runaway runs bounded.
- CLI + avy-cli-guide skill: new `add-external-subsystem` command page,
  workflows.md gets a coupled-sizing walkthrough with honest runtime
  numbers.

### A4. Native parity example (three lanes)

`packages/avy/examples/single_aisle_oas_wing/` following the established
layout:

- **Lane A** (oracle): adaptation of upstream's
  `run_OAS_wing_mass_example.py` — same deck, same fixed-profile 1800 nmi
  phase_info, SLSQP, `verbosity=0`, print `key: value` results. Golden
  anchors on `gross_mass_lbm`, `total_fuel_mass_lbm`, **`wing_mass_lbm`**
  (the quantity this example exists for), `range_nmi`.
- **Lane B**: avy-cli script JSON — `load_aircraft_template` →
  `add_external_subsystem oas_wing_mass` → `configure_mission` (a new
  `oas_wing_example` entry in `MISSION_TEMPLATES` pointing at a
  `hangar.avy.config.missions_oas_wing` module that reproduces the
  example's phase_info) → `run_sizing`.
- **Lane C**: scripted MCP tool-surface test + blind-agent prompt
  ("size the single aisle with a physics-based OAS wing mass and report how
  far it moves the wing mass vs the empirical estimate").
- Parity: A↔B at `rel=1e-6` (same code path, same venv); golden at
  `rel=2e-3`. A second cheap contract test asserts the FLOPS-only baseline
  wing mass differs from the OAS-coupled one (the integration is actually
  doing something).
- **Gate before writing goldens**: run Lane A once; if SLSQP does not
  converge (upstream prefers IPOPT/SNOPT), fall back per the established
  playbook — pin the profile harder / relax target range — and document a
  negative result honestly if no SLSQP-tractable variant exists. Mark all
  of it `slow`; CI keeps running only the aviary-free contract tests, the
  full lanes run via `.venv-avy` locally (same status as the existing avy
  parity suites).

## Architecture B — multitool omd

Two distinct flavors; build B1 first (it reuses everything from A), keep B2
as the follow-on that actually exercises cross-venv coupling.

### B1. Tight coupling: external subsystem through `avy/Sizing` (small)

The OAS-in-Aviary problem is just another Aviary run, so it flows through
the existing subprocess factory nearly for free:

- `avy_worker.py`: accept `spec["external_subsystems"] =
  [{"name": ..., "config": {...}}]`, materialize via the A2 registry
  (the worker already runs in `.venv-avy` where OAS now lives), pass to
  `run_aviary(subsystems=...)`. Also emit `wing_mass_lbm` in the results
  JSON.
- `factories/avy.py`: pass-through config key `external_subsystems`
  (validated shape only — name resolution happens in the worker, which is
  where the registry is importable); add `wing_mass_lbm` to `output_names`.
- omd example `packages/omd/examples/avy_oas_wing/`: plan.yaml =
  the A4 case as a one-component omd plan; Lane A subprocess-runs A4's
  Lane A script (exact pattern of `avy_single_aisle`); Lane C scripted
  builder-tools test. Goldens shared from A4's `shared.py`.
- Fast aviary-free unit tests in `packages/omd/tests/test_avy_factory.py`:
  config pass-through, `wing_mass_lbm` advertised, bad subsystem name
  rejected by the worker (exercised only in slow lanes).

### B2. Loose coupling: `oas/Aerostruct` → `avy/Sizing` override (the
multitool headline)

Main-venv OAS wingbox computes the wing mass; omd feeds it into the Aviary
subprocess as a deck override. One-way coupling (no feedback), which omd's
sequential composition already models:

- New `avy/Sizing` capability: **override inputs**. Config key
  `override_inputs: {wing_mass_lbm: "aircraft:wing:mass"}` declares
  OpenMDAO inputs on the component; at `compute()` each is written into
  `spec["overrides"]` (converting to the deck variable's units). This
  generalizes the existing `target_range_nm`-only input mechanism.
- Units seam (must be explicit, not implicit): OAS `structural_mass` is kg
  and is the *structure only*; Aviary `aircraft:wing:mass` is lbm and
  carries `wing_weight_ratio` semantics. The plan-level connection needs a
  small `units/Convert` passthrough component (kg→lbm, factor config) —
  omd shared vars connect same-units paths only. Check whether
  `wing_weight_ratio≈1.25` style dressing is wanted or whether raw wingbox
  mass is the study's point; surface that as a plan `decision`.
- Example plan: `oas/Aerostruct` (wingbox, single-aisle-like planform
  matching the A4 mesh) → convert → `avy/Sizing` (advanced single aisle,
  fixed-profile mission). DV sweep potential: `t_over_c_cp` or span at the
  OAS end, gross mass at the Aviary end — a real two-tool trade study and
  the natural `run_study` demo.
- Parity oracle problem: there is no single upstream script that does this
  loose coupling, so Lane A is *compositional*: run OAS raw (existing OAS
  Lane A infrastructure) → hand its wing mass to the avy Lane A script as a
  deck override. The lanes then check the hangar plumbing end to end, and
  the B1/A4 tight-coupled result provides the physical cross-check
  (loose-coupled result should land near the tight-coupled one when fed the
  same wingbox mass — document the expected gap: tight coupling re-optimizes
  the wing per outer iteration, loose coupling freezes it).

## Sequencing and risks

Superseded by the risk-mitigation work plan below — see **Revised
sequencing** at the end of this doc for the authoritative step order.

Risks, ranked (each mapped to a work package below):

1. **Wall-clock**: nested sub-opt cost × outer iterations × FD gradient
   evaluations → WP1 (measure), WP2 (reduce).
2. **SLSQP convergence of the coupled problem**: FD-across-sub-opt
   gradient noise; upstream example prefers SNOPT/IPOPT → WP1 (gate),
   WP3 (robustness modes).
3. **Hard-coded mesh**: the subsystem is single-aisle-specific until
   `user_mesh()` reads deck variables → WP4 (parametric mesh).
4. **Upstream API drift**: `aviary.models.external_subsystems...` is an
   example namespace, not core API → WP5 (contract tests + pin-bump
   checklist).

## Risk mitigation work plan

Work packages, in execution order. WP5 is trivial and lands first; WP1
gates the shape of everything after it.

### WP5 — drift protection (risk 4; ~0.25 day, do first)

- **W5.1 Contract test**: `packages/avy/tests/test_avy_oas_subsystem.py`
  (fast, `importorskip("aviary")` + `importorskip("openaerostruct")` so it
  skips in the main venv, runs for real via `.venv-avy`):
  - the upstream import path
    `aviary.models.external_subsystems.open_aero_struct` resolves;
  - `OASWingMassBuilder` is an `av.SubsystemBuilder` and
    `build_pre_mission` returns a group promoting onto
    `Aircraft.Wing.MASS`;
  - `OAStructures` still exposes the input/output names our config schema
    maps to (twist_cp, spar/skin thickness, fuel, wing_mass, ...);
  - `run_aviary` still accepts the `subsystems` kwarg
    (`inspect.signature`).
- **W5.2 Pin-bump checklist**: comment next to `AVY_REF`/`OAS_REF` in
  `scripts/upstream-pins.env`: "after bumping, run the avy contract tests
  in .venv-avy — the OAS external-subsystem integration imports from
  Aviary's example namespace, which is not API-stable."
- **W5.3 CI leg (decide separately, ~0.5 day if taken)**: a GH Actions job
  that builds `.venv-avy` (uv-cached) and runs
  `packages/avy/tests -m "not slow"` inside it. Today drift is caught only
  locally; this is the only mitigation that makes it automatic. Not
  required for the examples to ship.

### WP1 — instrument and measure (risks 1+2 gate; ~0.5 day + run time)

**MEASURED (2026-07-09, .venv-avy, SLSQP, hangar builder defaults ==
upstream example values, fixed-profile 1800 nmi mission):**

| quantity | value |
|---|---|
| optimizer result | **converged** (`prob.result.success == True`) |
| outer SLSQP iterations | 9 |
| `OAStructures.compute()` calls | **1** (verified by counting the component's timing prints) |
| nested sub-opt wall-clock | 37.0 s (the single, cold call) |
| total `run_aviary_problem` wall-clock | 45.5 s |
| setup wall-clock | 1.0 s |
| wing mass (OAS) | 14539.33 lbm |
| gross mass | 122876.48 lbm |
| total fuel | 13812.16 lbm |

Why one compute call: every OAS component input is an IndepVarComp
constant (the fuel input included -- and upstream's deck-driven
alternative, wing fuel *capacity*, is a deck constant too), so no outer
design variable feeds the component. OpenMDAO evaluates it once, caches
the output, and relevance reduction keeps the FD partial from ever being
requested -- an FD evaluation would have printed a second compute-timing
line, and there is none. The coupling in this upstream problem is
**feed-forward**, not two-way.

**Gate decision: coupled mode ships.** Converged, 45 s ≪ the 30-min
ceiling. Two corollaries: (a) coupled and precompute modes are *exactly*
equivalent here (same single sub-opt at the same inputs) -- the parity
example asserts that equivalence instead of choosing; (b) the W3.1
partials question is moot in this topology and stays upstream-as-is --
it only comes alive if a future mesh-from-deck-geometry coupling puts a
wing design variable upstream of the component (WP4 keeps geometry
config-static, so not even then).

The runtime and convergence mitigations depend on numbers we do not have.
One instrumented coupled run of the upstream example (Lane A adaptation,
SLSQP, fixed-profile 1800 nmi mission) in `.venv-avy`, capturing:

- number of `OAStructures.compute()` calls, split cold vs warm-started,
  and per-call wall-clock (the component already prints per-compute
  timing; capture stdout rather than patch);
- outer SLSQP iteration count and convergence status;
- total wall-clock;
- warm vs cold sub-opt cost ratio (validates that upstream's
  `previous_DV_values` warm start does the heavy lifting).

Deliverables: a measured budget table appended to this doc, and the
**go/no-go for coupled SLSQP goldens** (Architecture A4 step 3's gate).
Decision rule: converged + total wall-clock under ~30 min → coupled mode
is the shipped example; otherwise precompute mode (W3.2) is the shipped
example and coupled mode is documented as IPOPT-territory.

### WP2 — runtime reduction (risk 1; ~0.5 day)

- **W2.1 Nested-driver knobs**: builder config `sub_opt_tol` (default
  upstream's 1e-8) and `sub_opt_max_iter` (default 100). The nested
  driver settings are hardcoded mid-`compute()`, so this requires a thin
  subclass of `OAStructures` whose `initialize()` adds the two options
  and whose compute path applies them — implemented as a *surgical*
  subclass (override only the driver-setup seam if upstream's structure
  allows; otherwise carry a clearly-marked copied block with a pin-bump
  note in W5.2). Do NOT fork the physics.
- **W2.2 Smoke config**: a documented cheap variant for plumbing tests —
  `num_box_cp` reduced (51 → ~15), `sub_opt_tol` loosened to 1e-6,
  `sub_opt_max_iter` ~40. The VLM mesh is already minimal (nx=2, ny=7),
  so section resolution and tolerance are the only real levers; say so
  honestly rather than promising mesh-coarsening speedups.
- **W2.3 Optional fuel-tolerance memoization**: cache
  `(fuel → wing_mass)` and skip the sub-opt when the fuel input moved
  less than `recompute_rel_tol`. **Off by default** — it silently zeroes
  the FD partial when the tolerance swallows the FD step, which changes
  outer convergence behavior (see W3.1). Ship only with a validation
  finding that reports cache hits, so a run's provenance shows when
  memoization was active.

### WP3 — convergence robustness (risk 2; ~1 day)

- **W3.1 Partials strategy decision** (measure, then choose):
  the FD-across-sub-opt derivative couples gradient quality to
  `sub_opt_tol`. Evaluate on the WP1 instrumented run:
  (a) upstream as-is (FD, tol 1e-8);
  (b) frozen partials — treat wing mass as constant per outer iteration
  (zero partial), which converts the coupling into a fixed-point
  iteration handled by W3.2;
  (c) FD with tightened sub-opt tol only during gradient evaluations.
  Deliverable: a decision recorded in this doc with the measured
  iteration counts. (b) is the likely winner for SLSQP because it removes
  gradient noise entirely.
- **W3.2 `mode: "precompute"` (sequential fixed-point)** — the
  guaranteed-shippable path: run the OAS sub-opt *once* before the Aviary
  problem (fuel guess from the deck), apply the wing mass as a plain deck
  override, run standard sizing, then optionally iterate
  (sub-opt → override → sizing) until `wing_mass` and `fuel` settle
  (`fixed_point_max_iter` default 4, `fixed_point_tol` rel 1e-3 —
  weight-loop fixed points of this kind typically settle in 2–4 passes).
  Convergence properties equal plain sizing's, runtime is
  `N_fp × (sub_opt + sizing)`, and every iterate is observable
  (per-pass ValidationFinding with the wing-mass trajectory). This mode
  reuses the A2 builder config unchanged; only the runner orchestration
  differs. If WP1's gate fails for coupled SLSQP, this is the shipped
  example and the parity goldens anchor on it.
- **W3.3 IPOPT documentation (stretch, docs-only)**: conda-forge
  `pyoptsparse`+IPOPT into `.venv-avy` is possible but not
  pip-reproducible; document the recipe in `packages/avy/DEPLOY.md` as
  the coupled-mode escape hatch. No CI, no pins.

### WP4 — parametric mesh (risk 3; ~1 day)

- **W4.1 Deck-driven `user_mesh`**: upstream's `user_mesh()` is already a
  parameterized 2-segment (kink) planform builder with the
  advanced-single-aisle constants baked in (half_span 17.96 m, kink at
  4.95 m, chords 5.57/4.13/1.51 m, LE sweeps 25°/25°). Lift the constants
  into builder config, defaulted from deck variables:
  `Aircraft.Wing.SPAN`, `AREA`, `TAPER_RATIO`, `SWEEP`,
  `Aircraft.Wing.` kink/break span-fraction (FLOPS decks carry it as the
  wing definition's break location; fall back to a config value when the
  deck lacks it). Explicit config always wins over deck-derived values.
- **W4.2 Regression + sanity acceptance**:
  - advanced-single-aisle deck → generated mesh equals the hardcoded
    upstream mesh to 1e-10 (proves the lift-and-parameterize refactor
    changed nothing);
  - one other transport deck (`large_single_aisle_1`) → mesh is finite,
    spanwise-monotonic, positive chords, and the coupled/precompute run
    produces a plausible wing mass (order-of-magnitude finding, not a
    golden).
  - Until W4.1 lands, the deck-scope *warning* finding from A2 ships; after
    it lands, the finding drops to info and reports which mesh source
    (deck-derived vs config vs upstream-hardcoded) was used.
- **W4.3 Upstream contribution (stretch)**: PR the parametric
  `user_mesh` + the W2.1 driver-config options to Aviary; if accepted,
  the W2.1 subclass shrinks to a pass-through on the next AVY_REF bump.

### Revised sequencing

| Step | Contents | Size |
|---|---|---|
| 1 | WP5.1–5.2 drift contract tests + pin checklist | ~0.25 day |
| 2 | A1 venv/pins + A2 builder & registry + unit tests | ~1 day |
| 3 | WP1 instrumented coupled run → budget table + mode gate | ~0.5 day + run time |
| 4 | W3.2 precompute mode + W2.1/W2.2 knobs (informed by WP1) | ~1 day |
| 5 | A3 runner/tools/CLI + A4 parity lanes, goldens in the gated mode | ~1.5 days |
| 6 | B1 omd pass-through + example | ~0.5 day |
| 7 | W3.1 partials decision + coupled-mode goldens if gate passed | ~0.5 day |
| 8 | WP4 parametric mesh + second-deck example | ~1 day |
| 9 | B2 override inputs + convert component + coupled plan/study | ~1–1.5 days |
| 10 | W5.3 CI leg (optional) + WP4.3 upstream PR (stretch) + docs sync | ~1 day |

Anything that can invalidate goldens (WP1 mode gate, W3.1 partials choice)
lands *before* the goldens are written; anything additive (mesh, CI leg,
upstream PR) lands after.

## Implementation results (2026-07-10)

Everything above landed on `claude/aviary-hangar-package-44zznc` (PR #99).
What was built, and what the measurements said:

- **WP5**: `packages/avy/tests/test_avy_oas_contract.py` pins the upstream
  example-namespace surface (component I/O names+units, builder promotion
  onto `Aircraft.Wing.MASS`, `run_aviary(subsystems=)`, warm-start
  attribute); pin-bump checklist notes on AVY_REF/OAS_REF; a CI `avy-venv`
  job builds `.venv-avy` on every PR and runs the fast avy tests
  (including these) for real, and nightly runs the full avy suites +
  example goldens in `.venv-avy` (W5.3 taken).
- **A1/A2**: openaerostruct (editable at OAS_REF) + ambiance in
  `.venv-avy` and the avy Docker image; `hangar.avy.subsystems` registry
  with strict config validation, IVC wiring (no post-setup set_val),
  resampled defaults for coarse smoke configs, and the
  `ScipyOptimizeDriver.run` seam for the nested-driver knobs
  (`Problem.run_driver` is instance-bound by OpenMDAO's hooks and cannot
  be patched).
- **WP1**: measured budget table above. Coupled SLSQP converged (9 outer
  iterations, 45.5 s, exactly ONE sub-opt evaluation) -- gate PASSED,
  coupled mode shipped, and W3.1 dissolved (the FD partial is never
  requested in this feed-forward topology).
- **W3.2**: `run_precompute_sizing_problem` (sub-opt -> deck override ->
  plain sizing, optional `feedback="mission_fuel"` fixed-point loop).
  Measured **bit-identical** to coupled for the default config, as the
  topology predicts.
- **A3/A4**: `add_external_subsystem`/`list_external_subsystems` tools,
  `run_sizing(subsystem_mode=)`, `wing_mass_lbm` in the design summary,
  `subsystem.deck_scope`/`subsystem.wing_mass_applied` findings, CLI and
  skill updates; per-tool parity example `single_aisle_oas_wing` (6/6:
  golden anchor, coupled parity, precompute equivalence, FLOPS-contrast
  -- OAS 14539.33 lbm vs FLOPS at >3% separation -- and two contract
  tests). Goldens: gross 122876.48 lbm, fuel 13812.16 lbm, wing
  14539.33 lbm at 1800 nmi.
- **B1**: `avy/Sizing external_subsystems` pass-through into the worker
  (hangar.avy registry resolves inside `.venv-avy`), `wing_mass_lbm`
  output; omd example `avy_oas_wing` passed 1/1 (94 s).
- **WP4**: `wing_mesh.parametric_mesh` reproduces upstream `user_mesh()`
  **np.array_equal** (same ops, same order); `planform: "deck"` derives a
  simple trapezoid from `Aircraft.Wing.{SPAN, AREA, TAPER_RATIO, SWEEP}`
  (deck sweep applied as LE sweep -- stated in the mesh-source finding);
  delivered through the module-level `user_mesh` seam per compute.
  Second-deck check: 737-class `large_single_aisle_1` deck-derived
  sub-opt gives 13547.9 lbm (transport-plausible). The deck-scope warning
  now remediates to `planform: "deck"` and downgrades to an info
  mesh-source finding when a parametric planform is active.
- **B2**: `avy/Sizing override_inputs` ({input: {var, units, initial}} ->
  deck overrides per compute; `initial` mandatory so an unconnected input
  cannot silently override with 0; collision-checked against output
  names); omd example `oas_avy_wing_mass` -- OAS aerostructural wing
  (main venv, numpy<2) feeding `aircraft:wing:mass` across the venv
  boundary with kg->lbm on the plan connection. Compositional Lane A
  (raw OAS -> raw-Aviary override subprocess) vs the two-component plan:
  **0.0000% on every metric**, and the sizing's wing mass IS the OAS
  structural mass to round-off. Goldens: structural 6283.00 kg,
  gross 122560.10 lbm at 1906 nmi. (Also fixed a pre-existing run.py
  assumption that plan `solvers` is always a dict -- the schema's
  list-with-target form is exercised here for the first time.)
- The B2 `run_study` trade (OAS thickness/span vs Aviary gross mass)
  remains a documented follow-on, per the plan's "DV sweep potential"
  wording.
