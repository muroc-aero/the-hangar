# the-hangar / range-safety boundary

This document inventories the contract surface between the public
`the-hangar` workspace and the private `range-safety` repo. It records
what `the-hangar` provides for `range-safety` to consume, and what
`range-safety` provides back. It is the only boundary document that
lives in `the-hangar`. The dashboard design and the build roadmap live
in the `range-safety` repo (`docs/` there), because they describe code
that ships in `range-safety`.

`range-safety` is consumed here as a git submodule at
`packages/range-safety`, and is a member of the uv workspace. It depends
on the open packages below; the open packages never import
`range-safety`.

## What the-hangar provides (consumed by range-safety)

These are the stable contracts the dashboard reads. Treat the listed
modules as the public surface; internal helpers are not contracts.

### Provenance / analysis database (read-only)
- `hangar.omd.db.init_analysis_db(db_path=None)` -- open the analysis DB.
- `hangar.omd.db.query_run_results(run_id, variables=None) -> list[dict]`
  -- run-case rows: `{iteration, case_type, timestamp, data}`.
- `hangar.omd.db.query_entity(entity_id) -> dict | None` -- single entity
  by id (e.g. `"<plan_id>/v<N>"`).
- `hangar.omd.db.query_provenance_dag(plan_id) -> dict` -- entities,
  activities, edges for a plan.
