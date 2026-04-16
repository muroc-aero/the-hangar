# Deferred Enhancements (omd Plan Authoring)

This file documents capabilities that were intentionally scoped out of
the plan-authoring enhancement effort (which added the enriched
`requirements` / `decisions` schema, the `analysis_plan` section, the
plan knowledge-graph and provenance-DAG updates, and the
`omd-cli plan review` completeness checker).

Each item below records: what the capability is, why it was deferred,
what would be needed to pick it up later, and the signals that should
drive prioritization.

## 1. Phase execution in `omd-cli run`

**What.** An `omd-cli run <plan> --phase <id>` flag that runs a single
phase defined in `analysis_plan.phases`, evaluates its
`success_criteria` against the run results, records an `executes`
`prov_edge` from the phase entity to the run record, and gates
execution on `depends_on` (refuses to run a phase whose predecessor
has not succeeded).

Today, `analysis_plan` is captured as metadata only. The run pipeline
is unchanged by the plan-authoring work. Phases are visible in the
plan knowledge graph and provenance DAG, but the orchestration of a
phased campaign is still manual.

**Why deferred.** The change reaches into `run.py` and the run-record
schema, and it requires a success-criteria evaluation engine that
does not exist yet. The metadata-only form already captures the
intent where engineers look (the DAG viewer, `plan review`). No user
has asked for automatic phase gating yet, and the right design is
easier to find once real plans have been authored against the
enriched schema.

**What would be needed to pick it up.**

- `_evaluate_success_criteria(plan, phase, run_results) -> list[ReviewFinding]`
  in a new `packages/omd/src/hangar/omd/phase_eval.py`.
- Per-run metadata key capturing which phase a run corresponds to
  (either a new column on `run_records` or a JSON metadata field).
- Gating logic: before running a phase, assert that every
  `depends_on` predecessor has a successful run record.
- Register `executes` prov_edge emission in `run.py` when a
  phase-scoped run completes (the relation is already declared in
  `db.py:KNOWN_PROV_RELATIONS`).
- CLI surface: `omd-cli run <plan> --phase <id>`, optional
  `--skip-deps` for the explicit override case.
- Tests against the `oas_aerostruct_enriched` fixture exercising the
  two-phase campaign end to end.

**Signals to watch for.**

- A user asks to skip to a later phase or re-run a single phase.
- A user asks for automatic gating between phases.
- A third team adopts the enriched schema and starts writing multi-
  phase plans.

## 2. Acceptance-criteria verification loop

**What.** After a run completes, translate each
`requirement.verification.assertion` string into a concrete check
(ideally through `hangar.range_safety`), emit an `assessment` entity
linked to the requirement with a `satisfies` or `violates` relation,
and drive the requirement `status` (open → verified / violated) on
the basis of the result.

Today, `acceptance_criteria` and `verification.assertion` are stored
on requirements and rendered on the graph, but nothing checks them
automatically. Engineers still read the plot and decide by eye.

**Why deferred.** The assertion-expression grammar needs a design
pass (how do names resolve? which result scalars are exposed? which
variables ship as profiles?), and the automatic `status` transition
has UX subtleties (when does a `violated` requirement revert to
`open` after a replan?). The schema fields are useful as
documentation even without automation, so shipping them ahead of the
verification engine is a net gain.

**What would be needed to pick it up.**

- Assertion parser mapping short names (`failure`, `CL`,
  `structural_mass`) to run-result paths.
- Post-run hook in `run.py` that:
  - Loads the plan requirements,
  - Evaluates each `verification.assertion`,
  - Emits `satisfies` / `violates` prov_edges from the
    `assessment` entity to the requirement entity (relations are
    already declared).
- Requirement `status` update path: either mutate the stored plan
  YAML (cleanest for replan history) or store the status as an
  overlay in the provenance DB (cleanest for run independence).
- `range-safety` integration: translate simple comparators
  (`<=`, `<`, `>`, `>=`, `in`) into range-safety checks;
  passthrough for free-form assertion strings.
- Tests covering the matrix: satisfied criterion, violated
  criterion, missing metric, replan-after-violation.

**Signals to watch for.**

- A run violates a criterion and someone has to notice manually.
- A CI gating request lands.
- The first replan driven by automated verification.

## 3. Interactive plan builder (review item 5)

**What.** Step-by-step plan authoring via CLI (and MCP tool
equivalents) so that an agent or engineer can build a plan
incrementally with decision capture at each step, rather than
writing the full set of YAML files up front:

```
omd-cli plan init my-study/
omd-cli plan add-requirement my-study/ --interactive
omd-cli plan add-component my-study/ --type oas/AerostructPoint
omd-cli plan set-operating-point my-study/ --from-template cruise_M084
omd-cli plan set-solver my-study/ --recommend
omd-cli plan add-dv my-study/ --name twist_cp --recommend-bounds
omd-cli plan set-objective my-study/ --name structural_mass
omd-cli plan add-decision my-study/ --stage solver_selection
omd-cli plan set-analysis-strategy my-study/ --phases 2
omd-cli plan review my-study/
omd-cli plan assemble my-study/
```

**Why deferred.** Largest lift of the six review items. UX design
depends on seeing real plans written in the enriched schema and on
understanding which authoring steps are commonly skipped (which is
exactly what `omd-cli plan review` is for). Building the interactive
flow before the enriched schema has settled risks throwaway work.

**What would be needed to pick it up.**

- Partial-plan validator: the schema currently requires `metadata`
  and `components`; a partial-authoring flow needs a variant that
  accepts any valid sub-plan and surfaces what is still missing.
