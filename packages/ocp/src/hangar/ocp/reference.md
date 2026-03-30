# OpenConcept MCP Server -- Parameter Reference

## Aircraft Templates

| Template | Type | MTOW (kg) | Propulsion | Wing Area (m^2) |
|----------|------|-----------|------------|-----------------|
| caravan | GA turboprop | 3,970 | 1x PT6A (675 hp) | 26.0 |
| b738 | Jet transport | 79,002 | 2x CFM56 (27,000 lbf) | 124.6 |
| kingair | Twin turboprop | 4,581 | 2x PT6A (750 hp) | 27.3 |
| tbm850 | Fast turboprop | 3,353 | 1x PT6A (850 hp) | 18.0 |

## Propulsion Architectures

| Architecture | Engines | Fuel | Battery | Weight Model |
|-------------|---------|------|---------|--------------|
| turboprop | 1 | Yes | No | SingleTurboPropEmptyWeight |
| twin_turboprop | 2 | Yes | No | SingleTurboPropEmptyWeight |
| series_hybrid | 1 | Yes | Yes | TwinSeriesHybridEmptyWeight |
| twin_series_hybrid | 2 | Yes | Yes | TwinSeriesHybridEmptyWeight |
| twin_turbofan | 2 | Yes | No | Pass-through OEW |

## Mission Types

| Type | Phases | Description |
|------|--------|-------------|
| full | v0v1, v1vr, v1v0, rotate, climb, cruise, descent | Balanced-field takeoff + mission |
| basic | climb, cruise, descent | Three-phase only |
| with_reserve | climb, cruise, descent + reserve phases + loiter | Includes fuel reserves |

## Default Mission Parameters

| Parameter | Default | Units |
|-----------|---------|-------|
| cruise_altitude | 18,000 | ft |
| mission_range | 250 | NM |
| climb_vs | 850 | ft/min |
| climb_Ueas | 104 | kn |
| cruise_Ueas | 129 | kn |
| descent_vs | 400 | ft/min |
| descent_Ueas | 100 | kn |
| num_nodes | 11 | - |

## Sweep Parameters

mission_range, cruise_altitude, battery_weight, battery_specific_energy,
hybridization, engine_rating, motor_rating

## Optimization Objectives

| Objective | OpenMDAO Path |
|-----------|---------------|
| fuel_burn | descent.fuel_used_final |
| mixed_objective | mixed_objective (fuel + MTOW/100) |
| MTOW | ac\|weights\|MTOW |

## Common Design Variables

| Name | Units | Typical Range |
|------|-------|---------------|
| ac\|weights\|MTOW | kg | 4000-6000 |
| ac\|geom\|wing\|S_ref | m^2 | 15-40 |
| ac\|propulsion\|engine\|rating | hp | 500-3000 |
| ac\|propulsion\|motor\|rating | hp | 450-3000 |
| ac\|propulsion\|generator\|rating | hp | 1-3000 |
| ac\|weights\|W_battery | kg | 20-2250 |
| cruise.hybridization | - | 0.001-0.999 |

## Common Constraints

| Name | Bound | Description |
|------|-------|-------------|
| margins.MTOW_margin | >= 0 | Weight closure |
| descent.propmodel.batt1.SOC_final | >= 0 | Battery not depleted |
| climb.throttle | <= 1.05 | Throttle feasibility |
| rotate.range_final | <= 1357 ft | Takeoff field length |
| v0v1.Vstall_eas | <= 42 kn | Stall speed limit |