- Schema: `entities` / `activities` / `prov_edges` / `run_cases`.
  Entity types in `hangar.omd.db.KNOWN_ENTITY_TYPES` (includes
  `requirement`, `acceptance_criterion`, `decision`, `run_record`,
  `assessment`, `phase`). PROV relations in `KNOWN_PROV_RELATIONS`
  (includes `satisfies`, `violates`, `verifies`, `justifies`,
  `precedes`, `executes`).

  > Decoupling note: this extraction has landed (PR #21, 2026-05-29). The
  > read-only query functions + schema constants live in the thin
  > `hangar-results-reader` package (`hangar.results_reader.db`), so
  > `range-safety` reads results without OpenMDAO as a transitive
  > dependency. `hangar.omd.db` re-exports them for back-compat; new code
  > should import from `hangar.results_reader` directly.

### Cross-tool session provenance (read-only)
- `hangar.sdk.provenance.db` -- `sessions`, `tool_calls`, `decisions`,
  `cross_references` tables; `get_session_graph(session_id) -> dict`
  returns `{nodes, edges}` (node types `tool_call`, `decision`).

### Session requirements + conclusions (read-only)
The sdk session servers (oas / ocp / pyc) persist the gather/conclude data the
dashboard's `SdkSessionSource` renders for those stages:
- `hangar.sdk.provenance.db.get_requirements(session_id) -> list[dict]` -- the
  requirements set via `set_requirements` / `configure_session`, each
  `{path, operator, value, label, ...}`. Drives the Gather stage and the
  per-requirement verdict replay.
- `hangar.sdk.provenance.db.get_conclusion(session_id) -> dict | None` -- the
  concluding artifact for the session, or `None`. Payload:
  `{verdict, narrative, metrics, requirements, run_id, conclusion_id,
  created_at}`, where `verdict` is `meets` / `fails` / `partial` / `open` and
  each `requirements[]` entry carries a per-requirement `verdict`
  (`satisfies` / `violates` / `open`) with its `criteria`. A non-`None` result
  flips the Concluding stage to `populated` and scores the Report view.
- Storage: a conclusion is a `decisions` row with
  `decision_type = "conclusion"`, the verdict in `selected_action`, and the full
  payload JSON in the `decisions.metadata_json` column (added by a migration in
  `init_db`). `list_sessions` exposes a cheap `conclusion_count` so the study
  selector need not read each payload.
- Producer side (not consumed by the dashboard, listed for context): the
  `record_conclusion` MCP tool / CLI command on oas / ocp / pyc derives the
  verdict from the persisted requirements vs. the chosen run via
  `hangar.sdk.provenance.conclusion.derive_conclusion` (auto-derived, agent
  supplies only the run id + narrative) and persists it with
  `record_conclusion`. Optimization envelopes nest finals under
  `results.final_results`; `derive_conclusion` overlays that sub-dict so paths
  like `CL` / `CD` resolve.

### Plan schema
- `hangar.omd.plan_schema` -- the plan JSON Schema. Relevant sections for
  the dashboard: `metadata` (`version`, `parent_version`, `content_hash`),
  `requirements` (with `acceptance_criteria`, `status`, `traces_to`),
  `decisions` (with `alternatives_considered`, `element_path`),
  `analysis_plan` (`phases`, `replan_triggers`), `design_variables`,
  `constraints`, `objective`.

### Plan diff
- `hangar.omd.provenance.provenance_diff(plan_id, version_a, version_b, db_path=None) -> dict`
  -- returns `{plan_id, version_a, version_b, entity_a, entity_b, changes, content_changed}`.
  `changes` is currently a shallow top-level-key diff
  (`{key, action}` with action in `added|removed|modified`). The
  plan-diff graph view needs element-level granularity; the deeper diff
  is implemented in `range-safety`, not here (see
  `DESIGN_data_contract.md` in range-safety).

### Plot rendering
- Target contract (per the split branch `claude/hangar-repo-separation-KoJOR`):
  `hangar.viewer.embedded.generate_plot_png(run_id, plot_type) -> bytes`
  and the open registry `hangar.sdk.viz.plot_registry`
  (`register_plot_types`, `register_plot_generator`,
  `register_viewer_route`).
- On current `main` the equivalent lives in
  `hangar.sdk.viz.viewer_server`. `range-safety` calls it behind a thin
  one-file adapter so the import re-points when the split lands. The
  split branch is a reference draft; it may not merge verbatim, but the
  dashboard targets its intended boundaries.

### Multi-tool provenance reader (target contract)
- `hangar.viewer.reader.MultiDBProvenanceReader` (split branch) merges
  sessions/graphs across tool DBs. The dashboard read model targets this
  interface; until it lands, the read model opens DBs directly through
  the results-reader seam.

### Catalog and slots
- `hangar.omd.slots.list_slot_providers() -> list[str]` -- known slot
  provider names (already used by the structural validator).
- `catalog/` reference data (component types, archetypes, recommended DV
  ranges). Destined to become `hangar-catalog`; locate via
  `HANGAR_CATALOG_DIR` rather than a hard path.

## What range-safety provides

The existing validation surface, plus the new dashboard.

### Plan validation (pre-run)
- `hangar.range_safety.validators.validate_structural(plan, catalog_dir=None)`
- `hangar.range_safety.validators.validate_traceability(plan)`
- `hangar.range_safety.validators.validate_heuristics(plan, catalog_dir=None)`
  Each returns `list[{check, severity, message}]`.

### Run assertions (post-run)
- `hangar.range_safety.assertions.assert_convergence(run_id, db_path=None)`
- `hangar.range_safety.assertions.assert_constraints(run_id, plan, db_path=None, tol=1e-6)`
  Each returns `{passed, checks, summary}`.

### CLI
- `range-safety validate <plan>` and `range-safety assert <run_id> --plan <plan>`.

### Dashboard (new)
- A state-machine dashboard (Gather Requirements, Planning,
  Executing, Verifying, Concluding) served by a Starlette app, consuming
  the read-only contracts above. Design lives in the range-safety repo.

## Changes required in the-hangar to support this work

These are the only `the-hangar`-side changes the dashboard depends on.
They are tracked in the range-safety `ROADMAP.md`; listed here so the
public side knows what is expected of it.

1. **Public-workspace hygiene.** [Landed, PR #21, 2026-05-29.]
   `hangar-range-safety` is out of the committed root `pyproject.toml`
   workspace member list / dependency list and is added conditionally in
   `scripts/dev-setup.sh` when the submodule is present. An open-only
   clone without the private submodule `uv sync`s cleanly.
2. **Results-reader seam.** [Landed, PR #21, 2026-05-29.] The read-only
   query functions and schema constants are extracted from
   `hangar.omd.db` into `hangar-results-reader`, re-exported from
   `hangar.omd.db` for back-compat.
3. **Plot adapter stability.** [Open.] Keep a stable
   `generate_plot_png(run_id, plot_type) -> bytes` entry point across the
   viewer split so the dashboard adapter re-points with a one-line change.
