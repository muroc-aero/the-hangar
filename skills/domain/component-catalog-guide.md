# Component Catalog Guide

How to read and use the component catalog for plan authoring.

## Where catalog files live

```
catalog/
  oas/
    AeroPoint.yaml          # Aero-only VLM analysis
    AerostructPoint.yaml    # Coupled aero + structures
```

Each YAML file describes one component type that can be used in a plan.

## Catalog entry structure

```yaml
type: oas/AerostructPoint       # Component type string (used in plan)
source: openaerostruct           # Upstream package
description: ...                 # What it does
import_path: ...                 # Python import path

inputs:
  surface_config:                # Surface geometry parameters
    name: { type: string, required: true }
    num_y: { type: integer, minimum: 3, required: true }
    ...
  flight_conditions:             # Operating point parameters
    velocity: { type: number, units: m/s, default: 248.136 }
    ...

outputs:                         # Available result variables
  CL: { units: dimensionless }
  CD: { units: dimensionless }
  ...

recommended_solvers:             # Solver configuration to start with
  nonlinear: { type: NewtonSolver, options: { ... } }
  linear: { type: DirectSolver }

recommended_dvs:                 # Design variables with recommended ranges
  - name: twist_cp
    lower: -10.0
    upper: 15.0
    ...

recommended_constraints:         # Common constraints
  - name: failure
    upper: 0.0
    ...

known_issues:                    # Documented pitfalls
  - "num_y must be odd"
  ...
```

## How to use the catalog when authoring a plan

### 1. Select the component type

Read the catalog entry for each candidate component type. Choose based on
what the study needs:

- Need CL, CD, L/D only? Use `oas/AeroPoint`
- Need structural weight, deformation, failure? Use `oas/AerostructPoint`

### 2. Configure the surface

Use `inputs.surface_config` to see what parameters are available.
Required fields must be set. Pay attention to:

- `num_y` must be odd
- `fem_model_type` is required for AerostructPoint (use `tube`)
- Material properties (E, G, yield_stress, mrho) are required when
  fem_model_type is set

### 3. Set operating conditions

Use `inputs.flight_conditions` for the operating point. The defaults
are reasonable for a transport aircraft cruise condition.

### 4. Choose solvers

Start with `recommended_solvers` from the catalog. For aero-only,
solvers are optional. For aerostructural, they are required.

### 5. Set design variables (for optimization)

Use `recommended_dvs` for starting ranges. The catalog provides
physically reasonable bounds. If your study needs different bounds,
justify the change in `decisions.yaml`.

### 6. Set constraints (for optimization)

Use `recommended_constraints` for standard constraints. Not all
constraints apply to every study. Choose the ones that match
your requirements.

### 7. Check known issues

Read the `known_issues` section before finalizing the plan. These
are documented failure modes that can waste time if not addressed
up front.

## Mapping catalog data to plan YAML

| Catalog field                | Plan YAML location                      |
|-----------------------------|------------------------------------------|
| `type`                      | `components[].type`                      |
| `inputs.surface_config.*`   | `components[].config.surfaces[].*`       |
| `inputs.flight_conditions.*`| `operating_points.*`                     |
| `recommended_solvers`       | `solvers`                                |
| `recommended_dvs`           | `design_variables`                       |
| `recommended_constraints`   | `constraints`                            |
| `outputs`                   | Used in `objective.name`, `constraints[].name` |
