# Adler 2022a reproduction — handoff and TODO

This demo is a partial implementation. Plumbing exists end-to-end and
analysis-mode runs work, but no figure has actually been reproduced
because optimization mode does not converge in tractable wall time
with the current settings. This document describes the current state,
the root issues, and the work needed to actually demonstrate paper
results.

The numbered phases below are an explicit progression. Do not skip
ahead. Phase 0 establishes ground truth on what's actually present in
the code. Phase 1 fixes the things that prevent phases 2-4 from
producing useful output.

---

## Background

Goal: reproduce Adler & Martins (2022a, AIAA SciTech, "Aerostructural
wing design optimization considering full mission analysis"), Figs 7,
9, 10, 11, 12, 13, on a Boeing 737-800-class aircraft over mission
ranges from 300 to 2900 nmi. Headline finding: a mission-based
aerostructural wing optimization (full OpenConcept mission with an
aerostructural drag-polar surrogate at every node) finds a thicker,
lighter wing than single-point or multipoint optimizations,
particularly for shorter missions where climb is a large fraction of
total fuel.

### Layout (mirrors `packages/omd/demos/brelje_2018a/`)

```
adler_2022a/
  README.md                                 # paper citation, run instructions, known issues
  TODO.md                                   # this file
  shared.py                                 # DV bounds + constraint list (paper Tables 2-4)
  sweep.py                                  # driver: range x method
  retry_failed.py                           # warm-start failed cells from neighbours
  plotting.py                               # Figs 7, 9, 10, 11, 12, 13 from sweep CSV
  compare.py                                # paper-vs-reproduced PNG composer
  lane_a/aerostruct_mdo.py                  # programmatic single-cell MDO
  lane_b/{single_point,multipoint,
          mission_based,
          single_point_plus_climb}/plan.yaml
  lane_c/aerostruct_mdo.prompt.md           # agent prompt
  figures/paper/fig{7,9,10,11,12,13}.png    # already extracted from PDF
  figures/reproduced/                       # populated by plotting.py
  figures/comparison_fig*.png               # populated by compare.py
  results/sweep_*.csv                       # populated by sweep.py
  results/per_design/{range}/{method}.json  # populated by sweep.py
```

### What is wired and verified

- **`oas/AerostructFixedPoint` factory** at
  `packages/omd/src/hangar/omd/factories/oas_aerostruct_fixed.py`,
  registered in `registry.py`. Three modes: `single_point`,
  `multipoint`, `single_point_plus_climb`. Builds standalone
  `om.Problem` (no OCP mission) with N fixed-condition
  `AerostructDragPolar` instances + `_OasManeuverGroup` for 2.5g
  sizing + Bréguet/modified-Bréguet `ExecComp` for the objective. TSFC
  fixed at 17.76 g/(kN·s) per paper Section IV.
- **Lane B plans** — all four validate (`omd-cli validate`). Each pins
  the relevant DVs, constraints, objective, and SLSQP optimizer.
- **Lane A vs Lane B parity** — verified BIT-IDENTICAL in
  `--mode analysis` at 1500 nmi single_point: 7726.293493 kg both.
  Confirms factory and plan materialize the same OpenMDAO problem.
- **Paper figure crops** — `figures/paper/fig{7,9,10,11,12,13}.png`
  cropped from `Adler2022a_OAS_and_OCP.pdf`. Procedure documented at
  the top of `figures/paper/README.md` (todo: write that file).
- **Test suite** — `packages/omd/tests/` passes (283/7/88 split).

### What is broken or stubbed (root issues)

These are the reasons no figure has been reproduced. They are listed
in the order they bite. Status confirmed by Phase 0 inspection
(`STATUS.md`, 2026-04-28).

1. **`oas/AerostructFixedPoint` has no plot provider.**
   `registry.py:228` calls `register_factory(...)` without a
   `plot_provider=` argument. `omd-cli plot <run_id>` therefore only
   emits the generic plots (`convergence`, `dv_evolution`, `n2`); none
   of the spanwise plots (`twist`, `t_over_c`, `skin_spar`) work for
   runs of this factory.

2. **SLSQP convergence is impractically slow.** Lane A at 1500 nmi
   single_point ran 67 minutes for 26 outer iterations and was killed.
   It was still improving (~1 kg/iter on a ~7300 kg objective). Root
   cause is a combination of:
   - `tol: 1.0e-6` on an objective with `scaler: 1e-3` means SLSQP
     wants to converge to ~1e-9 in scaled units, far below FD-gradient
     noise floor.
   - `AerostructDragPolar` retrains its surrogate (~30 s at default
     mesh) every time wing geometry changes; FD probes 14 DVs in
     sequence per outer iter.
   - Some optimizer steps land on poorly-conditioned wings where the
     internal NLBGS solver fails to converge in 100 iterations and
     raises `AnalysisError`, killing SLSQP.

3. **Sweep parallelism is broken.** `AerostructDragPolar` internally
   calls `multiprocessing.Pool()` with `os.cpu_count()` as default. With
   `sweep.py --workers 4`, that's 4×8 = 32 processes on an 8-core box.
   The previous run had all 12 cells fail in <30s with no useful
   diagnostic. `--workers 1` works but serializes.

4. **`plotting.py:fig9` is dead code.** It reads columns
   `climb_fuel_kg` / `cruise_fuel_kg` / `descent_fuel_kg` from the
   sweep CSV but `sweep.py` extracts those values from the recorder
   into `values` (sweep.py:76-77) and never writes them to the row
   (sweep.py:242-255). Path verified via the recorder for a prior
   mission_based run: `climb.fuel_used_final`,
   `cruise.fuel_used_final`, `descent.fuel_used_final` all exist as
   top-level outputs.

5. **`plotting.py:fig11` is a placeholder, AND the original plan in
   §1.3 below cannot work as written.** Lines 178-202 render a text
   box. The TODO previously suggested reading
   `cruise_0.drag.aero_analysis.aerostruct_point.aero_states.wing_sec_forces` —
   that path does not exist. The Bréguet variants compute cruise drag
   via `AerostructDragPolar`, a Kriging surrogate over precomputed VLM
   evaluations; the surrogate does not expose per-panel forces at any
   point. Only the 2.5 g maneuver group (which uses direct VLM+struct
   coupling) emits
   `maneuver.aerostructural_maneuver.aerostruct_point.coupled.aero_states.wing_sec_forces`.
   Phase 1.3 has been revised accordingly.

6. **`plotting.py:fig13` is unreachable dead code AND has a typo
   bug.** Lines 229-238 contain
   `fig7(...)._with_suffix(".png") if False else _render_fig7_with_methods(...)`.
   `Path` has no method `_with_suffix` (typo for `with_suffix`); that
   branch would raise `AttributeError` on call. The `main()` dispatcher
   (plotting.py:309-310) bypasses `fig13()` entirely and calls
   `_render_fig7_with_methods` directly, so the PNG renders correctly
   today — but anyone importing and calling `fig13()` will crash.
   Phase 1.6 should just delete the function.

7. **The existing `results/sweep_coarse.csv` is misleading, not just
   sparse.** The 12-row CSV checked in to disk has every cell marked
   `converged=True` with wall_time ~120 s. All 12 rows have AR=9.45,
   taper=0.159, c4sweep=25.0, W_wing=5518.51 — those are the factory's
   default IVC values. SLSQP exited without moving any DV. The
   per-design JSON dumps under `results/per_design/` likewise contain
   default geometry, not optima. Treat the existing artifacts as
   anti-pattern output to be regenerated, not a partial result to
   build on.

8. **`sweep.py --warm-from` is partial.** Only the three scalar DVs
   (AR, taper, c4sweep_deg) are propagated through `_WARM_FIELDS`
   (sweep.py:111-115). The 11 vector DV elements (twist_cp,
   toverc_cp, skin, spar) are not warm-started even though those are
   the most expensive to discover from scratch. The fix is small and
   should land alongside Phase 1.4 SLSQP retuning.

### Key paper data for validation

Tables 5, 6, 7 in the paper appendix (pages 14-15 of the PDF) give
the **exact converged optima** for all four methods at 300, 1500, and
2900 nmi. These are the gold reference for any single-cell test:

**Table 5 (300 nmi)** — single point | multipoint | mission-based | sp+climb
- mission fuel burn (kg): `2770.44 | 2765.53 | 2733.49 | 2740.63`
- aspect ratio: `10.401 | 10.401 | 10.401 | 10.401` (all at upper bound)
- taper: `0.168 | 0.174 | 0.180 | 0.180`
- c4sweep (deg): `23.046 | 23.524 | 21.577 | 21.754`
- twist cps (deg, root-to-tip with tip locked at 0):
  - sp: `[0, 2.072, -2.862, -1.072]` *(reverse if your factory orders tip-to-root)*
  - mp: `[0, 5.274, -3.630, 0.588]`
  - mb: `[0, 4.997, -2.787, 1.055]`
  - spc: `[0, 4.084, -1.460, 1.206]`
- t/c cps: `[0.034,0.086,0.090,0.118] | [0.030,0.096,0.085,0.119] | [0.034,0.112,0.123,0.147] | [0.038,0.117,0.136,0.157]`
- spar (mm): `[3.99,3.0,8.72,5.43] | [7.09,3.0,6.44,5.49] | [4.31,3.0,4.18,4.21] | [3.43,3.0,3.79,4.06]`
- skin (mm): `[5.0,14.94,18.47,19.15] | [4.94,13.35,19.23,18.93] | [3.70,11.20,12.40,14.38] | [3.0,10.44,11.31,13.70]`
- 2.5g failure: `2.8e-6 | 1.3e-7 | 9.1e-8 | 6.2e-8`

**Table 6 (1500 nmi)** — sp | mp | mb | spc
- mission fuel burn (kg): `11173.83 | 11168.74 | 11141.58 | 11164.54`
- taper: `0.155 | 0.162 | 0.158 | 0.161`; c4sweep: `22.45 | 22.75 | 22.67 | 23.07`
- t/c: `[0.030,0.096,0.088,0.114] | [0.030,0.094,0.088,0.115] | [0.030,0.093,0.093,0.119] | [0.030,0.100,0.093,0.123]`

**Table 7 (2900 nmi)** — sp | mp | mb | spc
- mission fuel burn (kg): `20345.36 | 20338.33 | 20297.51 | 20335.74`
- taper: `0.140 | 0.146 | 0.137 | 0.145`; c4sweep: `21.50 | 21.85 | 21.27 | 21.79`

Full tables (twist, spar, skin, alpha, all constraints) are in the
PDF pages 14-15 — copy them into `paper_data.py` as part of TODO 2.3.

**Caveat on direct comparison**: paper "mission fuel burn" is the
*mission-integrated* fuel of the optimized wing run through the
mission_based model. For Bréguet-objective methods the paper's
tabulated number is therefore NOT the value the optimizer is
minimizing. The Bréguet objective at 1500 nmi single_point should
converge to roughly 7000-8000 kg (single cruise segment + reserves),
not 11173.83 kg. To compare to Table 6 directly, take the optimized
wing geometry and re-run through the mission_based plan.

The DVs (taper, sweep, twist, t/c, skin, spar) ARE directly
comparable across methods — they describe wing geometry, not fuel
burn objective.

---

## Phase 0 — Configuration review and capability checklist

**Status: complete (2026-04-28).** See `STATUS.md` for the full
capability matrix and discrepancies found vs the Background section
above. The Background "What is broken or stubbed" list has been
updated to reflect Phase 0 findings (items 5-8 are new or revised).
Phase 1.3 (fig11) has been rewritten because the original plan does
not work — see that section for details.

Original instructions (kept for reference):

Before changing anything, read the current code and produce an
honest capability matrix. The "What is wired and verified" / "What
is broken or stubbed" lists in the Background section above are the
previous session's claims; they may be partly wrong. Verify each row
by reading the relevant file (and, where the row claims something
runs, by actually running it in `--mode analysis` for ~30 seconds).

Deliverable: a `STATUS.md` next to this file with one row per
capability below, columns `[implemented? | works? | location | notes]`,
filled in from direct code inspection (not from this document).

Capabilities to assess:

**Factory `oas/AerostructFixedPoint`**
- [ ] Builds standalone om.Problem at N fixed flight points
- [ ] `single_point` mode (1 cruise pt + maneuver + Bréguet)
- [ ] `multipoint` mode (5 cruise pts averaged)
- [ ] `single_point_plus_climb` mode (cruise Bréguet + Eq. 2 climb)
- [ ] CL=W/qS lift balance at each point (no alpha DV)
- [ ] 2.5 g maneuver sizing group with KS-aggregated failure
- [ ] Wing weight feedback from maneuver to weight slot
- [ ] B738 / paper-specific defaults removed (post Phase 1.0)
- [ ] Renamed to `oas/AerostructBreguet` (post Phase 1.0)
- [ ] Has unit tests covering >1 aircraft template (post Phase 1.0)

**omd SDK plumbing**
- [ ] Factory registered in `registry.py`
- [ ] Plot provider registered (currently NO — Phase 1.1)
- [ ] `plan_validate.py` recognises objective `fuel_burn_kg` and
      constraint `2_5g_KS_failure` short names
- [ ] `plan_schema.py` accepts vector DV bounds (`lower: [...]` /
      `upper: [...]` for twist_cp, toverc_cp)
- [ ] CaseReader emits the per-phase fuel paths fig9 needs
      (`{climb,cruise,descent}.fuel_used_final` for mission_based)
- [ ] CaseReader emits per-panel `wing_sec_forces` fig11 needs

**Lane B plans**
- [ ] Convention: `packages/omd/.gitignore` ignores `**/plan.yaml`
      (intended for assembled output of `omd-cli assemble`). Adler's
      plans were committed with `git add -f` because no modular
      `components/` tree exists. Decide: refactor to modular
      components or remove the gitignore exclusion.
- [ ] `single_point/plan.yaml` validates and runs analysis-mode
- [ ] `multipoint/plan.yaml` validates and runs analysis-mode
- [ ] `single_point_plus_climb/plan.yaml` validates and runs
- [ ] `mission_based/plan.yaml` validates and runs analysis-mode
- [ ] All four converge in `--mode optimize` (currently NO)
- [ ] All four use sane SLSQP settings (currently `tol=1e-6`,
      too tight — Phase 1.4)

**Lane A**
- [ ] `aerostruct_mdo.py --method single_point` runs
- [ ] `aerostruct_mdo.py --method mission_based` runs (uses
      upstream B738_aerostructural.py)
- [ ] Lane A vs Lane B parity test in analysis mode passes
- [ ] Lane A vs Lane B parity test in optimize mode passes
      (currently NO — neither converges)

**Lane C**
- [ ] `aerostruct_mdo.prompt.md` is current re lane B plan structure

**Sweep / retry**
- [ ] `sweep.py --grid coarse --workers 1` runs
- [ ] `sweep.py --grid coarse --workers >1` runs (currently NO,
      OAS internal mp.Pool conflict — Phase 1.5)
- [ ] `--fine-mesh` flag bumps to num_y=27 correctly
- [ ] `--warm-from` reads prior CSV and seeds DVs
- [ ] CSV columns include per-phase fuel for fig9 (currently NO —
      Phase 1.2)
- [ ] Per-design JSON dumps spanwise DVs for fig10
- [ ] Per-design JSON dumps panel forces for fig11 (currently NO —
      Phase 1.3)
- [ ] `retry_failed.py` resumes from neighbour DVs after failures

**Plotting**
- [ ] `fig7` renders from sweep CSV
- [ ] `fig9` renders real data (currently dead code — Phase 1.2)
- [ ] `fig10` renders from per-design JSON
- [ ] `fig11` renders real data (currently placeholder — Phase 1.3)
- [ ] `fig12` renders from sweep CSV
- [ ] `fig13` renders without dead `if False` branch (Phase 1.6)
- [ ] `compare.py` composes paper-vs-reproduced for all 6 figures

**Reference data**
- [x] Paper figure crops at `figures/paper/fig{7,9,10,11,12,13}.png`
- [ ] Paper Tables 5/6/7 transcribed to `paper_data.py` (Phase 1.7)
- [ ] Paper Fig 7/12/13 trend curves digitized to
      `figures/paper/digitized/fig*.csv` (Phase 2.3)
- [ ] Parity test `tests/test_adler_paper_parity.py` (Phase 2.3)

The matrix is a one-day-or-less inspection task. Do not "fix while
reviewing" — just record. Phase 1 fixes things in the right order.

---

## Phase 1 — Fix core issues (no compute, all code)

Each of these is a precondition for getting any meaningful result.
None require running optimizations; all can be developed against
analysis-mode runs.

### 1.0 Relocate / generalize the paper-specific factory

`packages/omd/src/hangar/omd/factories/oas_aerostruct_fixed.py` (627
lines) is currently in core omd SDK source but is shot through with
B738- and Adler-paper-specific defaults:

- `_DEFAULT_MTOW_KG = 79002.0` (B738)
- `_DEFAULT_ORIG_W_WING_KG = 6561.57` (B738 Raymer estimate)
- `_DEFAULT_PAYLOAD_KG = 17260.0` (B738 174-pax)
- `_DEFAULT_TSFC_G_PER_KN_S = 17.76` (paper Section IV constant)
- `_DEFAULT_MANEUVER` mach=0.78, altitude_ft=20000 (paper-specific)
- The three `mode` strings (`single_point`, `multipoint`,
  `single_point_plus_climb`) are Adler's paper terminology

The module docstring even says "Used by the Adler 2022a
reproduction demo." It does not belong in core SDK in its current
form. Refactor to genuinely-generic:

- Rename file to `oas_aerostruct_breguet.py`; rename factory to
  `build_oas_aerostruct_breguet`; rename registry key to
  `oas/AerostructBreguet`.
- Move ALL B738 / paper-specific module-level defaults into the
  Adler demo's plan files. The factory should require the caller to
  pass `MTOW_kg`, `tsfc_g_per_kN_s`, `orig_W_wing_kg`,
  `payload_kg`, `maneuver` block. No defaults that bake in one
  aircraft.
- Rename `mode` taxonomy from paper terminology to method-agnostic
  names: `single_cruise_breguet`, `averaged_cruise_breguet`,
  `cruise_plus_climb_breguet`. Document the Adler mapping in the
  demo's README.
- Add tests in `packages/omd/tests/factories/test_oas_aerostruct_breguet.py`
  exercising at least two aircraft (B738 + a turboprop like the OCP
  `caravan` template) and asserting the lift balance + Bréguet math
  on a hand-checked case.
- Update `registry.py:223-234` to register the new name. Drop the
  old name (no users outside this demo).
- Update all four `lane_b/*/plan.yaml`, `lane_a/aerostruct_mdo.py`,
  the `lane_c/.prompt.md`, and `shared.py` to use the new name and
  pass the now-required config explicitly.
- Update `plan_validate.py` and `plan_schema.py` if either hard-codes
  the old name.

This is a precondition for Phase 1.1. Do it first.

### 1.1 Wire plot provider for `oas/AerostructBreguet`

Edit `packages/omd/src/hangar/omd/registry.py:228` to pass
`plot_provider=...`. The existing `OAS_AEROSTRUCT_PLOTS` (in
`packages/omd/src/hangar/omd/plotting/oas.py:1344`) assumes the
standard `aero_point_0` namespace; the FixedPoint factory uses
`cruise_0`, `cruise_1`, ..., `maneuver_aerostruct`. Two options:

- **(a) Thin wrapper:** create `OAS_AEROSTRUCT_FIXED_PLOTS` in
  `plotting/oas.py` that calls the existing helpers with the
  per-point name passed explicitly. Read each plot function in
  `plotting/oas.py` (twist, t_over_c, skin_spar, struct, vonmises) —
  most accept a `point_name` kwarg or read it from the factory
  metadata. Pass `cruise_0` for the FixedPoint factory.
- **(b) Refactor:** parameterize OAS plot helpers on point name and
  drop the assumption that the namespace is `aero_point_0`. More work
  but eliminates duplication.

Verify by running an analysis-mode plan and calling
`omd-cli plot <run_id> --type t_over_c` — it should produce a PNG
with the spanwise t/c profile (constant across span at the default
DVs, since toverc_cp = 0.15 everywhere by default).

### 1.2 Fix sweep.py CSV columns for fig9 source data

In `packages/omd/demos/adler_2022a/sweep.py`:

- Add to `COLUMNS` (line 47): `"climb_fuel_kg"`, `"cruise_fuel_kg"`,
  `"descent_fuel_kg"`.
- Add to `_run_one`'s `row.update({...})` (line 244): pull
  `climb.fuel_used_final`, `cruise.fuel_used_final`,
  `descent.fuel_used_final` from `values` for `mission_based`; leave
  NaN for Bréguet methods.
- Verify those output paths actually exist in the recorder. Run a
  mission_based analysis-mode cell first and inspect with
  `uv run python -c "from openmdao.api import CaseReader; cr =
  CaseReader('hangar_data/omd/recordings/<run>.sql'); c =
  cr.get_case('final'); print([k for k in c.outputs if 'fuel' in k])"`.
- Fix `plotting.py:fig9` to use the new columns (already there in
  spirit, but currently gates on `"climb_fuel_kg" not in sub.columns`
  so the placeholder triggers).

### 1.3 Implement fig11 panel-wise lift extraction

**Revised after Phase 0**: the original plan (read
`cruise_0.drag.aero_analysis.aerostruct_point.aero_states.wing_sec_forces`)
will not work. That path does not exist. For the Bréguet variants
the cruise drag is computed by `AerostructDragPolar` — a Kriging
surrogate trained on a precomputed VLM grid — and there is no
per-panel force exposure anywhere downstream of the surrogate. Only
the 2.5 g maneuver path emits `wing_sec_forces`.

For the `mission_based` plan the surrogate is wrapped further inside
the OCP slot infrastructure (`oas/aerostruct` drag slot) so cruise
panel forces are even less accessible.

Three options, in order of preference:

- **(a) Maneuver-only fig11.** Just plot the 2.5 g maneuver lift
  distribution for both methods and rename the figure (or annotate
  it). The paper's fig11 shows cruise + maneuver overlaid — losing
  cruise costs us one panel of comparison but the more interesting
  trend (maneuver-driven structural sizing differing between methods)
  is preserved. This is the cheapest path and is what we should ship
  for the first reproduction pass.
- **(b) Reconstruct cruise lift from the surrogate's training data.**
  `AerostructDragPolar` keeps the underlying VLM problem accessible
  via its training subgroup. The cruise CL is known
  (`cruise_0.cl_passthrough.fltcond_CL`). We could re-evaluate the
  underlying VLM at the converged geometry and that CL post hoc to
  get cruise panel forces. This is real engineering work, ~1 day.
- **(c) Switch the cruise drag computation to a direct-VLM coupled
  group** (drop `AerostructDragPolar` for one variant). Massive
  scope change, do not pursue for the reproduction.

Implement (a) first. Concrete steps:

In `packages/omd/demos/adler_2022a/sweep.py`:

- Add to `_OUTPUT_KEYS` (line 60):
  `maneuver.aerostructural_maneuver.aerostruct_point.coupled.aero_states.wing_sec_forces`
  (verified against live recorder run-20260428T090219-0ac31ea9 in Phase 0).
- In `_persist_per_design` (line 192), capture the array as
  `lift_dist_maneuver_N` (a list-of-lists since `wing_sec_forces` is
  shape `(nx-1, ny-1, 3)`).

In `packages/omd/demos/adler_2022a/plotting.py`, replace the
placeholder `fig11()` (lines 178-202):

- Read `lift_dist_maneuver_N` from
  `results/per_design/{rng}/{method}.json` for the three Bréguet
  variants (and `mission_based` once that path is also wired).
- The array is shape `(nx-1, ny-1, 3)`. Sum along the chord axis
  (axis=0) and take the z-component (`...[:, 2]`) to get spanwise
  lift per panel (length ny-1).
- Normalise by total maneuver lift (so the curve integrates to ~1).
- Mirror to full span using
  `hangar.omd.plotting._common.mirror_half_wing`.
- Plot all available methods overlaid on the full normalised span,
  one curve per method in the METHOD_COLORS palette.
- Update the figure title to "2.5 g maneuver lift distribution"
  (note in the docstring that cruise is unavailable due to
  surrogate-based drag; document option (b) for a future revisit).

If option (b) is later required, the entry point is OAS's
`compute_training_data` in `AerostructDragPolar`; the simplest
approach is to instantiate a single VLMGeometry/AeroPoint at the
converged geometry and converged cruise CL outside the recorder.

### 1.4 Fix SLSQP convergence settings

In all four `lane_b/*/plan.yaml` files:

- Change `optimizer.options.tol` from `1.0e-6` to `1.0e-4`. Paper
  reports failure constraints around `1e-7` — `tol=1e-4` is more than
  tight enough for the converged optima in Tables 5/6/7.
- Consider changing objective `scaler` from `1.0e-3` to `1.0e-4` on
  the multi-thousand-kg fuel burn — reduces FD step quantisation
  noise.
- Bound investigation: open
  `packages/omd/src/hangar/omd/factories/oas_aerostruct_fixed.py`
  and check whether the surrogate-train function can be wrapped in a
  retry-with-slack-tolerance loop. Currently a single NLBGS failure
  inside `compute_training_data` propagates as `AnalysisError` up to
  SLSQP and kills the run.

After this change, smoke-test with Lane A at the default mesh:
expected wall time `5-15 min` for SLSQP to return (vs the previous
67-min kill). If still too slow, profile with `cProfile` to see
whether wall time is dominated by surrogate retraining or coupled
NLBGS solves.

### 1.5 Patch OAS internal mp.Pool conflict

`AerostructDragPolar.compute_training_data` calls
`multiprocessing.Pool()` with no arg, defaulting to
`os.cpu_count()`. When `sweep.py --workers 4`, this multiplies.

In `packages/omd/demos/adler_2022a/sweep.py`, before the `mp.Pool` is
created, set `OMP_NUM_THREADS=1` and either:
- monkey-patch `multiprocessing.Pool` in the worker init function to
  cap at 2, or
- pass `processes=2` via a `pool_processes` arg to
  `AerostructDragPolar` (check upstream OpenConcept signature — this
  arg may already exist).

After this fix, `--workers 2` should be safe on an 8-core box.

### 1.6 Delete dead `plotting.py:fig13`

The `fig13()` function is unreachable: `main()` calls
`_render_fig7_with_methods(df, "fig13")` directly. Worse, the dead
branch has a typo (`._with_suffix(".png")`; `Path` has no such
method) so calling `fig13()` raises `AttributeError`. Just delete
the function. No replacement needed; `main()` already works.

### 1.8 Make `--warm-from` seed all DVs

Currently `_WARM_FIELDS` (sweep.py:111-115) covers only AR, taper,
and c4sweep_deg. Extend it (and `_warm_for`,
`retry_failed.py:53-57`) to also seed the four vector DVs:
`twist_cp`, `toverc_cp`, `skin_thickness_cp`, `spar_thickness_cp`.
The values come back from the recorder as JSON-serialised lists in
the per-design dump, so:

- Add the four vector DVs to a new `_WARM_VECTOR_FIELDS` list and
  read them out of the corresponding `results/per_design/{rng}/{method}.json`
  in `_warm_for` (since the sweep CSV is scalar-only by design).
- In `_patch_plan` (sweep.py:153-157), accept list-valued `initial`
  on the four vector DVs and write them into the plan's
  `design_variables[].initial` field. The plan schema already
  accepts list `initial` (plan_schema.py:358-363); no schema work.
- Confirm via a small unit test that `omd-cli run` actually applies
  the seed values at setup time (the materializer sets DV initial
  via `prob.set_val` after setup).

This is a precondition for Phase 4's coarse sweep: warm-starting
only the three scalar DVs is not enough to rescue an SLSQP failure
on a wing whose t/c shape was the actual issue.

### 1.7 (Optional but recommended) write `paper_data.py`

Transcribe Tables 5, 6, 7 from the paper appendix into
`packages/omd/demos/adler_2022a/paper_data.py` as Python literals.
Used by the validation tests in Phase 2.3 and by `compare.py` for
overlay annotations.

---

## Phase 2 — Demonstrate one fully converged single-cell run

After Phase 1.1, 1.4 are done. The cell to use is
**`lane_b/single_point/plan.yaml` at mission_range_nmi = 300**, the
simplest method at the paper's most-illustrative range (this is what
the paper's Fig 10 shows).

### 2.1 Reduced mesh smoke run

Make a copy `lane_b/single_point/plan_smoke.yaml` with:
- `mission_range_nmi: 300`
- `surface_grid: {num_x: 2, num_y: 5, num_twist: 4, ...}` (and
  matching `maneuver`)
- `optimizer.options.tol: 1.0e-4`

Run:
```bash
uv run omd-cli run packages/omd/demos/adler_2022a/lane_b/single_point/plan_smoke.yaml \
  --mode optimize
```

Wait for SLSQP to **return on its own** — do not kill early. Expected
wall time ~30-60 min. Capture the printed `run_id`.

Generate the t/c plot (this is the single comparison we want to match):
```bash
uv run omd-cli plot <run_id> --type t_over_c
```

Compare to paper Table 5 single_point row above:
- AR: paper 10.401 (at upper bound). Ours: read with
  `uv run omd-cli results <run_id> --summary | grep AR`.
- taper: paper 0.168.
- c4sweep: paper 23.046°.
- t/c cps: paper `[0.034, 0.086, 0.090, 0.118]`. Coarse mesh will not
  match exactly; expect ~10-20% differences on individual cps. Goal:
  same monotonic shape (low at root, high at mid, ~0.118 at tip is
  unusual — the bounds in `lane_b/.../plan.yaml` may have the wrong
  ordering; verify root-to-tip vs tip-to-root convention vs paper).

If the t/c numbers are nowhere near the paper, the most likely cause
is a bound-ordering bug in the plan (paper orders cps tip-to-root in
Table 5; the plan currently has lower bounds `[0.030, 0.053, 0.077,
0.10]` which look like tip-to-root). Cross-check before assuming
optimizer failure.

### 2.2 Full mesh paper-spec run

Once 2.1 produces a directionally-correct match, rerun with the
paper's mesh:
- `surface_grid: {num_x: 3, num_y: 27, ...}` (and matching maneuver)
- `optimizer.options.tol: 1.0e-5`

Expected wall time `4-12 h` (4× per surrogate train + tighter tol).
Run on a machine you can leave overnight.

Compare to paper Table 5 single_point row directly. Acceptance:
- AR, taper, c4sweep within **1%** of paper.
- Each t/c, skin, spar cp within **5%** of paper.
- 2.5g_KS_failure within `1e-5` of `0.0` (paper says `2.8e-6`).
- Bréguet fuel_burn_kg in the 7000-8000 kg range (NOT directly
  comparable to paper Table 5 fuel burn — see "Caveat on direct
  comparison" above).

### 2.3 Extract paper data + write parity test

Write `packages/omd/demos/adler_2022a/paper_data.py`:
```python
PAPER_TABLES = {
    300: {"single_point": {"taper": 0.168, "c4sweep_deg": 23.046, ...}, ...},
    1500: {...},
    2900: {...},
}
```
(Numbers are in the Background section above; full transcription is
mechanical.)

Write `packages/omd/tests/test_adler_paper_parity.py`:
- Given a single-cell sweep CSV, assert each (range, method)
  scalar within tolerance of `PAPER_TABLES[range][method]`.
- Mark `@pytest.mark.slow` since it requires a converged sweep.

For Fig 7 / 12 / 13 trend curves (no tabulated data across all 14
ranges), digitize the paper figures with WebPlotDigitizer
(<https://apps.automeris.io/wpd/>). Open
`figures/paper/fig{7,12,13}.png`, calibrate axes, export each curve
as CSV. Save to `figures/paper/digitized/fig{7,12,13}.csv` with
columns `mission_range_nmi, method, pct_vs_baseline`. Use these for
trend-correlation tests in Phase 4.

---

## Phase 3 — Test one figure on a real sweep

After Phase 2.2 succeeds. Pick **Fig 10** (one mission range, three
methods — the smallest sweep that reproduces a paper figure end-to-end).

### 3.1 Reduced-mesh fig10 sweep

Run three single cells via direct `omd-cli` (avoid sweep.py
multiprocessing until Phase 1.5 is done if it blocked):

```bash
for method in single_point multipoint mission_based; do
  uv run omd-cli run packages/omd/demos/adler_2022a/lane_b/$method/plan_smoke.yaml \
    --mode optimize
done
```

Each plan_smoke.yaml uses `mission_range_nmi: 300, num_y: 5,
tol: 1.0e-4`. mission_based at smoke mesh: ~60 min. The other two:
~30-60 min each. Total wall time: ~2-3 h serial.

Capture each `run_id` and write to a small `results/fig10_smoke.csv`
manually (or have sweep.py with `--workers 1` write it). Then:

```bash
uv run python packages/omd/demos/adler_2022a/plotting.py \
  --csv results/fig10_smoke.csv --figures 10 --design-range 300
```

Compare `figures/reproduced/fig10.png` to `figures/paper/fig10.png`
side-by-side. Expected qualitative match per paper:
- mission_based (green) t/c notably higher than single_point (red)
  and multipoint (orange) — paper shows green peak ≈ 14.5%, red/orange
  peak ≈ 11.5%.
- mission_based skin thickness lower than single_point/multipoint —
  paper green ≈ 14 mm peak, red/orange ≈ 19 mm peak.
- twist: green and orange similar; red lower (more washout) per
  paper.

### 3.2 Paper-spec fig10 sweep

Once 3.1 looks right, rerun the same three cells at paper-spec mesh
(`num_y: 27, num_x: 3, tol: 1.0e-5`). Wall time: ~12-36 h total
(mission_based dominates).

This is the demonstrable "one paper figure reproduced from omd plans"
deliverable.

---

## Phase 4 — Run all sweeps

After Phase 3.2 succeeds. Goal: full coarse sweep producing all
six paper figures.

**Before starting**: delete `results/sweep_coarse.csv` and the
`results/per_design/*` JSON files. The artifacts checked in to disk
today have every cell at default IVC geometry (see Background
item 7); leaving them in place will silently provide misleading
"converged" warm-starts to Phase 4.1.

### 4.1 Bréguet-trio coarse sweep first

After Phase 1.5 mp.Pool patch is applied:

```bash
uv run python packages/omd/demos/adler_2022a/sweep.py \
  --grid coarse \
  --methods single_point,multipoint,single_point_plus_climb \
  --workers 2
```

Expected: 12 cells × 6-15 h each = 72-180 h serial → 36-90 h at
workers=2 on this 8-core box. Plan for a multi-day run.

If individual cells fail, run `retry_failed.py` after the first
pass; warm-starts from converged neighbours typically rescue ~80%
of failures.

### 4.2 Mission-based coarse sweep separately

```bash
uv run python packages/omd/demos/adler_2022a/sweep.py \
  --grid coarse --methods mission_based --workers 1
```

mission_based is much slower (~30-90 h per cell) because each outer
SLSQP iter has to converge a full mission. 4 cells × 60 h = 240 h
serial. Schedule on a machine you can leave for a week, or use a
larger one.

### 4.3 Render all figures + compare

```bash
uv run python packages/omd/demos/adler_2022a/plotting.py --figures all
uv run python packages/omd/demos/adler_2022a/compare.py --figures all
```

Sanity checks against paper trends (read these from
`figures/paper/fig{N}.png`):
- **Fig 7**: mission-based should be ~-1.3% below single_point at
  300 nmi, asymptoting to ~-0.25% at 2900 nmi. Multipoint should be
  ~-0.2% at all ranges.
- **Fig 9**: climb fuel fraction ~73% at 300 nmi → ~10% at 2900 nmi
  (the dominant trend that motivates mission-based).
- **Fig 12**: mission-based wing weight ~-25% vs single_point at
  300 nmi → ~-5% at 2900 nmi.
- **Fig 13**: single_point_plus_climb between mission-based and
  single_point at all ranges (paper's "low-cost objective" claim).

### 4.4 (Optional) fine-mesh validation

After 4.3, pick one cell to validate against the paper's absolute
fuel-burn numbers (paper Tables 5/6/7) at full mesh:

```bash
uv run python packages/omd/demos/adler_2022a/sweep.py \
  --grid 1500 --methods mission_based --fine-mesh
```

Single cell, ~24 h at fine mesh. Expected: mission-integrated fuel
within ~1% of paper Table 6 mission_based row (`11141.58 kg`).

---

## Anti-patterns (things the previous session did that didn't help)

- **Killing SLSQP early because "it should be done by now".** The
  optimizer was making real progress when killed at iter 26
  (~5% objective reduction). Paper-quality optima need 50-100+ iters
  at the current settings; with Phase 1.4 settings, ~30-50 iters
  should suffice.
- **Falling back to analysis-mode and rendering "comparison" PNGs.**
  Analysis-mode at default DVs gives the *same* wing for every
  method, so the comparison plots are definitionally meaningless.
  Don't do this.
- **Running `--workers 4` with the OAS internal mp.Pool conflict.**
  All cells fail silently in <30 s. Phase 1.5 is a hard
  prerequisite for any worker > 1.
- **Implementing a "placeholder text in figure" for fig9 / fig11.**
  Real placeholders are NotImplementedError, not a PNG that looks
  like a finished figure. Anyone glancing at
  `figures/reproduced/fig11.png` thinks it ran.