- Per-subcommand prompt flows (Click prompts, MCP-tool parameter
  collection).
- Per-step decision recording hook: auto-append a `decisions.yaml`
  entry capturing the author's rationale for the change just made.
- MCP-tool wrappers so agents can call `plan_add_dv`,
  `plan_add_decision`, etc., from a conversation.
- Completeness-aware review integration: the interactive flow runs
  `plan review` implicitly and highlights the specific missing
  section before prompting the user for it.
- Library-side: a lot of the logic is plan-mutation primitives
  (`add_requirement`, `add_component`), which belong in a new
  `packages/omd/src/hangar/omd/plan_mutate.py` so the CLI and MCP
  layers stay thin.

**Signals to watch for.**

- Users (human or agent) repeatedly build plans and ask for help at
  each step.
- `omd-cli plan review` consistently flags the same missing sections
  across plans, signalling where an interactive prompt would pay
  off most.

## 4. Problem DAG phase filter

**What.** Filter the problem / discipline DAG
(`packages/omd/src/hangar/omd/discipline_graph.py`,
`_omd_problem_dag_handler` in `cli.py`) by analysis phase so that a
"coarse mesh" configuration and a "refined mesh" configuration show
up as distinct views rather than a mashup.

**Why deferred.** Only meaningful once phase execution (item 1) lands
and different phases have materially different problem shapes. Today
a plan's problem DAG is single-valued, so a filter would have
nothing to filter.

**What would be needed to pick it up.**

- Phase-aware builder in `discipline_graph.py` that accepts a phase
  id and returns the problem graph for that phase's configuration.
- Viewer-side filter control (a dropdown in the toolbar listing
  declared phases).
- A phase-overlay representation (since phases modify the same
  underlying plan, diff-style rendering may be more useful than
  parallel views).

**Signals to watch for.**

- Phase execution ships.
- Users complain that the problem DAG shows a "Frankenstein" of
  phase configurations.
- Multi-phase plans start encoding materially different topologies
  (different solvers, different active components).

## Authoring ergonomics (discovered during the A320 / HBTF / integrated demos)

Three small rough edges surfaced while subagents authored plans using the
enriched schema end-to-end. None are blocking, but each cost an agent a
round-trip.

### `components/*.yaml` schema asymmetry

- **What:** Other modular files in a plan directory unwrap a single
  top-level key automatically (`decisions.yaml` containing
  `decisions: [...]`, `requirements.yaml` containing
  `requirements: [...]`, etc. -- see
  `packages/omd/src/hangar/omd/assemble.py:_merge_yaml_files`). But
  `components/*.yaml` expects a bare mapping (`id: ... type: ...
  config: {...}`) or a top-level list, never a
  `components: [...]` wrapper. When an agent wraps the single
  component in the list form, assembly fails with a misleading
  `"id" is a required property` schema error.
- **Why deferred:** Cosmetic. Agents hit it once and learn. But the
  error is misleading enough that a small fix is worth doing.
- **What would be needed to pick it up:** In
  `_merge_yaml_files`, detect the case where a per-component YAML
  file contains a single `components:` key and unwrap it. Or reject
  at load with a clearer message pointing at the bare-mapping form.
  Add a test fixture exercising both forms.
- **Signals:** repeated mentions by agents or users; any PR using
  `components/*.yaml` rejected with the misleading error.

### YAML colon-in-bullet footgun in rationale / decisions

- **What:** A bullet like `- Foo: the bar baz` in `rationale.yaml`
  or free-form fields of `decisions.yaml` parses as a mapping, not a
  string. PyYAML raises a duplicate-key or type error depending on
  the surrounding content.
- **Why deferred:** Standard YAML behaviour, and readable error once
  you know to look. The workaround -- quote the string or use a
  block scalar (`- >-`) -- is one line.
- **What would be needed to pick it up:** A pre-load pass that
  tolerates unquoted colon-bearing bullets in `rationale` and the
  free-form decision fields, or a `yamllint`-style warning emitted
  by `omd-cli validate` that points at the line. Document the
  workaround in `plan-authoring-workflow.md`.
- **Signals:** agents repeatedly silently quote-escape strings that
  don't actually need escaping; a user filing "my rationale broke"
  with a colon in the text.

### `omd-cli plot --type all` messaging in analysis mode

- **What:** In `--mode analysis` the generic `convergence` and
  `dv_evolution` plots emit
  `Need at least 2 driver cases` and skip. That's the expected
  state for a single-case analysis run, but the message reads like
  a warning.
- **Why deferred:** Cosmetic, no data impact.
- **What would be needed to pick it up:** In
  `packages/omd/src/hangar/omd/plotting/` (generic plots), detect
  single-case runs and emit `skipped (analysis mode: no driver
  history)` instead. Or suppress the message at INFO level.
- **Signals:** users asking why their analysis run "failed" to plot
  convergence.

## Cross-reference

- Implementation plan for the shipped work:
  `/home/alex/.claude/plans/confirm-and-critique-the-adaptive-manatee.md`
- Schema: `packages/omd/src/hangar/omd/plan_schema.py`
- Provenance: `packages/omd/src/hangar/omd/assemble.py`,
  `packages/omd/src/hangar/omd/db.py`
- Graph: `packages/omd/src/hangar/omd/plan_graph.py`,
  `packages/omd/src/hangar/omd/provenance.py`
- Checker: `packages/omd/src/hangar/omd/plan_review.py`
- CLI: `packages/omd/src/hangar/omd/cli.py`
  (see `omd-cli plan review`)
