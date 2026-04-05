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

## results

Query results for a completed run.

```bash
omd-cli results <run_id> [--summary] [--variables v1,v2,...] [--db PATH]
```

**Options:**
- `--summary` -- return only the final case with condensed output
- `--variables`, `-v` -- filter to specific variable names
- `--db` -- path to analysis DB

## export

Generate a standalone Python script from a plan.

```bash
omd-cli export <plan_path> --output <script.py>
```

The script uses only openmdao/openaerostruct imports (no hangar dependency).
Useful for sharing, archiving, or debugging.

## provenance

View the provenance chain for a plan. There are two viewing modes:

### Static HTML viewer (plan-lifecycle provenance)

Generates a standalone Cytoscape.js HTML file from the omd analysis DB.
Shows plan entities, execute/assess/replan activities, run records, assessment
entities, and PROV edges. The file opens in any browser with no server needed.

```bash
omd-cli provenance <plan_id> --format html -o <output.html>
```

Then open the file in a browser. On WSL:
```bash
explorer.exe "$(wslpath -w <output.html>)"
```

**When to offer this to the user:** After any `omd-cli run` or when the user
asks to see the provenance graph. Generate the file and tell the user the path
so they can open it. This is the primary way to visualize omd provenance.

### Text timeline

```bash
omd-cli provenance <plan_id> --format text
```

Human-readable timeline of entities and activities. Good for quick checks
in the terminal.

### Version diff

```bash
omd-cli provenance <plan_id> --diff V1 V2
```

Compare two plan versions: shows metadata diff and which keys changed.

**Full options:**
- `--format` -- `text` (timeline) or `html` (Cytoscape.js DAG)
- `--diff V1 V2` -- compare two plan versions
- `--output`, `-o` -- output file path (required for html format)
- `--db` -- path to analysis DB

**Example output (text):**
```
Provenance timeline for: plan-paraboloid-analysis
============================================================
  [2026-04-03T13:04:57] plan v1 (plan-paraboloid-analysis/v1) by have-agent
  [2026-04-03T13:04:57] EXECUTE (act-execute-run-...) by omd -- completed
  [2026-04-03T13:04:58] run_record (run-...) by omd
  [2026-04-03T13:04:58] ASSESS (act-assess-run-...) by omd -- completed
  [2026-04-03T13:04:58] assessment (assessment-run-...) by omd

Edges:
  run-... --wasGeneratedBy--> act-execute-run-...
  act-execute-run-... --used--> plan-paraboloid-analysis/v1
  act-assess-run-... --used--> run-...
  assessment-run-... --wasGeneratedBy--> act-assess-run-...
```

## viewer

Start the provenance viewer as a live HTTP server. Serves two views:

- `/omd-provenance` -- omd plan-lifecycle provenance (plans, runs, assessments)
  from the analysis DB. Lists all plans; click one to see its Cytoscape.js DAG.
- `/viewer` -- SDK tool-call-level provenance from MCP server sessions
  (populated when running via `uv run python -m hangar.omd.server`).

```bash
omd-cli viewer [--port PORT] [--db PATH]
```

**Options:**
- `--port` -- port to serve on (default: 7654)
- `--db` -- path to SDK provenance database

**Usage:**
1. Run `omd-cli viewer` in one terminal
2. Open `http://localhost:7654/omd-provenance` in a browser to see plan DAGs
3. Click a plan ID to view its full Cytoscape.js provenance graph
4. Press Ctrl+C in the terminal to stop the server

**When to offer this to the user:** After any `omd-cli run`, tell the user
they can start the viewer to browse all plan provenance interactively. For a
quick one-off, the static HTML export (see `provenance` command above) works
without needing a running server.

### Summary: how to view provenance

| Situation | Command | What it shows |
|-----------|---------|---------------|
| Browse all plans interactively | `omd-cli viewer`, open `/omd-provenance` | Plan/run/assessment DAGs (live server) |
| One-off static file | `omd-cli provenance <plan_id> --format html -o dag.html` | Single plan DAG (static HTML) |
| Quick terminal check | `omd-cli provenance <plan_id> --format text` | Text timeline |
| MCP session tool calls | `omd-cli viewer`, open `/viewer` | Tool call sequence + decisions |
