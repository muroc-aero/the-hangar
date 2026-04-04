# Plan Validation Checklist

Pre-flight checklist before submitting a plan for execution. Run
`range-safety validate` to automate these checks.

## Automated checks (range-safety validate)

### Structural checks

- [ ] All component types exist in the catalog
- [ ] All component IDs are unique
- [ ] `num_y` is odd for all surfaces
- [ ] AerostructPoint surfaces have `fem_model_type`
- [ ] Material properties (E, G, yield_stress, mrho) are set when
      fem_model_type is specified
- [ ] Solver type is a known OpenMDAO solver
- [ ] Optimizer type is a known OpenMDAO driver
- [ ] Nonlinear solver has a paired linear solver
- [ ] DV, constraint, and objective names are non-empty
- [ ] Connection endpoints reference existing component IDs

### Traceability checks

- [ ] Every requirement has at least one `traces_to` link
- [ ] All `traces_to` targets exist (DV, constraint, or objective name)
- [ ] DV traces_to references point to valid requirement IDs
- [ ] Constraint traces_to references point to valid requirement IDs
- [ ] Objective traces to at least one requirement
- [ ] No orphan requirements (requirement with nothing referencing it)

### Heuristic checks

- [ ] DV bounds within catalog recommended ranges
- [ ] Operating point values in physically reasonable ranges
- [ ] DVs with large dynamic range have scalers
- [ ] Optimization has at least one DV and one objective
- [ ] Mesh is not too coarse for optimization (num_y >= 5)

## Running the checks

```bash
# Validate the assembled plan
range-safety validate my-plan/plan.yaml --catalog-dir catalog/
```

Output is structured JSON:

```json
{
  "status": "pass",
  "error_count": 0,
  "warning_count": 2,
  "findings": [
    {
      "check": "dv_bounds_catalog",
      "severity": "warning",
      "message": "DV 'twist_cp' upper bound 20.0 is above catalog recommended maximum 15.0"
    }
  ]
}
```

- **status: pass** -- no errors, plan is executable
- **status: warn** -- warnings only, plan is executable but review findings
- **status: fail** -- errors found, fix before running

Exit code is 0 for pass/warn, 1 for fail.

## Manual checks (not yet automated)

These are checks the agent should perform that are not yet in the
automated validator:

- [ ] Operating conditions match the study intent (cruise vs maneuver)
- [ ] Wing type matches the study (CRM for transport, rect for simple)
- [ ] DV scalers are set to put DVs near O(1) for the optimizer
- [ ] Constraint scalers are set appropriately
- [ ] Objective scaler is set (e.g., 1e-4 for structural_mass)
- [ ] If coupled problem: verify solver config matches solver-selection skill
- [ ] Decision log documents key choices

## Post-run assertions

After execution, run assertions to verify convergence and constraint
satisfaction:

```bash
range-safety assert <run_id> --plan my-plan/plan.yaml
```

Checks:
- Run exists and has recorded data
- No NaN values in final results
- Objective improved (for optimization)
- All constraints satisfied within tolerance
