# Commands & Parameters Reference

Run `ocp-cli <subcommand> --help` for the complete, auto-generated parameter
list for any tool. This file documents key parameters and gotchas.

## Common parameters

Most analysis tools accept these shared parameters:

| Parameter | CLI flag | Default | Notes |
|-----------|----------|---------|-------|
| `session_id` | `--session-id` | `"default"` | Groups related analyses |
| `run_name` | `--run-name` | `None` | Optional label for `list-runs` |

---

## Configuration tools

### list-aircraft-templates

List all built-in aircraft templates. No arguments.

```bash
ocp-cli --pretty list-aircraft-templates
```

### load-aircraft-template

Load a built-in aircraft data template.

| Parameter | CLI flag | Default | Notes |
|-----------|----------|---------|-------|
| `template` | `--template` | (required) | `caravan`, `b738`, `kingair`, `tbm850` |
| `overrides` | `--overrides` | `None` | JSON dict of nested overrides |

`--overrides` only replaces fields that already exist in the template,
addressed by their full nested path. Any key it introduces is inert (the model
never reads it), and the response lists it under `warnings`. Mission calibration
(`structural_fudge`, `takeoff_throttle`) is NOT an override -- pass it to
`configure-mission`.

```bash
ocp-cli load-aircraft-template --template caravan
ocp-cli load-aircraft-template --template kingair \
    --overrides '{"ac": {"weights": {"MTOW": {"value": 5000, "units": "kg"}}}}'
```

### define-aircraft

Define a custom aircraft from individual parameters.

**Key parameters:**
- `--S-ref` (m^2), `--AR`, `--MTOW` (kg), `--W-fuel-max` (kg)
- `--engine-rating` (hp), `--engine-rating-units` (`hp` or `lbf`)
- `--propeller-diameter` (m), `--motor-rating` (hp), `--generator-rating` (hp)
- `--W-battery` (kg), `--e`, `--CD0-cruise`, `--CD0-TO`
- `--fuselage-S-wet` (m^2), `--fuselage-width` (m), `--fuselage-length` (m)

### set-propulsion-architecture

Select and configure the propulsion system.

| Parameter | CLI flag | Default | Notes |
|-----------|----------|---------|-------|
| `architecture` | `--architecture` | (required) | See table below |
| `motor_rating` | `--motor-rating` | `None` | hp, required for hybrid/electric |
| `generator_rating` | `--generator-rating` | `None` | hp, required for hybrid |
| `battery_weight` | `--battery-weight` | `None` | kg, required for hybrid/electric |
| `battery_specific_energy` | `--battery-specific-energy` | `None` | Wh/kg (default 300) |

**Architectures:**

| Name | Engines | Fuel | Battery | Notes |
|------|---------|------|---------|-------|
| `turboprop` | 1 | Yes | No | Single turboprop |
| `twin_turboprop` | 2 | Yes | No | Twin turboprop |
| `series_hybrid` | 1 | Yes | Yes | Single engine + motor + generator |
| `twin_series_hybrid` | 2 | Yes | Yes | Twin engine + motors + generators |
| `twin_turbofan` | 2 | Yes | No | B738-style CFM56 |

### configure-mission

Set mission profile parameters.

| Parameter | CLI flag | Default | Notes |
|-----------|----------|---------|-------|
| `mission_type` | `--mission-type` | `"full"` | `full`, `basic`, `with_reserve` |
| `cruise_altitude` | `--cruise-altitude` | 18000 | ft |
| `mission_range` | `--mission-range` | 250 | NM |
| `climb_vs` | `--climb-vs` | 850 | ft/min |
| `climb_Ueas` | `--climb-Ueas` | 104 | kn |
| `cruise_Ueas` | `--cruise-Ueas` | 129 | kn |
| `descent_vs` | `--descent-vs` | 400 | ft/min (positive; auto-negated) |
| `descent_Ueas` | `--descent-Ueas` | 100 | kn |
| `num_nodes` | `--num-nodes` | 11 | **Must be ODD** |
| `payload` | `--payload` | `None` | lb (hybrid/reserve) |
| `cruise_hybridization` | `--cruise-hybridization` | `None` | 0-1 (hybrid only) |
| `climb_hybridization` | `--climb-hybridization` | `None` | 0-1 (hybrid only) |
| `descent_hybridization` | `--descent-hybridization` | `None` | 0-1 (hybrid only) |

**Mission types:**

| Type | Phases | Description |
|------|--------|-------------|
| `full` | v0v1, v1vr, v1v0, rotate, climb, cruise, descent | Balanced-field takeoff + mission |
| `basic` | climb, cruise, descent | Three-phase only |
| `with_reserve` | climb, cruise, descent + reserve + loiter | Includes fuel reserves |

---

## Analysis tools

### run-mission-analysis

Run the configured mission. Returns fuel burn, OEW, TOFL, battery SOC, etc.

```bash
ocp-cli --pretty run-mission-analysis
ocp-cli --pretty run-mission-analysis --run-name "baseline"
```

