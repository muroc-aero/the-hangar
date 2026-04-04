# Plan Authoring Workflow

Step-by-step process for going from a study instruction to a validated,
executable analysis plan.

## Overview

```
Study instruction
  -> 1. UNDERSTAND the requirements
  -> 2. SELECT components from catalog
  -> 3. DRAFT the plan directory
  -> 4. ASSEMBLE and VALIDATE
  -> 5. RUN range-safety pre-flight
  -> 6. EXECUTE
  -> 7. PLOT results for human review
  -> 8. ASSESS results
  -> 9. REPLAN if needed (see replan-workflow.md)
```

## Step 1: Understand the study instruction

Parse the instruction for:
- What quantity to optimize or analyze? (CL, CD, structural_mass, fuel_burn)
- What constraints exist? (failure index, trim, specific CL target)
- What fidelity level is appropriate? (quick check vs production study)
- What wing type? (rect for simple, CRM for transport aircraft)
- What flight conditions? (Mach, altitude, alpha)

## Step 2: Select components from the catalog

Read the catalog YAMLs in `catalog/oas/` to find the right component type.
See `skills/domain/component-catalog-guide.md` for details.

- Aero-only analysis: `oas/AeroPoint`
- Aerostructural analysis or optimization: `oas/AerostructPoint`

## Step 3: Draft the plan directory

Create a directory with modular YAML files:

```
my-plan/
  metadata.yaml
  components/
    wing.yaml
  operating_points.yaml
  solvers.yaml           # required for aerostructural
  optimization.yaml      # only for optimization studies
  requirements.yaml      # formal requirements with traces
  decisions.yaml         # decision log (initially empty or first entry)
```

### metadata.yaml

```yaml
id: plan-crm-aero-cruise
name: CRM wing aero analysis at cruise
```

### components/wing.yaml

```yaml
id: wing
type: oas/AeroPoint
config:
  surfaces:
    - name: wing
      wing_type: CRM
      num_y: 11
      symmetry: true
      with_viscous: true
```

### operating_points.yaml

```yaml
velocity: 248.136
alpha: 3.0
Mach_number: 0.85
re: 1.0e6
rho: 0.38
```

### solvers.yaml (for aerostructural)

```yaml
nonlinear:
  type: NewtonSolver
  options:
    maxiter: 20
    atol: 1.0e-6
    solve_subsystems: true
linear:
  type: DirectSolver
```

### optimization.yaml (for optimization studies)

```yaml
design_variables:
  - name: twist_cp
    lower: -10.0
    upper: 15.0
    traces_to: [R1]

constraints:
  - name: failure
    upper: 0.0
    traces_to: [R2]

objective:
  name: structural_mass
  scaler: 1.0e-4
  traces_to: [R1]

optimizer:
  type: SLSQP
  options:
    maxiter: 100
```

### requirements.yaml

```yaml
requirements:
  - id: R1
    text: Minimize structural mass
    type: objective
    traces_to: [structural_mass, twist_cp]
  - id: R2
    text: Structure must not fail under load
    type: constraint
    traces_to: [failure]
```

### decisions.yaml

```yaml
decisions:
  - id: dec-001
    timestamp: "2026-04-03T14:00:00Z"
    stage: formulation
    decision: "Selected NewtonSolver for coupled problem"
    rationale: >
      Mesh resolution (num_y=7) is moderate. Newton is standard
      for aerostructural coupling per solver-selection skill.
    references:
      - skill: domain/solver-selection.md
```

## Step 4: Assemble and validate

```bash
omd-cli assemble my-plan/
omd-cli validate my-plan/plan.yaml
```

Fix any schema errors and re-assemble. The assembler auto-increments
the version and archives to `history/`.

## Step 5: Run range-safety pre-flight checks

```bash
range-safety validate my-plan/plan.yaml --catalog-dir catalog/
```

Review the output. Fix errors (severity: error). Warnings are advisory
but should be addressed or documented in decisions.yaml.

## Step 6: Execute

```bash
# Analysis first (sanity check)
omd-cli run my-plan/plan.yaml --mode analysis

# Then optimization if the study requires it
omd-cli run my-plan/plan.yaml --mode optimize
```

## Step 7: Generate plots for human review

```bash
omd-cli plot <run_id> --type all --output plots/
```

Plot types:
- `planform`: top-down mesh view (verify geometry)
- `lift`: spanwise lift distribution (verify aerodynamics)
- `convergence`: objective vs iteration (verify optimization converged)
- `struct`: deformed vs undeformed mesh (verify structural response)
- `twist`: twist distribution (verify aerodynamic shaping)
- `thickness`: spar thickness (verify structural sizing)

## Step 8: Assess results

```bash
omd-cli results <run_id> --summary
range-safety assert <run_id> --plan my-plan/plan.yaml
```

Check:
- Did the optimizer converge? (status: converged)
- Are all constraints satisfied? (range-safety assert passes)
- Is the objective value physically reasonable?
- Do the plots look correct to a human engineer?

## Step 9: Replan if needed

If the run failed or results are not satisfactory, see
`skills/omd/replan-workflow.md` for the diagnosis and replan process.
