# Adler 2022a reproduction — Phase 0 capability matrix

Recorded 2026-04-28 from direct code inspection of files at HEAD
(`adler-2022a-demo` branch, working dir clean for the demo subtree).
Where a row claims something runs, it was confirmed by either an
analysis-mode run or by running `omd-cli validate`. All `works?`
verdicts apply only to `--mode analysis` unless noted; no
`--mode optimize` cell has actually moved a DV (see "Sweep / retry"
notes below).

The columns are:

- **implemented?** — code exists and looks load-bearing
- **works?**       — verified by running it (validate / analysis)
                    or by reading a recorder file produced by it
- **location**     — file:line of the relevant code
- **notes**        — verifier observations and discrepancies vs TODO

---

## Factory `oas/AerostructFixedPoint`

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| Builds standalone om.Problem at N fixed flight points | yes | yes | factories/oas_aerostruct_fixed.py:322 | analysis run produced fuel_burn_kg=7726.293493 at 1500 nmi single_point in 130 s |
| `single_point` mode (1 cruise pt + maneuver + Bréguet) | yes | yes | factories/oas_aerostruct_fixed.py:261 | Bréguet ExecComp form matches paper Eq. 1; verified analysis run |
| `multipoint` mode (5 cruise pts averaged) | yes | not run | factories/oas_aerostruct_fixed.py:272 | plan validates; arithmetic is `(sum) / n_cruise` per ExecComp on line 289 |
| `single_point_plus_climb` mode (cruise Bréguet + Eq. 2 climb) | yes | not run | factories/oas_aerostruct_fixed.py:291 | plan validates; ExecComp on line 300 implements Adler Eq. 2 |
| CL=W/qS lift balance at each point (no alpha DV) | yes | yes | factories/oas_aerostruct_fixed.py:163 | `cl_passthrough` sets fltcond_CL = CL_target; AerostructDragPolar surrogate evaluated at that CL |
| 2.5 g maneuver sizing group with KS-aggregated failure | yes | yes | factories/oas_aerostruct_fixed.py:475 | uses `_OasManeuverGroup` with `self_feedback_W_wing=True`; `failure_maneuver` and `2_5g_KS_failure` (alias) both promoted |
| Wing weight feedback from maneuver to weight slot | n/a | n/a | — | Bréguet variant doesn't have a weight slot; `W_wing_maneuver` is just an output. The mission_based plan uses `ocp/parametric-weight` with `use_wing_weight: true` |
| B738 / paper-specific defaults removed (post Phase 1.0) | no | — | factories/oas_aerostruct_fixed.py:30-52 | `_DEFAULT_MTOW_KG=79002.0`, `_DEFAULT_TSFC_G_PER_KN_S=17.76`, `_DEFAULT_MANEUVER` (M0.78, 20kft) all hard-coded at module level; module docstring still references "the Adler 2022a reproduction demo" |
| Renamed to `oas/AerostructBreguet` (post Phase 1.0) | no | — | registry.py:228 | factory file name and registry key still `AerostructFixedPoint` |
| Has unit tests covering >1 aircraft template (post Phase 1.0) | no | — | — | no `tests/factories/test_oas_aerostruct_breguet.py` (or _fixed.py); `find packages/omd/tests -name 'test_*aerostruct*fixed*'` returns nothing |

