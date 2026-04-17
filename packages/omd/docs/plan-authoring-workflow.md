# Plan Authoring Workflow

This document walks through the full end-to-end process of authoring
and running an omd plan using the interactive plan builder added in
April 2026. Before the builder existed, plans had to be hand-written
as a directory of YAML files; they still can be (the hand-authored
path is unchanged), but the builder is now the recommended entry
point for new plans.

## Summary of the pipeline

```
plan init ──┐
            ├──> modular YAML directory ──> assemble ──> plan.yaml ──> run
add-* ──────┤       (partial-valid)          (full-valid,             (results,
set-* ──────┤                                 versioned)               N2, DB,
add-decision ┘                                                         recorder)
plan review (any time)                                                   │
                                                                         ▼
                                                                     plot / results
                                                                     / provenance
```

Each `plan init` / `add-*` / `set-*` subcommand mutates exactly one
modular file (`metadata.yaml`, `components/<id>.yaml`, `requirements.yaml`,
`operating_points.yaml`, `solvers.yaml`, `optimization.yaml`,
`decisions.yaml`, `analysis_plan.yaml`). After every mutation the
on-disk partial plan is validated with
`hangar.omd.plan_schema.validate_partial` — missing top-level sections
are permitted, but structural errors in whatever is present fail
fast.

The partial validator is deliberately looser than the full one used by
`omd-cli assemble`: `assemble` still requires `metadata` and at least
one component to produce a canonical `plan.yaml`. Nothing about the
existing run pipeline changed; the builder just replaces the manual
YAML authoring step.

## Walkthrough

### 1. Scaffold the plan directory

```bash
omd-cli plan init hangar_studies/my-study \
    --id my-study --name "My study"
```

Creates `hangar_studies/my-study/metadata.yaml`. The directory is
created if it does not exist. `plan review` at this point reports
MISSING for every other section — that is expected.

### 2. Add a component

Flag-driven (supply a pre-written config YAML):

```bash
omd-cli plan add-component hangar_studies/my-study \
    --id wing --type oas/AerostructPoint \
    --config-file /path/to/wing-config.yaml \
    --rationale "Baseline rectangular wing for exploration"
```

Interactive (Click prompts field-by-field for
`oas/AerostructPoint`; other types fall back to `$EDITOR`):

```bash
omd-cli plan add-component hangar_studies/my-study -i
```

Writes `components/wing.yaml` as a bare mapping. Duplicate ids error
unless `--replace` is set.

### 3. Set operating point and solvers

```bash
omd-cli plan set-operating-point hangar_studies/my-study \
    --mach 0.84 --alpha 5.0 --velocity 248 --re 1e6 --rho 0.38 \
    --rationale "Cruise design point per study brief"

omd-cli plan set-solver hangar_studies/my-study \
    --nonlinear NewtonSolver --linear DirectSolver \
    --nonlinear-maxiter 20 --rationale "Standard aerostruct choice"
```

`set-operating-point` merges fields into `operating_points.yaml`
(existing keys preserved unless overwritten). `set-solver` writes both
legs unless only one is provided.

### 4. Add design variables and objective

```bash
omd-cli plan add-dv hangar_studies/my-study \
    --name twist_cp --lower -10 --upper 15 \
    --rationale "Conservative envelope, expect wash-out optimum"

omd-cli plan set-objective hangar_studies/my-study \
    --name structural_mass --scaler 1e-4 \
    --rationale "Primary study goal"
```

Short names are validated against the declared component's factory
`var_paths` (see `_FACTORY_DV_SHORT_NAMES` in
`packages/omd/src/hangar/omd/plan_mutate.py`). For OAS AerostructPoint
the allowed set is `twist_cp`, `thickness_cp`, `chord_cp`,
`spar_thickness_cp`, `skin_thickness_cp`, `t_over_c_cp`, `S_ref`,
`structural_mass`, `CL`, `CD`, `CDi`, `CDv`, `CDw`, `CM`, `failure`,
`tsaiwu_sr`, `L_equals_W`, `fuelburn`. Prefixed forms like
`wing.twist_cp` are accepted as long as the suffix matches. Under
`--interactive` the allowed names are printed before the prompt.

### 5. Hand-author a decision (optional)

```bash
omd-cli plan add-decision hangar_studies/my-study \
    --stage optimizer_selection \
    --decision "SLSQP with maxiter 200" \
    --rationale "Inequality constraints + continuous DVs"
```

Stages outside `RECOMMENDED_DECISION_STAGES` are accepted but emit a
warning to stderr (and `plan review` will WARN on them too).

### 6. Scaffold a phased strategy (optional)

