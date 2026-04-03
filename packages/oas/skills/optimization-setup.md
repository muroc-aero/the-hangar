# Optimization Setup

Configure and run wing design optimization using the OAS MCP server.
Covers aerodynamic (min drag) and aerostructural (min fuel burn) optimization.

## When to use

Use this skill when the user wants to:
- Minimize drag at a target CL by varying twist and alpha
- Minimize fuel burn by varying twist, thickness, and alpha
- Minimize structural mass subject to strength constraints
- Find optimal wing shape parameters for a given mission

## Workflow

### Step 0 -- Start provenance session

```
start_session(notes="optimization: <objective> for <configuration>")
```

### Step 1 -- Create surface

For aero-only optimization (min drag):
```
create_surface(
    name="wing", wing_type="CRM",
    num_x=7, num_y=35, symmetry=True,
    with_viscous=True, CD0=0.015
)
```

For aerostructural optimization (min fuelburn/mass):
```
create_surface(
    name="wing", wing_type="CRM",
    num_x=7, num_y=35, symmetry=True,
    with_viscous=True, CD0=0.015,
    fem_model_type="tube",
    E=70e9, G=30e9, yield_stress=500e6, safety_factor=2.5, mrho=3000.0
)
```

Default to num_x=7, num_y=35 for optimization. Coarser meshes can converge
to a different optimum because induced drag and structural loads are under-
resolved. Only reduce if the user asks for speed or runtime is a problem
(try num_y=21, num_x=5 as a fallback). See the oas-cli-guide SKILL.md mesh
resolution table.

### Step 2 -- Baseline analysis

Always run a baseline before optimizing:
```
run_aero_analysis(surfaces=["wing"], velocity=248.136, alpha=5.0,
                  Mach_number=0.84, density=0.38)
```

Note the baseline CL, CD, L/D, and `run_id`. The baseline values are needed
to compute proper objective scaling.

### Step 3 -- Select design variables and log rationale

```
log_decision(
    decision_type="dv_selection",
    reasoning="<why these DVs and bounds>",
    selected_action="<DV list with bounds>",
    prior_call_id="<baseline call_id>",
    confidence="medium"
)
```

### Step 4 -- Run optimization

**Aero-only (min drag at fixed CL):**
```
run_optimization(
    surfaces=["wing"],
    analysis_type="aero",
    objective="CD",
    objective_scaler=30,          # ~ 1/baseline_CD
    design_variables=[
        {"name": "twist", "lower": -10.0, "upper": 15.0},
        {"name": "alpha", "lower": -5.0,  "upper": 15.0}
    ],
    constraints=[{"name": "CL", "equals": 0.5}],
    Mach_number=0.84, density=0.38
)
```

**Aerostructural (min fuel burn):**
```
run_optimization(
    surfaces=["wing"],
    analysis_type="aerostruct",
    objective="fuelburn",
    objective_scaler=1e-5,        # ~ 1/baseline_fuelburn
    tolerance=1e-9,
    design_variables=[
        {"name": "twist",     "lower": -10.0, "upper": 15.0},
        {"name": "thickness", "lower":  0.003, "upper": 0.25, "scaler": 100},
        {"name": "alpha",     "lower":  -5.0,  "upper": 10.0}
    ],
    constraints=[
        {"name": "L_equals_W",          "equals": 0.0},
        {"name": "failure",             "upper":  0.0},
        {"name": "thickness_intersects", "upper": 0.0}
    ],
    W0=120000, R=11.165e6, Mach_number=0.84, density=0.38
)
```

### Step 5 -- Assess convergence

```
visualize(run_id=run_id, plot_type="opt_history", output="file")
```

```
log_decision(
    decision_type="convergence_assessment",
    reasoning="<convergence quality: iterations, constraint satisfaction>",
    selected_action="<accept or re-run with different settings>",
    prior_call_id="<opt call_id>"
)
```

### Step 6 -- Report results

- Convergence: `success`, number of iterations
- Objective improvement: `summary.derived_metrics.objective_improvement_pct`
- Optimized DV values: `results.optimized_design_variables`
- Final performance: CL, CD, L/D from `results.final_results`
- Constraint satisfaction: CL residual, failure margin

### Step 7 -- Export provenance

```
export_session_graph(session_id=session_id)
```

## SLSQP Scaling -- Critical for Convergence

OAS uses SLSQP, which is very sensitive to problem scaling. The scaled
objective and DV values should all be O(1) (roughly 0.1--100).

### Computing the right scaler

`objective_scaler` should be approximately `1 / baseline_objective_value`:

| Objective | Typical baseline | objective_scaler |
|-----------|-----------------|-----------------|
| CD | ~0.03 | 30 or 1e2 |
| fuelburn | ~100,000 kg | 1e-5 |
| structural_mass | ~25,000 kg | 4e-5 |

DV scalers by magnitude:

| DV | Typical values | scaler |
|----|---------------|--------|
| thickness | 0.01--0.3 m | 100 |
| spar_thickness | 0.001--0.05 m | 1000 |
| skin_thickness | 0.001--0.05 m | 1000 |
| twist, alpha, sweep | 1--15 deg | not needed |
| chord | 1--10 m | not needed |

### When to suspect a scaling problem

- Optimizer reports `success: false` with few iterations
- Failure constraint violated at termination despite feasible initial point
- Design variables pinned at bounds without physical justification
- Converging in 1--2 iterations (DVs not being applied or bounds too tight)

## Decision guide

| Goal | objective | DVs | constraints |
|------|-----------|-----|-------------|
| Min drag (aero) | CD | twist, alpha | CL=target |
| Min fuel burn | fuelburn | twist, thickness, alpha | L_equals_W=0, failure<=0, thickness_intersects<=0 |
| Min structural mass | structural_mass | twist, thickness, alpha | L_equals_W=0, failure<=0, thickness_intersects<=0 |

## Valid design variable names

`twist`, `thickness`, `chord`, `sweep`, `taper`, `alpha`,
`spar_thickness`, `skin_thickness` (wingbox only)

OAS silently ignores unrecognized DV names. Always validate against this list.

## Valid constraint names

- Aero: `CL`, `CD`, `CM`
- Aerostruct: `CL`, `CD`, `CM`, `failure`, `thickness_intersects`, `L_equals_W`

## Reference scalers from OAS examples

| Example | Objective | objective_scaler | DV scalers |
|---------|-----------|-----------------|------------|
| run_CRM.py | fuelburn | 1e-5 | thickness: 1e2 |
| run_scaneagle.py | fuelburn | 0.1 | thickness: 1e3 |
