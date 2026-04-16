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
  -> 5. REVIEW completeness (omd-cli plan review)
  -> 6. RUN range-safety pre-flight
  -> 7. EXECUTE
  -> 8. PLOT results for human review
  -> 9. ASSESS results
  -> 10. REPLAN if needed (see replan-workflow.md)
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
  analysis_plan.yaml     # process: strategy, phases, checks (optional)
  rationale.yaml         # short top-level rationale list (optional)
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

### requirements.yaml (enriched form)

```yaml
- id: R1
  text: Minimize structural mass
  type: objective
  priority: primary                 # primary | secondary | goal
  source: study instruction
  status: open                      # draft | open | verified | violated | waived
  traces_to: [structural_mass, twist_cp]
  acceptance_criteria:
    - metric: structural_mass
      comparator: "<"
      threshold: 200.0
      units: kg
  verification:
    method: automated               # automated | visual | comparison
    assertion: "structural_mass < 200.0"

- id: R2
  text: Structure must not fail under load
  type: constraint
  priority: primary
  status: open
  traces_to: [failure]
  acceptance_criteria:
    - metric: failure
      comparator: "<="
      threshold: 0.0
      units: dimensionless
  verification:
    method: automated
    assertion: "failure <= 0.0"
```

Only `id` and `text` are required. The other fields are optional, but
`omd-cli plan review` will WARN on requirements without
`acceptance_criteria` or `verification`.

### decisions.yaml (enriched form)

```yaml
- id: dec-mesh
  stage: mesh_selection                                   # see recommended stages below
  decision: Set num_y=7 for initial exploration
  rationale: >
    Moderate fidelity per aerostructural-formulation.md guidelines.
    Will increase to 21+ for production after confirming convergence.
  element_path: "components[wing].config.surfaces[wing].num_y"   # what this justifies
  alternatives_considered:
    - option: "num_y=21"
      rejected_because: Iteration time too high for exploration.
  references:
    - skill: domain/aerostructural-formulation.md
```

**`element_path`** is optional but strongly recommended. Without it, the
plan knowledge graph cannot draw a concrete `justifies` edge — the
decision falls back to pointing at the whole plan node and
`omd-cli plan review` emits a graph-completeness WARN.

Supported `element_path` syntax:

- `components[wing]`, `design_variables[wing.twist_cp]` -- id/name match.
- `components[wing].config.surfaces[wing].num_y` -- nested dot access.
- `objective`, `solvers.nonlinear`, `solvers.linear`.
- `requirements[R1]`, `analysis_plan.phases[phase-1]`.
- `connections[0].src` -- positional fallback for elements with no id.

**Recommended `stage` values** (soft-enforced by `plan review`):
`problem_definition`, `component_selection`, `mesh_selection`,
`solver_selection`, `dv_setup`, `constraint_setup`,
`objective_selection`, `operating_point_selection`,
`optimizer_selection`, `diagnosis`, `replan`, `formulation`.

### analysis_plan.yaml (optional but recommended)

Captures *how* to proceed, not just *what* to compute. Phases are
documented in the plan graph and provenance DAG; execution
orchestration (`omd-cli run --phase`) is a deferred capability --
see `packages/omd/docs/deferred-enhancements.md`.

```yaml
strategy: Verify baseline, optimize, then assert.
phases:
  - id: phase-1
    name: Baseline verification
    mode: analysis
    depends_on: []
    success_criteria:
      - metric: CL
        comparator: in
        range: [0.3, 0.7]
      - metric: solver_iterations
        comparator: "<"
        threshold: 50
    checks:
      - type: plot
        plots: [planform, lift, twist]
        look_for: Smooth lift distribution; geometry matches intent.
      - type: assertion
        command: "range-safety validate {plan}"
  - id: phase-2
    name: Optimization
    mode: optimize
    depends_on: [phase-1]
    success_criteria:
      - metric: failure
        comparator: "<="
        threshold: 0.0
    checks:
      - type: plot
        plots: [convergence, dv_evolution, struct, vonmises]
        look_for: Smooth convergence; no DV pegged at bounds.
replan_triggers:
  - Solver divergence or NaN in results.
  - Optimizer hits maxiter without converging.
  - Any DV pegged at its bound in the final solution.
```

## Step 4: Assemble and validate

```bash
omd-cli assemble my-plan/
omd-cli validate my-plan/plan.yaml
```

Fix any schema errors and re-assemble. The assembler auto-increments
the version and archives to `history/`.

## Step 5: Review completeness

```bash
omd-cli plan review my-plan/
omd-cli plan review my-plan/ --format json > review.json    # for CI gating
```

Always exits 0 (advisory). Reports per-section status (OK / WARN /
MISSING / ERROR) covering:

- requirements without `acceptance_criteria` or `verification`
- decisions without `element_path` (cannot render as `justifies` edge)
- decisions whose `element_path` fails to resolve
- decisions with a `stage` outside the recommended set
- configurable sections (mesh, DVs, constraints, objective, solvers,
  optimizer) with no decisions pointing at them
- missing `analysis_plan` or phases without `success_criteria`
- `depends_on` referring to an unknown phase (ERROR)
- missing top-level `rationale`

The checker and the plan knowledge graph share the same element-path
resolver, so every WARN here corresponds to a concrete missing edge or
node in the viewer.

## Step 6: Run range-safety pre-flight checks

```bash
range-safety validate my-plan/plan.yaml --catalog-dir catalog/
```

Review the output. Fix errors (severity: error). Warnings are advisory
but should be addressed or documented in decisions.yaml.

## Step 7: Execute

```bash
# Analysis first (sanity check)
omd-cli run my-plan/plan.yaml --mode analysis

# Then optimization if the study requires it
omd-cli run my-plan/plan.yaml --mode optimize
```

## Step 8: Generate plots for human review

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

## Step 9: Assess results

```bash
omd-cli results <run_id> --summary
range-safety assert <run_id> --plan my-plan/plan.yaml
```

Check:
- Did the optimizer converge? (status: converged)
- Are all constraints satisfied? (range-safety assert passes)
- Is the objective value physically reasonable?
- Do the plots look correct to a human engineer?

If a requirement has an `acceptance_criteria` entry, a later
verification-loop pass will emit `satisfies` / `violates` edges
against the requirement in the provenance DAG (see
`packages/omd/docs/deferred-enhancements.md`). Until that lands,
assess by inspection and record the verdict in a
`result_interpretation` decision.

## Step 10: Replan if needed

If the run failed or results are not satisfactory, see
`skills/omd/replan-workflow.md` for the diagnosis and replan process.