## omd SDK plumbing

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| Factory registered in `registry.py` | yes | yes | registry.py:223-234 | wrapped in `try/except ImportError`; appears in `omd-cli` factory list |
| Plot provider registered (currently NO — Phase 1.1) | no | — | registry.py:227-229 | `register_factory("oas/AerostructFixedPoint", build_oas_aerostruct_fixed)` — no `plot_provider=` kwarg. `omd-cli plot --list-types` for a FixedPoint run reports only generic types |
| `plan_validate.py` recognises objective `fuel_burn_kg` and constraint `2_5g_KS_failure` short names | yes | yes | plan_validate.py:49-50 | both names present in `_OAS_COMMON`; all 4 lane B plans pass `omd-cli validate` |
| `plan_schema.py` accepts vector DV bounds (`lower: [...]` / `upper: [...]`) | yes | yes | plan_schema.py:342-353 | `oneOf: number | array`; twist_cp / toverc_cp use vector lower in all four plans, all validate |
| CaseReader emits per-phase fuel paths fig9 needs (`{climb,cruise,descent}.fuel_used_final` for mission_based) | yes | yes | (out-of-tree, pulled from a prior recording at run-20260420T205727-f03713d8) | confirmed all three exist in the mission_based recorder; sweep.py does NOT propagate them to the row (see Sweep / retry below) |
| CaseReader emits per-panel `wing_sec_forces` fig11 needs | partial | — | recorder | `maneuver.aerostructural_maneuver.aerostruct_point.coupled.aero_states.wing_sec_forces` exists. There is NO equivalent under any `cruise_*` path — `AerostructDragPolar` is a surrogate over precomputed VLM, so the cruise-segment panel forces are not exposed at all. Phase 1.3 will need to extract maneuver lift only (or compute cruise lift indirectly from the surrogate's training mesh) |

## Lane B plans

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| Convention: `**/plan.yaml` ignored, lane_b plans force-added | yes | yes | packages/omd/.gitignore:3 | `git ls-files` confirms all four plan.yaml files are tracked despite the gitignore rule. No modular `components/` tree exists for any of them — they are not assembled. Refactor decision is open |
| `single_point/plan.yaml` validates and runs analysis-mode | yes | yes | lane_b/single_point/plan.yaml | `omd-cli validate` passes; analysis run completed in 130 s with run_id run-20260428T090219-0ac31ea9, fuel_burn_kg=7726.293493 |
| `multipoint/plan.yaml` validates and runs analysis-mode | yes | partial | lane_b/multipoint/plan.yaml | `omd-cli validate` passes; not run in this Phase 0 inspection (would take ~5x longer for 5 surrogates) |
| `single_point_plus_climb/plan.yaml` validates and runs | yes | partial | lane_b/single_point_plus_climb/plan.yaml | `omd-cli validate` passes; not analysis-run in this inspection |
| `mission_based/plan.yaml` validates and runs analysis-mode | yes | partial | lane_b/mission_based/plan.yaml | `omd-cli validate` passes; not re-run in this inspection (a prior recording at run-20260420T205727-f03713d8 exists with the expected per-phase fuel paths) |
| All four converge in `--mode optimize` | no | no | results/sweep_coarse.csv | the existing 12-row CSV has every cell at AR=9.45, taper=0.159, c4sweep=25.0 (the factory IVC defaults) and W_wing_maneuver=5518.51 — the optimizer did not move any DV. Wall times 111-140 s ≈ a single function eval. These rows are functionally analysis-mode despite `converged=True` |
| All four use sane SLSQP settings | no | — | each plan.yaml lines ~70 | `tol: 1.0e-6` (too tight, see TODO Phase 1.4); `objective.scaler: 1.0e-3` (Bréguet) or `1.0e-4` (mission_based); `maxiter: 150` |

## Lane A

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| `aerostruct_mdo.py --method single_point` runs | yes | partial | lane_a/aerostruct_mdo.py:34 | calls the factory directly with the same config as lane_b/single_point; not run end-to-end in this inspection but the analysis-mode parity claim (7726.293493 kg both lanes) remains supported by the lane_b run today |
| `aerostruct_mdo.py --method mission_based` runs | yes | not run | lane_a/aerostruct_mdo.py:99 | imports `upstream/openconcept/openconcept/examples/B738_aerostructural.py`; depends on that upstream clone being present (it is — see `upstream/` in repo root) |
| Lane A vs Lane B parity test in analysis mode passes | claim only | — | TODO.md:65-66 | TODO claims "BIT-IDENTICAL ... 7726.293493 kg both" at 1500 nmi single_point. Today's lane B analysis run reproduces 7726.293493493… kg. Lane A not re-run today; parity not re-verified end-to-end |
| Lane A vs Lane B parity test in optimize mode passes | no | no | — | neither lane has a converged optimize run |

## Lane C

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| `aerostruct_mdo.prompt.md` is current re lane B plan structure | yes | n/a | lane_c/aerostruct_mdo.prompt.md | references the four method names, factory `oas/AerostructFixedPoint`, `oas/aerostruct` drag slot, `pyc/surrogate` HBTF propulsion, `ocp/parametric-weight`, `oas/maneuver` — matches the actual plans. Will go stale after Phase 1.0 rename |

## Sweep / retry

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| `sweep.py --grid coarse --workers 1` runs | yes | partial | sweep.py:359-363 | the existing `results/sweep_coarse.csv` was apparently produced via this codepath. Cells "succeed" but at default DVs only (see lane B optimize note above) |
| `sweep.py --grid coarse --workers >1` runs | no | no | sweep.py:362-363 | no fix for the OAS internal `multiprocessing.Pool()` (Phase 1.5). `OMP_NUM_THREADS` is not set, no monkey-patch, no `pool_processes` kwarg threaded to AerostructDragPolar |
| `--fine-mesh` flag bumps to num_y=27 correctly | yes | not run | sweep.py:136-152 | code patches `surface_grid`, `maneuver`, and slot configs to num_x=3/num_y=27. Logic looks right but no run has exercised it |
| `--warm-from` reads prior CSV and seeds DVs | partial | not run | sweep.py:296-310 | only seeds the three scalar fields in `_WARM_FIELDS` (AR, taper, c4sweep_deg). twist_cp/toverc_cp/skin/spar are NOT warm-started even though the prior cell's converged values would be the most useful for those |
| CSV columns include per-phase fuel for fig9 | no | no | sweep.py:47-56 | `COLUMNS` has no climb_fuel_kg / cruise_fuel_kg / descent_fuel_kg; `_OUTPUT_KEYS` lists them (lines 76-77) but `_run_one` does not put them into the row at lines 244-255 |
| Per-design JSON dumps spanwise DVs for fig10 | yes | yes | sweep.py:192-212 | `_persist_per_design` writes twist_cp_deg / toverc_cp / skin_cp_m / spar_cp_m. `results/per_design/{300,900,1500,2900}/{single_point,multipoint,single_point_plus_climb}.json` exist on disk but contain the default-IVC values (no real optimization happened) |
| Per-design JSON dumps panel forces for fig11 | no | no | sweep.py:192-212 | `_persist_per_design` payload has no `lift_dist_*_N`. `_OUTPUT_KEYS` does not list `wing_sec_forces` paths either |
| `retry_failed.py` resumes from neighbour DVs after failures | yes | not run | retry_failed.py:23-73 | imports from sweep.py and reuses `_run_one`. Builds warm dicts from same-method nearest-range converged neighbours. Inherits the same partial-warm-start limitation (only AR/taper/sweep) |

## Plotting

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| `fig7` renders from sweep CSV | yes | yes | plotting.py:61-82 | `figures/reproduced/fig7.png` exists from a prior run but is meaningless (CSV has no real optima — every method has the same default DVs, so the % difference vs single_point is 0 for everyone) |
| `fig9` renders real data | no | no | plotting.py:85-118 | falls into the placeholder branch (line 92) because `climb_fuel_kg` is not a CSV column. Output is a text-box PNG that *looks* like a finished figure |
| `fig10` renders from per-design JSON | yes | partial | plotting.py:133-175 | reads JSON payloads correctly. Works as code, but currently plots default-IVC values for all three methods — same shape, useless content |
| `fig11` renders real data | no | no | plotting.py:178-202 | pure placeholder text-box. No code anywhere touches `wing_sec_forces` |
| `fig12` renders from sweep CSV | yes | yes | plotting.py:205-226 | same caveat as fig7 — code OK, data not real yet |
| `fig13` renders without dead `if False` branch | yes | yes | plotting.py:229-238 + plotting.py:309-310 | the `fig13()` function (line 229) is unreachable dead code with a broken `._with_suffix(".png")` that would raise if called. `main()` bypasses it and calls `_render_fig7_with_methods(df, "fig13")` directly. Output PNG is correct (because the helper is fine) — but the `fig13()` function as written is not just oddly structured, it would crash if anyone imported and called it |
| `compare.py` composes paper-vs-reproduced for all 6 figures | yes | yes | compare.py:23-42 | side-by-side composer using PIL; produces `figures/comparison_fig{7,9,10,11,12,13}.png` (all 6 exist on disk from a prior run). Only the *paper* halves are meaningful right now; the reproduced halves are anti-pattern outputs (fig9/11 placeholder + fig7/10/12/13 default DVs) |

## Reference data

| Capability | implemented? | works? | location | notes |
|---|---|---|---|---|
| Paper figure crops at `figures/paper/fig{7,9,10,11,12,13}.png` | yes | n/a | figures/paper/ | all six PNGs present (32-95 kB each) |
| Paper figure README documenting crop procedure | no | — | — | TODO Background promised `figures/paper/README.md`; not present |
| Paper Tables 5/6/7 transcribed to `paper_data.py` | no | — | — | `paper_data.py` does not exist |
| Paper Fig 7/12/13 trend curves digitized to `figures/paper/digitized/fig*.csv` | no | — | — | `figures/paper/digitized/` does not exist |
| Parity test `tests/test_adler_paper_parity.py` | no | — | — | not present |

---

## Summary of discrepancies vs TODO Background

The TODO Background section is largely accurate. Notable refinements:

1. **The existing `results/sweep_coarse.csv` is more misleading than
   TODO suggests.** TODO says "no figure has been reproduced because
   optimization mode does not converge in tractable wall time." The
   CSV that exists actually has every cell marked `converged=True`
   with wall_time ~120 s. Inspection shows every cell is at the
   factory's default IVC values (AR=9.45, taper=0.159, c4sweep=25,
   W_wing=5518.51), so SLSQP exited without moving any DV. Whatever
   produced these rows did not actually optimise — likely a single
   function eval with `tol` satisfied trivially. This is the
   anti-pattern TODO calls out in the bottom of the file.

