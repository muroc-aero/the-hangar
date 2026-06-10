# omd-cli Command Reference

## assemble

Merge modular YAML files from a plan directory into a canonical `plan.yaml`.

```bash
omd-cli assemble <plan_dir> [--output PATH]
```

**Arguments:**
- `plan_dir` -- path to directory containing modular YAML files

**Options:**
- `--output`, `-o` -- output path for assembled plan (default: `<plan_dir>/plan.yaml`)

**Behavior:**
- Reads metadata.yaml, requirements.yaml, operating_points.yaml, solvers.yaml, optimization.yaml, decisions.yaml
- Collects all `*.yaml` files from `components/` subdirectory
- Validates against the plan JSON Schema
- Computes SHA256 content hash
- Auto-increments version number from `history/` directory
- Writes `plan.yaml` + `history/vN.yaml` + copy to `hangar_data/omd/plans/{plan-id}/vN.yaml`

## validate

Check an assembled plan against the JSON Schema.

```bash
omd-cli validate <plan_path>
```

Returns structured error messages with field paths if invalid.

## run

Materialize an OpenMDAO problem from a plan and execute it.

```bash
omd-cli run <plan_path> --mode analysis|optimize [--recording-level LEVEL] [--db PATH]
```

**Options:**
- `--mode` -- `analysis` (run_model) or `optimize` (run_driver). Default: analysis.
- `--recording-level` -- `minimal`, `driver`, `solver`, or `full`. Default: driver.
- `--db` -- path to analysis DB. Default: `hangar_data/omd/analysis.db`.

**Output:**
```
Run complete: run-20260403T130457-6f5287cc
  Status: completed
  CL: 0.452177
  CD: 0.035087
  L/D: 12.89
  Recording: 1 cases, 76.0 KB
```

**Recording levels:**
- `minimal` -- final values only (smallest storage)
- `driver` -- DVs + objective + constraints per optimizer iteration (default)
- `solver` -- above + nonlinear solver iterations
- `full` -- everything including residuals (largest)

## polar

Compute a drag polar by sweeping angle of attack on an OAS plan.

```bash
omd-cli polar <plan_path> [--alpha-start A] [--alpha-end B] [--num N] [--output PATH]
```

**Options:**
- `--alpha-start` / `--alpha-end` -- sweep bounds in degrees
- `--num` -- number of alpha points to evaluate
- `--output`, `-o` -- write the sweep result to a JSON file

Returns `alpha_deg` / `CL` / `CD` / `L_over_D` arrays plus `best_L_over_D`.
Only meaningful for plans whose component exposes CL/CD (`oas/*`).

## results

Query results for a completed run.

```bash
omd-cli results <run_id> [--summary] [--variables v1,v2,...] [--db PATH]
```

**Options:**
- `--summary` -- return only the final case with condensed output
- `--variables`, `-v` -- filter to specific variable names
- `--db` -- path to analysis DB

## summary

Produce a one-page HTML summary of a completed run (key metrics, DV table,
plot gallery, links to N2 and provenance).

```bash
omd-cli summary <run_id> [--output PATH] [--no-plots]
```

**Options:**
- `--output`, `-o` -- output HTML path (default: `plots/{run_id}/summary.html`)
- `--no-plots` -- skip on-demand plot generation; only embed existing PNGs

`run` already renders the summary eagerly at the end of each run; use this
command to regenerate it (e.g. after `plot` produced new figures).

## plot

Generate analysis plots from a completed run.

```bash
omd-cli plot <run_id> [--type TYPE|all] [--output DIR] [--surface NAME] [--list-types]
omd-cli plot --recorder-db <path.sql> --type all
```

**Options:**
- `--type` -- one plot type, or `all` for everything that applies
- `--list-types` -- list the plot types available for this run, then exit
- `--output`, `-o` -- output directory for PNGs (default: `plots/{run_id}/`)
- `--surface` -- surface name filter (multi-surface OAS plans)
- `--recorder-db` -- direct path to a recorder `.sql` file instead of a run_id

Generic types (`convergence`, `dv_evolution`, `n2`) work for every run;
factory-specific types (planform, lift, twist, struct, station_properties,
...) depend on the component family. Always check `--list-types` first.