### run-parameter-sweep

Sweep one parameter across multiple values.

| Parameter | CLI flag | Notes |
|-----------|----------|-------|
| `parameter` | `--parameter` | See table below |
| `values` | `--values` | JSON array, e.g. `'[200, 300, 400, 500]'` |

**Sweep parameters:** `mission_range`, `cruise_altitude`, `battery_weight`,
`battery_specific_energy`, `hybridization`, `engine_rating`, `motor_rating`

```bash
ocp-cli --pretty run-parameter-sweep \
    --parameter mission_range --values '[200, 300, 400, 500]'
```

### run-optimization

Run design optimization with ScipyOptimizeDriver (SLSQP).

| Parameter | CLI flag | Notes |
|-----------|----------|-------|
| `objective` | `--objective` | `fuel_burn`, `mixed_objective`, `MTOW` |
| `design_variables` | `--design-variables` | JSON array of DV dicts |
| `constraints` | `--constraints` | JSON array of constraint dicts |
| `max_iterations` | `--max-iterations` | Default 200 |

DV dict format: `{"name": "path", "lower": val, "upper": val}`
Constraint dict format: `{"name": "path", "lower": val}` or `{"upper": val}` or `{"equals": val}`

```bash
ocp-cli --pretty run-optimization --objective fuel_burn \
    --design-variables '[{"name": "cruise.hybridization", "lower": 0.01, "upper": 0.5}]' \
    --constraints '[{"name": "descent.propmodel.batt1.SOC_final", "lower": 0.0}]'
```

---

## Visualization tools

### visualize

Generate a plot for an OpenConcept analysis run.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_id` | str | **required** | Run ID (or `"latest"`) |
| `plot_type` | str | **required** | See plot types below |
| `case_name` | str | `""` | Label for the plot title |
| `output` | str | `None` | `"inline"`, `"file"`, or `"url"` |

**Plot types:**

| Type | Applicable to | Description |
|------|--------------|-------------|
| `mission_profile` | mission, optimization | 2x3 grid: altitude, V/S, TAS, throttle, fuel, battery SOC vs range |
| `takeoff_profile` | mission (full only) | 1x3 grid: altitude, airspeed, throttle for takeoff phases |
| `weight_breakdown` | mission, optimization | Horizontal bar chart of MTOW components (OEW, fuel, payload) |
| `performance_summary` | all | Table card with all key metrics |
| `energy_budget` | mission (hybrid only) | Dual Y-axis: battery SOC + fuel used vs range |
| `sweep_chart` | sweep | 2x2 grid: metrics vs swept parameter |
| `optimization_history` | optimization | Objective summary + optimized DV values |

**Important**: `visualize` returns a **list**, not a dict. First element is
metadata; second (if present in inline mode) is the image.

```bash
ocp-cli plot latest mission_profile -o mission.png
ocp-cli plot latest weight_breakdown
ocp-cli --pretty visualize --run-id latest --plot-type performance_summary --output file
```

---

## Observability & artifact tools

| Tool | Key parameters | Purpose |
|------|---------------|---------|
| `get-run` | `--run-id` | Full manifest: inputs, outputs, validation |
| `get-detailed-results` | `--run-id`, `--detail-level` | Full results (`standard`) or scalars only (`summary`) |
| `pin-run` / `unpin-run` | `--run-id` | Prevent/release artifact eviction |
| `get-last-logs` | `--run-id` | Server-side log records |
| `list-artifacts` | `--session-id`, `--analysis-type`, `--project` | Browse saved runs |
| `get-artifact` / `get-artifact-summary` | `--run-id` | Full or metadata-only retrieval |
| `delete-artifact` | `--run-id` | Remove a saved artifact |
| `configure-session` | `--auto-visualize`, `--visualization-output` | Per-session defaults |
| `set-requirements` | `--requirements` | Auto-checked constraints |
| `reset` | `--session-id` | Clear all state |

---

## Provenance tools

| Tool | Key parameters | Purpose |
|------|---------------|---------|
| `start-session` | `--notes`, `--session-id` | Begin named provenance session |
| `log-decision` | `--decision-type`, `--reasoning`, `--selected-action`, `--prior-call-id` | Record reasoning step |
| `link-cross-tool-result` | `--source-call-id`, `--source-tool`, `--target-tool` | Cross-tool data handoff |
| `export-session-graph` | `--session-id` | Export provenance DAG as JSON |

---

## Convenience commands

| Command | Usage | Description |
|---------|-------|-------------|
| `list-tools` | `ocp-cli list-tools` | Print available tool names |
| `list-runs` | `ocp-cli list-runs --limit 10` | Browse recent runs |
| `show` | `ocp-cli show latest` | Show summary of a run |
| `plot` | `ocp-cli plot latest mission_profile` | Save plot to disk (shorthand for visualize with output=file) |
| `viewer` | `ocp-cli viewer --port 7654` | Start provenance/dashboard viewer |