2. **`fig11` cruise lift extraction is harder than TODO 1.3
   implies.** TODO says to add
   `cruise_0.drag.aero_analysis.aerostruct_point.aero_states.wing_sec_forces`
   to `_OUTPUT_KEYS`. That path does not exist in the recorder. The
   cruise drag is computed by `AerostructDragPolar` — a Kriging
   surrogate over precomputed VLM evaluations — and does not expose
   per-panel forces at all. Only the maneuver group exposes
   `wing_sec_forces`. Phase 1.3 will need to either (a) plot maneuver
   lift only, (b) reach into the surrogate's training mesh and
   reconstruct cruise lift from there, or (c) skip cruise and just
   show the 2.5 g maneuver — but it cannot work as TODO 1.3 currently
   describes.

3. **`fig13()` function is dead code, not "structurally wrong but
   working."** `main()` (plotting.py:309-310) routes around it and
   calls `_render_fig7_with_methods` directly, so the rendered PNG is
   correct. But `fig13()` itself contains
   `fig7(...)._with_suffix(".png")` which would raise `AttributeError`
   the moment anyone called it (Path has no `_with_suffix`; that's a
   typo for `with_suffix`). Phase 1.6 should just delete the function.

4. **`--warm-from` is partial.** TODO row "reads prior CSV and seeds
   DVs" is correct in the literal sense, but only the three scalar
   DVs (AR, taper, c4sweep_deg) are warm-started. The 11 vector DV
   elements (twist_cp, toverc_cp, skin, spar) are not — even though
   those are exactly the DVs whose warm starts would matter most.
   Worth noting in Phase 1.4 / Phase 4 work, even though TODO does
   not flag it explicitly.