## conclude

Record a conclusion artifact for a completed run. This is the closing
step of a study: it states what the chosen result means for the
requirements. Run it once you have settled on a final/best run.

```bash
omd-cli conclude <run_id> --narrative "what these results mean" [--plan PATH] [--db PATH]
```

**Options:**
- `--narrative`, `-n` -- a short sentence on what the results mean
- `--plan` -- plan YAML to evaluate against (defaults to the run's plan from the store)
- `--db` -- path to analysis DB

The per-requirement verdict is derived automatically: each requirement's
acceptance criteria are evaluated against the run's final results, so the
verdicts cannot drift from the numbers. The command writes a `conclusion`
entity tied to the run (with `satisfies` / `violates` edges to the
requirements) and prints what it derived, e.g.:

```
Conclusion conclusion-run-...: MEETS
  optimum reached
  [PASS] R1: reach a low objective
         paraboloid.f_xy <= -25.0 (actual -27.33)
```

Recording a conclusion is what moves a study into the Concluding state on
the dashboard (its Concluding coverage becomes populated). A study is not
"done" until its conclusion is recorded.

## export

Generate a standalone Python script from a plan.

```bash
omd-cli export <plan_path> --output <script.py>
```

The script uses only openmdao/openaerostruct imports (no hangar dependency).
Useful for sharing, archiving, or debugging.

## provenance

View the provenance chain for a plan.

```bash
omd-cli provenance <plan_id> [--format text|html|json] [--diff V1 V2] [--output PATH] [--db PATH]
```

**Options:**
- `--format` -- `text` (timeline), `html` (Cytoscape.js DAG), or `json` (raw data)
- `--diff V1 V2` -- compare two plan versions
- `--output`, `-o` -- output file path (required for html format)

**WSL tip:** The interactive viewer (`omd-cli viewer`) may not bridge to
Windows. Use `--format html` to export a static DAG and open it with:
```bash
explorer.exe "$(wslpath -w dag.html)"
```

**Example output (text):**
```
Provenance timeline for: plan-paraboloid-analysis
============================================================
  [2026-04-03T13:04:57] plan v1 (plan-paraboloid-analysis/v1) by have-agent
  [2026-04-03T13:04:57] EXECUTE (act-execute-run-...) by omd -- completed
  [2026-04-03T13:04:58] run_record (run-...) by omd

Edges:
  run-... --wasGeneratedBy--> act-execute-run-...
  act-execute-run-... --used--> plan-paraboloid-analysis/v1
```

## plan

Plan authoring subcommands. Each mutation subcommand mutates one
modular file in the plan directory, validates the result against the
partial plan schema (`validate_partial`), and (when `--rationale` is
provided) appends a structured entry to `decisions.yaml`.

Under `--interactive`, every subcommand prompts for missing fields
via Click and **requires** a non-empty rationale — empty rationale
exits 1. Non-interactive calls treat `--rationale` as optional.

### plan init

Scaffold a plan directory with `metadata.yaml`. Creates the directory
if it does not exist.

```bash
omd-cli plan init <plan_dir> --id <plan_id> --name <name> \
    [--description TEXT] [--interactive]
```

### plan add-component

Write `components/<comp_id>.yaml` as a bare mapping.

```bash
omd-cli plan add-component <plan_dir> \
    --id <comp_id> --type <comp_type> \
    --config-file <yaml-file> \
    [--rationale TEXT] [--replace] [--interactive]
```

Non-interactive mode requires `--config-file`. Interactive mode
prompts for a curated field list when `--type` is
`oas/AerostructPoint`; other types fall back to `$EDITOR` for paste-in
YAML.

### plan add-requirement

Append a requirement to `requirements.yaml`.

```bash
omd-cli plan add-requirement <plan_dir> \
    --id <req_id> --text <text> \
    [--type performance|structural|stability|constraint|objective] \
    [--priority primary|secondary|goal] \
    [--rationale TEXT] [--replace] [--interactive]
```

Duplicate ids error unless `--replace` is set.

### plan add-dv

Add a design variable to `optimization.yaml`.

```bash
omd-cli plan add-dv <plan_dir> \
    --name <dv_name> --lower <float> --upper <float> \
    [--scaler <float>] [--units TEXT] \
    [--rationale TEXT] [--replace] [--interactive]
```

The DV name is validated against the short-name set of declared
components (e.g. `twist_cp`, `thickness_cp`, `chord_cp` for OAS
AerostructPoint). Prefixed forms like `wing.twist_cp` are accepted as
long as the suffix matches. `--interactive` echoes the allowed short
names before prompting for `--name`.

### plan add-shared-var

Append an entry to `shared_vars.yaml` so two or more components share
one DV driven by a root `shared_ivc` IndepVarComp.

```bash
omd-cli plan add-shared-var <plan_dir> \
    --name <var_name> --consumers <id1,id2,...> \
    [--value <scalar | comma-list>] [--units TEXT] \
    [--rationale TEXT] [--replace] [--interactive]
```

Consumers must match declared component ids. Scalar values pass
through as a float; comma-separated values become a list (e.g.
`--value 0.005,0.01,0.015`). See `plan-authoring.md` for the
composition model and when to use `shared_vars` vs `connections:`.

### plan set-composition-policy

Toggle the Fix 3 auto-share flag (and optionally populate a
`no_auto_share` list) from the CLI.

```bash
omd-cli plan set-composition-policy <plan_dir> \
    --policy explicit|auto \
    [--no-auto-share "name1,name2"] \
    [--rationale TEXT]
```

Writes `composition_policy.yaml` (and `no_auto_share.yaml` if names
are supplied) which the assembler splices into the final plan.

### plan set-objective

Set the optimization objective in `optimization.yaml`.

```bash
omd-cli plan set-objective <plan_dir> \
    --name <objective_name> \
    [--scaler <float>] [--units TEXT] \
    [--rationale TEXT] [--interactive]
```

Replaces any existing objective. Same short-name validation as
`add-dv`.

### plan add-decision

Append a hand-authored decision entry to `decisions.yaml`.

```bash
omd-cli plan add-decision <plan_dir> \
    --stage <stage> --decision <text> \
    [--rationale TEXT] [--element-path TEXT] [--id TEXT] \
    [--interactive]
```

Off-list stages (outside `RECOMMENDED_DECISION_STAGES` in
`plan_schema.py`) are accepted but emit a warning to stderr.

### plan set-operating-point

Merge flight-condition fields into `operating_points.yaml`.

```bash
omd-cli plan set-operating-point <plan_dir> \
    [--mach FLOAT] [--alpha FLOAT] [--velocity FLOAT] \
    [--altitude FLOAT] [--re FLOAT] [--rho FLOAT] \
    [--units SI|imperial] \
    [--rationale TEXT] [--interactive]
```

Only sets the fields that are provided; existing keys are preserved
unless overwritten. `--units` applies to `--altitude` only: `SI` → m,
`imperial` → ft. At least one field must be provided in
non-interactive mode.

### plan set-solver

Write `solvers.yaml` (nonlinear + linear).

```bash
omd-cli plan set-solver <plan_dir> \
    [--nonlinear TYPE] [--linear TYPE] \
    [--nonlinear-maxiter INT] [--nonlinear-atol FLOAT] \
    [--rationale TEXT] [--interactive]
```

At least one of `--nonlinear`, `--linear` is required. Unspecified
legs are left unchanged.

### plan set-analysis-strategy

Scaffold `analysis_plan.yaml` with N empty phases. Each phase gets
`{id, name: TODO, mode: analysis, depends_on, success_criteria: []}`
so the partial validator passes immediately. Phase ids are
`{prefix}{n}` with `depends_on` chaining each phase to its
predecessor.

```bash
omd-cli plan set-analysis-strategy <plan_dir> \
    --phases <N> [--phase-id-prefix TEXT] \
    [--rationale TEXT] [--interactive]
```

### plan review

Review a plan directory (or assembled plan.yaml) for completeness.

```bash
omd-cli plan review <plan_path> [--format text|json]
```

Emits per-section findings (OK / WARN / MISSING / ERROR). Always exits
0 (advisory). Use `--format json` for CI gating.
