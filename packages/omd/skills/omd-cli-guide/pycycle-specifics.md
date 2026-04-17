# pyCycle-Specific Notes

Deep-dive companion to `SKILL.md` covering pyCycle operating-point
keys and the plot types that only apply to pyCycle runs.

## pyCycle Operating Points

pyCycle factories expect these operating point keys:

- `alt` -- altitude in feet (default 35000)
- `MN` -- Mach number (default 0.8)
- `Fn_target` -- net thrust target in lbf (default varies by archetype)
- `T4_target` -- turbine inlet temperature in degR (default varies by archetype)

Example:

```yaml
operating_points:
  alt: 35000
  MN: 0.78
  Fn_target: 5500
  T4_target: 2850
```

For multipoint (`pyc/TurbojetMultipoint`), use:

```yaml
operating_points:
  design:
    alt: 35000
    MN: 0.8
    Fn_target: 5900
    T4_target: 2857
  off_design:
    - alt: 0
      MN: 0.01
      T4_target: 2857
    - alt: 25000
      MN: 0.6
      T4_target: 2857
```

## pyCycle Plot Types

pyCycle runs produce these additional plot types (via `omd-cli plot`):

| Plot | Description |
|------|-------------|
| `station_properties` | Grouped bar chart of total pressure and temperature at each flow station |
| `component_efficiency` | Bar chart of compressor/turbine efficiency and pressure ratio |

These are in addition to the generic plots (convergence, dv_evolution,
n2) available for all component types.