```bash
omd-cli plan set-analysis-strategy hangar_studies/my-study \
    --phases 2 --rationale "Baseline verify then optimize"
```

Writes `analysis_plan.yaml` with `{p1, p2}` phases pre-populated to
pass the partial validator. `p2.depends_on` chains to `p1`. Success
criteria lists are empty — fill them in by hand. Phase execution
(`omd-cli run --phase`) is still deferred per
`deferred-enhancements.md` item 1; `analysis_plan` is rendered in the
provenance DAG today as documentation.

### 7. Review and assemble

```bash
omd-cli plan review hangar_studies/my-study
omd-cli assemble hangar_studies/my-study
```

`plan review` reports per-section OK / WARN / MISSING / ERROR
findings. ERROR findings must be fixed before assembly. `assemble`
validates against the full schema, auto-versions, and writes
`plan.yaml` plus `history/v{N}.yaml` and a copy to the plan store.

### 8. Run, plot, and review provenance

The rest of the pipeline is unchanged:

```bash
omd-cli run hangar_studies/my-study/plan.yaml --mode analysis
omd-cli results <run_id> --summary
omd-cli plot <run_id> --type all
omd-cli provenance <plan_id> --format text
```

## Rationale capture policy

Every mutation subcommand accepts an optional `--rationale TEXT`
flag. When provided, the library auto-appends a structured entry to
`decisions.yaml`:

```yaml
- id: dec-auto-3
  stage: dv_setup                   # inferred from the primitive
  decision: DV twist_cp bounds [-10, 15]
  rationale: Conservative envelope, expect wash-out optimum
  element_path: design_variables[twist_cp]
```

Stage inference:

| Subcommand | Inferred stage |
|------------|----------------|
| `add-component` | `component_selection` |
| `add-requirement` | `problem_definition` |
| `add-dv` | `dv_setup` |
| `set-objective` | `objective_selection` |
| `set-operating-point` | `operating_point_selection` |
| `set-solver` | `solver_selection` |
| `set-analysis-strategy` | `formulation` |

Ids use `dec-auto-{N}` where N is the next free integer across the
`decisions.yaml` list. `add-decision` bypasses the auto-capture hook —
the call itself is the decision and the user supplies the id and
stage directly.

**Under `--interactive`, rationale is required.** An empty rationale
exits 1 so the decision trail is never silently dropped. Non-interactive
runs treat `--rationale` as optional; omitting it simply means no
`decisions.yaml` entry is appended.

## When the builder is not the right tool

- **Copying an existing plan.** For minor variations on a fixture,
  it is still faster to copy the directory and hand-edit one or two
  fields than to re-run the builder.
- **Per-surface config beyond the curated interactive prompts.** The
  `oas/AerostructPoint` prompt list covers the minimum fields. For
  multi-surface wings, wingbox models, or custom material maps, pass
  a ready-made `--config-file` or edit `components/<id>.yaml`
  directly after `add-component`.
- **Multi-point operating conditions.** `set-operating-point` writes
  the single-point flat-dict form. Multi-point
  (`{flight_points: [...]}`) is not yet supported by the builder —
  hand-author `operating_points.yaml` or edit after scaffolding.
- **Programmatic batch creation.** Import from
  `hangar.omd.plan_mutate` directly:

  ```python
  from pathlib import Path
  from hangar.omd import plan_mutate as pm

  pm.init_plan(Path("my-plan"), plan_id="my", name="My plan")
  pm.add_component(
      Path("my-plan"),
      comp_id="wing",
      comp_type="oas/AerostructPoint",
      config=config_dict,
      rationale="Baseline",
  )
  # ...
  ```

  Primitives raise `hangar.sdk.errors.UserInputError` on bad input;
  catch and surface them in your scripting layer.

## Related references

- `packages/omd/docs/deferred-enhancements.md` — what the builder is
  *not* yet: MCP-tool wrappers, `--recommend-bounds` / `--recommend`
  heuristics, operating-point template library, completeness-aware
  auto-review inside prompts, phase execution gating.
- `packages/omd/src/hangar/omd/plan_mutate.py` — the library layer.
- `packages/omd/src/hangar/omd/plan_schema.py` — `PLAN_SCHEMA_PARTIAL`
  and `validate_partial` (used after every mutation); full `PLAN_SCHEMA`
  used by `assemble`.
- `packages/omd/src/hangar/omd/cli.py` — `@plan` command group.
- `.claude/skills/omd-cli-guide/` — CLI reference skill; the
  "Interactive Plan Builder" section in `SKILL.md` mirrors this doc
  in short form.
