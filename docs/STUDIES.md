# Studies: multi-case analysis layer (2026-06-11)

A *study* groups many sub-analysis cases under one spec. Each case is one
analysis/optimization run (for omd: one plan run; for oas/ocp/pyc: one
workflow script). The layer is tool independent: the core lives in
`hangar.sdk.study`, runners adapt it to a tool, and one study can mix
runners across cases (different `runner:` per matrix block or manual
case). Runners load lazily from installed packages via the
`hangar.study_runners` entry-point group, so no orchestrating package
needs to import the tools.

## Where things live

| Piece | Location |
|---|---|
| Core (schema, expansion, review, store, orchestration) | `packages/sdk/src/hangar/sdk/study/` |
| Generic script runner (any sdk-CLI tool registry) | `packages/sdk/src/hangar/sdk/study/script_runner.py` |
| Runner adapters | `packages/{omd,oas,ocp,pyc}/src/hangar/*/study_runner.py` + `hangar.study_runners` entry points |
| Standalone CLI (no omd needed) | `hangar-study validate/review/generate/run/status/results/runners` |
| omd CLI alias | `omd-cli study ...` (same commands) |
| MCP tools (omd server) | `review_study`, `run_study`, `get_study_status`, `get_study_results` |
| Study state | `hangar_data/studies/{study_id}/` (`HANGAR_STUDY_DIR` to override) |
| Case run provenance | each tool's own store (omd: analysis.db `study` entity + `partOf` edges, `metadata.study` on case plans; script runners: the tool's run_id in `run_ref`) |
| Demos | `packages/omd/demos/brelje_2018a/study/fig5_study.yaml` (133-case omd MDO grid), `packages/oas/examples/alpha_span_study/` (oas script study + oas/pyc cross-tool study) |
| Tests | `packages/sdk/tests/test_study.py`, `test_script_runner.py`; `packages/omd/tests/test_study_runner.py`, `test_study_cross_tool.py`; per-tool smoke suites |

## The spec (study.yaml)

```yaml
metadata: {id: my-study, name: "...", version: 1}
defaults:
  runner: omd                       # per-case override allowed
  spec: {plan: ../base/plan.yaml, mode: optimize, timeout_seconds: 1800}
cases:
  - matrix:                         # DOE-style cartesian expansion
      id_template: "r{range:g}-e{energy:g}"
      axes:
        range:  {linspace: [300, 800, 11]}
        energy: {values: [250, 500, 750]}
      bind:                         # every axis MUST bind to >=1 plan path.
        range:                      # NOTE: use block lists (or quote the
          - components[mission].config.mission_params.mission_range_NM
        energy:                     # strings) -- bare [id] selectors break
          - components[mission].config.mission_params.battery_specific_energy
                                    # YAML flow-sequence parsing.
  - case:                           # manual insertion of an arbitrary case
      id: reference-cell
      params: {range: 500, energy: 450}
      spec:
        plan: ../other/plan.yaml    # any plan artifact, or set/initial patches
        initial: {cruise.hybridization: 0.05841}
multistart:                         # optional: N variants per case, keep best
  presets: {low: {initial: {...}}, high: {initial: {...}}}
  pick: {output: mixed_objective, mode: min}
execution:
  workers: 2
  est_case_seconds: 240             # seeds the review estimate
  review_threshold: 12              # bigger batches need --yes / confirm
  guard_max_cases: 300              # expansion hard cap
outputs:                            # case-table columns, runner-interpreted paths
  - {name: MTOW_kg, path: "ac|weights|MTOW"}
```

### Script-runner case specs (oas, ocp, pyc)

Tools whose CLI is built on `hangar.sdk.cli` get their runner from the
generic script runner (`hangar.sdk.study.script_runner`): a case is a
workflow script, the same `[{tool, args}]` JSON `*-cli run-script`
executes, run in-process and stopped at the first failing step.

```yaml
defaults:
  runner: oas
  spec:
    script: scripts/aero.json       # or inline steps: [...] -- give steps
                                    # an "id" so bind paths can address them
    steps:
      - {id: surf, tool: create_surface, args: {name: wing, num_y: 7, ...}}
      - {id: an, tool: run_aero_analysis, args: {surfaces: [wing], alpha: 2.0}}
    success_when:                   # optional: map a result field to
      step: an                      # converged/failed (oas optimization:
      path: validation.passed       # results.success; default is
                                    # "completed" when all steps ok)
cases:
  - matrix:
      axes: {alpha: {values: [0, 2, 4]}}
      bind:
        alpha:
          - steps[an].args.alpha    # set_by_path into the step list
outputs:
  - {name: CL, path: "an:results.CL"}   # "step_ref:dotted.path" into that
                                        # step's response envelope
```

`$prev.run_id` / `$N.run_id` interpolation works exactly as in
`run-script`; multistart presets patch steps via the same `set` shape. The
runner calls the tool's `reset` before each case so pool workers don't
leak session state between cases, and `run_ref` is the last `run_id` a
step returned (`run_ref_step: <id>` to override).

## Workflow (review-first, incremental)

```bash
hangar-study validate study.yaml         # schema + expansion preflight
hangar-study review   study.yaml         # case count, axes, compute estimate
hangar-study generate study.yaml         # write case input artifacts, no compute
hangar-study run study.yaml --max-cases 4     # pilot batch, checkpointed
hangar-study status  <study_id>          # progress counts
hangar-study results <study_id>          # spreadsheet-style case table
hangar-study run study.yaml --yes        # commit to the rest (resumes)
hangar-study runners                     # registered + discoverable runners
```

