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

## Observability & artifact tools

See the OAS CLI guide for shared patterns — OCP uses the same SDK tools with
the same interface:

- `get-run`, `pin-run`, `unpin-run`, `get-detailed-results`, `get-last-logs`
- `list-artifacts`, `get-artifact`, `get-artifact-summary`, `delete-artifact`
- `configure-session`, `set-requirements`, `reset`
