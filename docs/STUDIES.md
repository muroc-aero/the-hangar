# Studies: multi-case analysis layer (2026-06-11)

A *study* groups many sub-analysis cases under one spec. Each case is one
analysis/optimization run (for omd: one plan run). The layer is tool
independent: the core lives in `hangar.sdk.study`, runners adapt it to a
tool, and one study can mix runners across cases. The omd runner is the
first (and currently only) adapter.

## Where things live

| Piece | Location |
|---|---|
| Core (schema, expansion, review, store, orchestration) | `packages/sdk/src/hangar/sdk/study/` |
| omd runner adapter | `packages/omd/src/hangar/omd/study_runner.py` |
| CLI | `omd-cli study validate/review/generate/run/status/results` |
| MCP tools (omd server) | `review_study`, `run_study`, `get_study_status`, `get_study_results` |
| Study state | `hangar_data/studies/{study_id}/` (`HANGAR_STUDY_DIR` to override) |
| Case run provenance | each tool's own store (omd: analysis.db `study` entity + `partOf` edges, `metadata.study` on case plans) |
| Demo | `packages/omd/demos/brelje_2018a/study/fig5_study.yaml` (study-layer port of `pipeline/sweep.py`) |
| Tests | `packages/sdk/tests/test_study.py`, `packages/omd/tests/test_study_runner.py` |

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

## Workflow (review-first, incremental)

```bash
omd-cli study validate study.yaml        # schema + expansion preflight
omd-cli study review   study.yaml        # case count, axes, compute estimate
omd-cli study generate study.yaml        # write case plan artifacts, no compute
omd-cli study run study.yaml --max-cases 4    # pilot batch, checkpointed
omd-cli study status  <study_id>         # progress counts
omd-cli study results <study_id>         # spreadsheet-style case table
omd-cli study run study.yaml --yes       # commit to the rest (resumes)
```

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
- [x] Per-case runner field (multi-tool studies once more runners exist)
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
- [ ] **Non-omd runners**: oas/ocp/pyc-native runners (case spec = tool
      CLI/script payload), then a cross-tool demo study; runner discovery
      via entry points so `study run` works without importing omd.
- [ ] **Standalone study CLI** (`hangar-study` or similar) once a second
      runner exists; `omd-cli study` stays as an alias.
- [ ] **Study-level requirements/conclusions**: acceptance criteria over
      aggregate outputs ("all cells converged", "min margin > 0"),
      `record_conclusion` for studies.
- [ ] **Derived columns** in outputs (unit conversions, expressions like
      `fuel_lb / range_nm`) instead of post-processing the CSV.
- [ ] **Concurrent-orchestrator safety**: state.json assumes a single
      orchestrator process; add a lock file if studies ever run from two
      hosts/processes at once.
- [ ] **Brelje fig6 spec + full-grid re-verification** via the study layer
      (warm_from depends on the retry-heuristics item); then port the
      Adler 2022a demo onto studies when it lands.
- [ ] **Case-level artifacts browsing** in the dashboard (link from a case
      row to its generated plan YAML and N2/plots of its run).