`omd-cli study <same commands>` is an equivalent alias when hangar-omd is
installed; both resolve runners through entry-point discovery, so a mixed
oas/omd study runs from either.

Design decisions baked in:

- **Blowup guard.** Expansion hard-fails past `guard_max_cases`; `run`
  refuses more pending cases than `review_threshold` without `--yes` or a
  `--max-cases` batch. The MCP `run_study` always requires `max_cases`
  (1-25), so agents are forced into the review -> pilot -> continue loop.
- **Checkpoint-first.** Every case completion is written to
  `state.json` + `cases.csv` before the next is processed. Resume is by
  `case_key` (hash of runner+spec+params): editing a case re-runs exactly
  the cases the edit touched; removed cases keep their history flagged
  `in_spec: false`.
- **Plan artifacts.** Generated case plans are real reviewable YAML under
  `studies/{id}/cases/{case_id}/plan.yaml`, stamped with
  `metadata.study`/`metadata.case_id`, semantically validated at generate
  time (typos fail before compute), and copied into the omd plan store at
  run time.
- **Estimates sharpen.** The review wall-time estimate starts from
  `est_case_seconds` and switches to the observed mean once cases finish.

## Main features (MVP, done)

- [x] Tool-independent core in `hangar.sdk.study` (no OpenMDAO/tool imports)
- [x] Matrix (DOE) expansion + manual case insertion, mixed in one study
- [x] Per-case runner field; cross-tool studies verified (oas + pyc demo,
      omd + oas test) with one case-table schema across tools
- [x] oas/ocp/pyc runners via the generic script runner
      (`hangar.sdk.study.script_runner`): case = run-script workflow,
      `success_when` validation gate, outputs from response envelopes
- [x] Runner discovery via `hangar.study_runners` entry points
- [x] Standalone `hangar-study` CLI (no omd dependency)
- [x] Deterministic case keys; resume; spec-edit invalidation
- [x] Review guard: case count, axis sizes, multistart multiplier, wall estimate
- [x] Incremental/pilot batches (`--max-cases`, MCP-capped batches)
- [x] Multistart presets with pick-best (port of sweep.py low/high brackets)
- [x] omd runner: plan artifact generation, semantic preflight, output
      extraction from the analysis DB, `study` entity + `partOf` provenance
- [x] Spreadsheet case table (`cases.csv`, `study results`, MCP
      `get_study_results`)
- [x] Progress tracking pollable over MCP (`get_study_status`)
- [x] Brelje 2018a Fig 5 demo spec (133 cases, review/generate verified)
- [x] range-safety dashboard: studies source + case-table view (submodule)

## Deferred backlog

- [ ] **Dashboard visuals beyond the table**: requirement-tracing view
      (case -> plan requirements -> verdicts), trade-space scatter,
      2-axis heatmap/contour rendering of output columns, sparkline per
      output across an axis.
- [ ] **Study-level plots in omd**: generic pcolormesh/contour provider
      over cases.csv when a study has exactly 2 numeric axes (the brelje
      fig5/fig6 render), replacing `pipeline/plotting.py`.
- [ ] **Retry heuristics**: nearest-neighbor warm starts and bracket
      retries (`retry_failed.py` / `retry_stuck_cells.py`) as
      `study retry`; cross-study `warm_from` (cost grid seeded from fuel
      grid).
- [ ] **DOE sampling strategies** beyond full-factorial + explicit lists
      (LHS, fractional, adaptive refinement near failures/ridges).
- [ ] **MCP study tools on the oas/ocp/pyc servers**: only the omd server
      exposes review/run/status/results today (and can run any runner via
      discovery when co-installed); factor the four tools into a shared
      sdk module and register them on every server.
- [ ] **Dashboard run-scoped views for non-omd cases**: the studyfs
      source's per-case results/plots delegate to the omd source, so
      oas/ocp/pyc `run_ref`s render the table row but not run detail;
      dispatch on the case's runner instead.
- [ ] **Per-step timeout for script runners**: omd cases have
      `timeout_seconds` through run_plan; script steps currently run
      unbounded.
- [ ] **Study-level requirements/conclusions**: acceptance criteria over
      aggregate outputs ("all cells converged", "min margin > 0"),
      `record_conclusion` for studies.
- [ ] **Derived columns** in outputs (unit conversions, expressions like
      `fuel_lb / range_nm`) instead of post-processing the CSV.
- [ ] **Concurrent-orchestrator safety**: state.json assumes a single
      orchestrator process; add a lock file if studies ever run from two
      hosts/processes at once.
- [ ] **Queued vs running status**: the orchestrator marks the whole
      submitted batch "running" at dispatch, so a 131-case batch shows
      running: 131 while only ~workers cases execute; add a "queued"
      status (done/total stays accurate; surfaced by the 2026-06-12
      fig5 verification run).
- [ ] **Brelje fig6 spec + full-grid re-verification** via the study layer
      (warm_from depends on the retry-heuristics item); then port the
      Adler 2022a demo onto studies when it lands. Fig5 verified
      2026-06-12: 126/133 cold-bracket convergence, every converged cell
      identical to the reference CSV (0.0000% delta); the 7 boundary
      failures are the retry-heuristics motivation, and a single-neighbor
      manual rescue (fig5_study_v2_rescue pattern) recovers convergence
      but can land in a worse basin (545 vs 468 at r700-e450), so the
      automated retry should be multi-neighbor + bracket like
      retry_stuck_cells.py.
- [ ] **Case-level artifacts browsing** in the dashboard (link from a case
      row to its generated plan YAML and N2/plots of its run).
