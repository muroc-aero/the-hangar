# Aerostructural Problem Formulation

How to formulate OAS aerostructural analysis and optimization problems.

## When to use which analysis type

- **Aero-only** (`oas/AeroPoint`): aerodynamic loads and coefficients without
  structural coupling. Appropriate when structure is not changing or when
  you only need CL, CD, L/D. Fast, minimal setup.
- **Aerostructural** (`oas/AerostructPoint`): coupled VLM aerodynamics + beam
  FEM structures. Use when structural weight, deformation, or failure index
  matter. Required for structural optimization.
- **Aerostructural optimization**: adds design variables, constraints, and an
  objective to the coupled analysis. Use when you want to find optimal
  twist, thickness, or other distributions.

## Surface definition

Every OAS analysis needs at least one lifting surface defined in the component
config under `surfaces:`.

### Required fields

- `name`: string identifier, used in variable paths (e.g., "wing")
- `num_y`: spanwise mesh points. **Must be odd** (3, 5, 7, 9, ...).
  More points = higher fidelity but slower.
- `wing_type`: `rect` (rectangular), `CRM` (NASA Common Research Model),
  or `uCRM_based` (updated CRM)

### Fidelity guidelines for num_y

| Purpose             | num_y  | Notes                           |
|---------------------|--------|---------------------------------|
| Quick sanity check  | 5      | Very coarse, qualitative only   |
| Moderate fidelity   | 7-11   | Good for design exploration     |
| Production study    | 21-31  | Use for final results           |
| Convergence study   | 41+    | Only for mesh convergence check |

### Mesh type selection

- `rect`: rectangular planform. Simple, good for teaching and validation.
  Specify `span` and `root_chord`.
- `CRM`: swept transport wing. Good for realistic transport aircraft studies.
  Built-in planform, no need to specify span/chord.

### Structural properties (aerostruct only)

Required when `fem_model_type` is set:

| Property       | Units  | Aluminum 7075 | Composite    | Titanium     |
|---------------|--------|---------------|--------------|--------------|
| `E`           | Pa     | 70e9          | 130e9        | 116e9        |
| `G`           | Pa     | 30e9          | 5e9          | 44e9         |
| `yield_stress`| Pa     | 500e6         | 600e6        | 900e6        |
| `mrho`        | kg/m^3 | 2810          | 1600         | 4430         |

Only `tube` fem_model_type is currently supported in omd factories.

## Operating point selection

Standard flight conditions go in `operating_points.yaml`:

| Variable       | Units | Typical cruise  | Typical maneuver |
|---------------|-------|-----------------|------------------|
| `velocity`    | m/s   | 248 (M0.84)     | 200              |
| `alpha`       | deg   | 3-5             | 8-12             |
| `Mach_number` | -     | 0.78-0.85       | 0.6-0.8          |
| `rho`         | kg/m^3| 0.38 (FL350)    | 1.225 (sea level)|
| `re`          | 1/m   | 1e6             | 5e6              |

## Design variables and their ranges

| DV name          | Lower  | Upper  | Scaler | Notes                          |
|-----------------|--------|--------|--------|--------------------------------|
| `twist_cp`      | -10    | 15     | 1      | Wash-out at tips is typical    |
| `thickness_cp`  | 0.001  | 0.5    | 10     | Tube model only. Needs scaler! |
| `alpha`         | -5     | 15     | 1      | For trim optimization          |

`thickness_cp` needs `scaler: 10` because its values are O(0.01) while
the optimizer works best with DVs near O(1).

## Standard constraints

| Constraint            | Bound       | Notes                           |
|----------------------|-------------|---------------------------------|
| `failure`            | upper: 0.0  | KS-aggregated failure index     |
| `L_equals_W`         | equals: 0.0 | Trim constraint (lift = weight) |
| `thickness_intersects`| upper: 0.0 | Wingbox spar intersection       |

## Standard objectives

- `structural_mass` (scaler: 1e-4) for minimum weight
- `CD` (scaler: 1e2) for minimum drag
- `fuel_burn` (scaler: 1e-4) for minimum fuel

## Known OAS pitfalls

1. **Even num_y**: OAS raises an error. Always use odd values.
2. **DV name mangling**: special characters in surface name can cause issues.
   Use simple alphanumeric names.
3. **load_factor caching**: always set load_factor explicitly per analysis.
4. **thickness_cp needs scaler**: without it, SLSQP treats thickness_cp
   changes as negligible and does not optimize the structure.
5. **Optimizer converging in 1-2 iterations**: usually means DV bounds
   are wrong or DVs are not being applied. Check the recorder.
6. **Mesh coarseness exploitation**: optimizer can find "solutions" that
   only work on coarse meshes. Verify results with finer mesh.
