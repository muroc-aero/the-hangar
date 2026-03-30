# hangar-ocp -- OpenConcept MCP Server

This package wraps OpenConcept as an MCP tool server for aircraft conceptual design.

## Key constraints

- `num_nodes` must always be odd (3, 5, 7, 11, ...) for Simpson's rule integration
- Hybrid architectures require battery_weight, motor_rating, and generator_rating
- Propulsion architecture changes invalidate the cached OpenMDAO problem
- Aircraft data dicts use pipe-separated field names (`ac|geom|wing|S_ref`)
- CFM56 turbofan uses IntegratorGroup pattern; all others use explicit Integrator

## Propulsion architectures

- `turboprop` -- single engine, TurbopropPropulsionSystem
- `twin_turboprop` -- twin engine, TwinTurbopropPropulsionSystem
- `series_hybrid` -- single hybrid, SingleSeriesHybridElectricPropulsionSystem
- `twin_series_hybrid` -- twin hybrid, TwinSeriesHybridElectricPropulsionSystem
- `twin_turbofan` -- B738-style CFM56

## Testing

```bash
uv run pytest packages/ocp/tests/ -m "not slow"
```
