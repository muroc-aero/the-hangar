# Commands Reference

All tool parameters, grouped by function. Run `evt-cli <subcommand> --help`
for the authoritative parameter list. The full config-key schema also lives in
the `evt://reference` resource.

## Common parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `session_id` | `"default"` | Session for state and provenance grouping |
| `run_name` | `None` | Optional human-readable label for a run |

## Vehicle / config tools

The config has five sections -- `aircraft`, `mission`, `power`, `propulsion`,
`environ`. A config must be complete before analysis; `load_vehicle_template`
seeds all five, the setters override individual keys. Unknown keys are rejected
(evtolpy silently ignores them otherwise).

### list-vehicle-templates

No parameters. Returns the built-in templates and their descriptions.

### load-vehicle-template

Seed the session config from a complete, upstream-validated baseline. **Call
this first.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `template` | str | `"test_all"` | Template name (`test_all` is the only shipped template) |

Returns: `{template, description, sections, status}`

### define-vehicle / set-propulsion / set-power / set-environment / configure-mission

Each merges `{key: value}` overrides into one config section and validates the
keys. All take a single `params` JSON object:

| Tool | Section | Example keys |
|------|---------|--------------|
| `define-vehicle` | aircraft | `wingspan_m`, `payload_kg`, `vehicle_cl_max`, `max_takeoff_mass_kg`, fixed component masses |
| `set-propulsion` | propulsion | `rotor_count`, `lift_rotor_count`, `tilt_rotor_count`, `rotor_diameter_m`, `tip_mach`, `rotor_effic` |
| `set-power` | power | `batt_spec_energy_w_h_p_kg`, `batt_eol_capacity`, `epu_effic`, `hover_power_effic` |
| `set-environment` | environ | `air_density_sea_lvl_kg_p_m3`, `g_m_p_s2`, `sound_speed_m_p_s` |
| `configure-mission` | mission | per-segment speeds (`*_h_m_p_s`, `*_v_m_p_s`, `*_avg_*`) and durations (`*_s`), e.g. `cruise_s`, `cruise_h_m_p_s` |

```bash
evt-cli set-power --params '{"batt_spec_energy_w_h_p_kg": 280.0, "epu_effic": 0.92}'
evt-cli configure-mission --params '{"cruise_s": 720.0}'
```

Validation rejects: unknown keys (with a typo suggestion), non-numeric values,
rotor counts that are not non-negative integers, fractions/efficiencies outside
`(0, 1]`, battery specific energy outside `[50, 1000]` Wh/kg, and negative
magnitudes.

## Analysis tools

### run-mission-analysis

Evaluate the configured vehicle over its mission at the **as-configured MTOW**
(no sizing). Reproduces upstream's mission-segment energy/power and mass-breakdown
lanes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_name` | str | `None` | Optional label |
| `session_id` | str | `"default"` | Session |

Returns a versioned envelope. `results` contains:
- `energy_kw_hr` -- per-segment energy across 18 segments (incl. reserves)
- `avg_electric_power_kw` -- per-segment average electric power
- `mass_breakdown_kg` -- 15-component empty-mass breakdown
- `totals` -- `total_mission_energy_kw_hr`, `total_reserve_mission_energy_kw_hr`, `empty_mass_kg`, `battery_mass_kg`, `payload_kg`, `payload_mass_frac`
- `geometry`, `aero`, `propulsion` -- summary blocks
- `max_takeoff_mass_kg` -- the as-configured MTOW

### run-sizing

Converge the maximum takeoff weight via evtolpy's MTOW fixed-point iteration.
Reproduces upstream's `log_mtow_iteration`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_name` | str | `None` | Optional label |
| `session_id` | str | `"default"` | Session |

Returns a versioned envelope. `results` contains:
- `initial_mtow_kg`, `sized_mtow_kg`, `converged` (bool), `iterations`
- `history` -- per-iteration rows (`mtow_guess_kg`, `new_mtow_kg`, `delta_kg`, masses, `total_energy_converged_kw_hr`)
- `mass_breakdown_kg`, `totals` -- at the converged MTOW

A diverging iteration fails (evtolpy's safeguard). A returned-but-not-converged
result is flagged as an error finding in `validation` -- check it.

### run-parameter-sweep

Sweep one config parameter over a list of values and collect a metric. Points
that raise (e.g. a diverging MTOW) are recorded with a null metric and an
`error` note rather than aborting the sweep.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param` | str | **required** | `section.key`, e.g. `power.batt_spec_energy_w_h_p_kg` |
| `values` | list[float] | **required** | Explicit values to evaluate |
| `metric` | str | `total_mission_energy_kw_hr` | Output metric (see below) |

Metrics: `total_mission_energy_kw_hr`, `total_reserve_mission_energy_kw_hr`,
`battery_mass_kg`, `empty_mass_kg`, `cruise_l_p_d`, `cruise_avg_electric_power_kw`,
`disk_loading_kg_p_m2`, `sized_mtow_kg` (this last one converges MTOW per point --
slower). Returns `{param, metric, points:[{value, metric}], summary}`.

```bash
evt-cli run-parameter-sweep --param power.batt_spec_energy_w_h_p_kg \
        --values '[200, 260, 320]' --metric sized_mtow_kg
```

### reset

Clear the session config and cached state.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | str | `"default"` | Session to reset |

## Visualization tools

### visualize

Generate a plot for an analysis run.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_id` | str | **required** | Run ID (or `"latest"`) |
| `plot_type` | str | **required** | See plot types below |
| `case_name` | str | `""` | Label for the plot title |
| `output` | str | `None` | `"inline"`, `"file"`, or `"url"` |

**Plot types:**

| Type | Applicable to | Description |
|------|--------------|-------------|
| `segment_energy` | mission | Per-segment energy bar chart (reserves shaded) |
| `segment_power` | mission | Per-segment average electric power bar chart |
| `mass_breakdown` | mission, sizing | Component empty-mass horizontal bars |
| `mtow_convergence` | sizing | MTOW guess vs iteration |
| `sweep` | sweep | Metric vs swept parameter |

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

`path` uses dot notation into `results` (e.g. `totals.total_mission_energy_kw_hr`,
`sized_mtow_kg`). `operator`: `"<"`, `"<="`, `">"`, `">="`, `"=="`, `"!="`. The
threshold key is `value` (not `target`); a requirement written with `target` is
silently compared against `None` and never passes.

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
| `list-tools` | `evt-cli list-tools` | Print available tool names |
| `list-runs` | `evt-cli list-runs --limit 10` | Browse recent runs |
| `show` | `evt-cli show latest` | Show summary of a run |
| `plot` | `evt-cli plot latest segment_energy` | Save plot to disk (shorthand for visualize with output=file) |
| `viewer` | `evt-cli viewer --port 7654` | Start provenance/dashboard viewer |