5. **No `paper_data.py`, no digitized fig CSVs, no parity test.** All
   three are listed as TODO Phase 1.7 / Phase 2.3 follow-ups; just
   confirming none exist yet.

---

## Phase 2 outcome (2026-04-28)

Phases 1.0–1.8 (PR1 + PR2) and Phase 2.1 + 2.3 are complete. Phase 2.2
paper-spec mesh is set up but not run (4–12 h compute).

### Phase 2.1 — smoke run at lane_b/single_point/plan_smoke.yaml

- `plan_smoke.yaml` (300 nmi, num_x=2, num_y=5, tol=1e-4) is committed.
- First run **failed** in the documented mode: NLBGS in
  `cruise_0.drag.training_data` failed to converge in 100 iterations and
  the `AnalysisError` killed SLSQP on first probe (TODO Background
  item 2).
- Mitigation: the Bréguet factory now monkey-patches `om.Problem.setup`
  at module load (`oas_aerostruct_breguet.py` `_apply_aerostruct_solver_patch`)
  to bump NLBGS `maxiter` from 100 to 500 on any subsystem named
  `coupled` whose nonlinear solver is the OAS aerostructural NLBGS. The
  patch is no-op on Problems without OAS topology, so other tests are
  unaffected; `pytest -m "not slow"` stays at 296 passed / 7 skipped.
