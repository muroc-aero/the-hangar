# Commands Reference

All tool parameters, grouped by function. Run `pyc-cli <subcommand> --help`
for the authoritative parameter list.

## Common parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `session_id` | `"default"` | Session for state and provenance grouping |
| `run_name` | `None` | Optional human-readable label for a run |

## Analysis tools

### create-engine

Define an engine from a predefined archetype. The engine is stored in session
memory and referenced by name in subsequent analysis calls.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `archetype` | str | **required** | Engine architecture: `turbojet` |
| `name` | str | `"engine"` | Engine name (must match in later calls) |
| `comp_PR` | float | archetype default | Compressor pressure ratio |
| `comp_eff` | float | archetype default | Compressor isentropic efficiency |
| `turb_eff` | float | archetype default | Turbine isentropic efficiency |
| `Nmech` | float | archetype default | Shaft speed (rpm) |
| `burner_dPqP` | float | archetype default | Combustor fractional pressure loss |
| `nozz_Cv` | float | archetype default | Nozzle velocity coefficient |
| `thermo_method` | str | `"TABULAR"` | `"TABULAR"` (fast) or `"CEA"` (accurate, ~10x slower) |
| `overrides` | dict | `None` | Advanced: arbitrary cycle parameter overrides `{path: value}` |

Returns: `{engine_name, archetype, description, elements, params, valid_design_vars}`

### run-design-point

Size the engine at design conditions. **Must be called before run-off-design.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `engine_name` | str | `"engine"` | Engine from create_engine |
| `alt` | float | `0.0` | Design altitude (ft) |
| `MN` | float | `0.000001` | Design Mach number (near-zero, NOT exactly 0) |
| `Fn_target` | float | `11800.0` | Design net thrust target (lbf) |
| `T4_target` | float | `2370.0` | Turbine inlet temperature target (degR); limit ~3600 |

Returns: versioned envelope with `{results, validation, telemetry, run_id}`

**results** contains:
- `performance`: Fn, Fg, TSFC, OPR, Wfuel, ram_drag, mass_flow
- `flow_stations`: per-station tot:P, tot:T, tot:h, tot:S, stat:P, stat:W, stat:MN, stat:V, stat:area
- `components`: comp (PR, eff, Wc, Nc, pwr, trq), turb (PR, eff, Wp, Np, pwr, trq), burner (FAR, Wfuel, dPqP), shaft (Nmech, pwr_net), nozz (Fg, PR, Cv, throat_area)

### run-off-design

Evaluate the engine at off-design conditions. **Requires run-design-point first.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `engine_name` | str | `"engine"` | Engine (must have design point) |
| `alt` | float | `0.0` | Off-design altitude (ft) |
| `MN` | float | `0.000001` | Off-design Mach number |
| `Fn_target` | float | `11000.0` | Off-design thrust target (lbf) |

Returns: same envelope as design point, plus `results.design_point` with the
design-point performance for comparison.

### reset

Clear all engines and cached state for the session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | str | `"default"` | Session to reset |

## Visualization tools

### visualize

Generate a plot for a pyCycle analysis run.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_id` | str | **required** | Run ID (or `"latest"`) |
| `plot_type` | str | **required** | See plot types below |
| `case_name` | str | `""` | Label for the plot title |
| `output` | str | `None` | `"inline"`, `"file"`, or `"url"` |

**Plot types:**

| Type | Applicable to | Description |
|------|--------------|-------------|
| `station_properties` | design, off-design | 2x2 grid: Pt, Tt, Mach, mass flow vs station |
| `ts_diagram` | design, off-design | T-s diagram of the Brayton cycle |
| `performance_summary` | design, off-design | Table card with all key engine metrics |
| `component_bars` | design, off-design | Bar chart: PR, efficiency, power per component |
| `design_vs_offdesign` | off-design only | 2x2 paired bars comparing design vs off-design |

**Important**: `visualize` returns a **list**, not a dict. First element is
metadata; second (if present in inline mode) is the image.

## Session configuration tools

### configure-session

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | str | `"default"` | Session to configure |
| `project` | str | `None` | Project name for artifact grouping |
| `detail_level` | str | `None` | `"standard"` or `"full"` |

### set-requirements

Set requirements checked against every analysis result.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `requirements` | list[dict] | **required** | `[{label, path, operator, value}]` |

`path` uses dot notation into results (e.g. `"performance.TSFC"`).
`operator`: `"<"`, `"<="`, `">"`, `">="`, `"=="`, `"!="`.
The threshold key is `value` (not `target`); a requirement written with
`target` is silently compared against `None` and never passes.

## Artifact management tools

| Tool | Key parameters | Purpose |
|------|---------------|---------|
| `list-artifacts` | `--session-id`, `--analysis-type`, `--project` | Browse saved runs |
| `get-artifact` | `--run-id` | Full metadata + results |
| `get-artifact-summary` | `--run-id` | Metadata only (lightweight) |
| `delete-artifact` | `--run-id` | Remove a saved artifact |

## Observability tools

| Tool | Key parameters | Purpose |
|------|---------------|---------|
| `get-run` | `--run-id` | Full manifest: inputs, outputs, validation |
| `get-detailed-results` | `--run-id`, `--detail-level` | Full results (`standard`) or scalars only (`summary`) |
| `pin-run` | `--run-id` | Prevent cache/artifact eviction |
| `unpin-run` | `--run-id` | Release a pinned run |
| `get-last-logs` | `--run-id` | Server-side log records for a run |

## Provenance tools

| Tool | Key parameters | Purpose |
|------|---------------|---------|
| `start-session` | `--notes`, `--session-id` | Begin named provenance session |
| `log-decision` | `--decision-type`, `--reasoning`, `--selected-action`, `--prior-call-id` | Record reasoning step |
| `link-cross-tool-result` | `--source-call-id`, `--source-tool`, `--target-tool` | Cross-tool data handoff |
| `export-session-graph` | `--session-id` | Export provenance DAG as JSON |

## Convenience commands

| Command | Usage | Description |
|---------|-------|-------------|
| `list-tools` | `pyc-cli list-tools` | Print available tool names |
| `list-runs` | `pyc-cli list-runs --limit 10` | Browse recent runs |
| `show` | `pyc-cli show latest` | Show summary of a run |
| `plot` | `pyc-cli plot latest station_properties` | Save plot to disk (shorthand for visualize with output=file) |
| `viewer` | `pyc-cli viewer --port 7654` | Start provenance/dashboard viewer |