- Retry **converged**: `run-20260428T154640-0824cd42`,
  `Status: converged`, 31 recorded cases, ~19 min wall time.
- All 9 plot types render
  (`omd-cli plot run-... --type all` produced
   convergence, dv_evolution, n2.html, planform, twist, mesh_3d,
   thickness, skin_spar, t_over_c).

### Smoke DVs vs paper Table 5 single_point at 300 nmi

| DV | smoke (num_y=5) | paper Table 5 | comment |
|---|---|---|---|
| AR | 7.216 | 10.401 (UB) | smoke decreased; paper wants UB |
| taper | 0.0344 | 0.168 | smoke at lower bound region |
| c4sweep | 25.22° | 23.046° | within 10 % |
| twist [tip→root] | [0, -1.78, -1.15, -1.29] | [0, 2.07, -2.86, -1.07] | shape disagrees |
| t/c [tip→root] | [0.133, 0.053, 0.077, 0.100] | [0.034, 0.086, 0.090, 0.118] | three-of-four at lower bound; tip thickened |
| skin (mm) [tip→root] | [20.93, 36.74, 45.50, 48.60] | [5.00, 14.94, 18.47, 19.15] | smoke ≈ 2-3× paper |
| spar (mm) [tip→root] | [6.49, 9.47, 11.88, 13.71] | [3.99, 3.0, 8.72, 5.43] | smoke higher across span |
| 2_5g_KS_failure | -0.94 (slack) | 2.8e-6 (active) | constraint not binding at smoke |
| Bréguet fuel_burn_kg | 1542.65 | 2770.44 (mission) | not directly comparable |

The smoke result at num_y=5 is the documented "directionally not
necessarily right" coarse-mesh outcome the TODO warned about. Phase
2.1's primary technical goal — demonstrating SLSQP CAN converge with
the Phase 1 plumbing and patches in place — is met. Real paper-parity
comparison waits for Phase 2.2 paper-spec mesh.

The bound-ordering hypothesis the TODO floated (lower bounds at wrong
end) was checked: per upstream openconcept docstring, spanwise cps are
ordered tip→root, and the plan's lower bound array
`[0.030, 0.053, 0.077, 0.10]` already brackets the paper values
correctly under that convention. Bounds are not inverted; the smoke-mesh
disagreement comes from the coarse-aerodynamics regime, not a bound bug.

### Phase 2.2 — paper-spec plan ready, not run

- `plan_paperspec.yaml` (300 nmi, num_x=3, num_y=27, tol=1e-5) is
  committed and validates. Expected wall time 4–12 h; not run in this
  session.

### Phase 2.3 — paper data + parity test

- `paper_data.py` was added in PR2 with full Table 5 transcription
  and partial Tables 6/7 entries.
- `tests/test_paper_parity.py` is present and `@pytest.mark.slow`.
  Reads `results/per_design/{rng}/{method}.json` for each cell, compares
  against `PAPER_TABLES[rng][method]` with a configurable
  `--paper-rel-tol` (default 0.20 for smoke mesh; pass 0.05 for paper
  spec). Skips cells whose JSON is absent or whose paper transcription
  has `None` for that field.
- The test will surface real comparisons once Phase 2.2 / Phase 4
  populate per_design dumps with optima.
