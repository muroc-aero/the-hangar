# Replan Workflow

What to do when a run fails or produces unsatisfactory results.

## When replanning is needed

- **Non-convergence**: optimizer hit maxiter without converging
- **Infeasible**: constraints cannot be simultaneously satisfied
- **Solver failure**: NaN, AnalysisError, or diverging residuals
- **Poor results**: optimizer converged but results are physically wrong
- **Reviewer feedback**: human engineer requests changes

## Diagnosis checklist

### 1. Non-convergence (optimizer hit maxiter)

Check the convergence table in `omd-cli run` output or generate plots:

```bash
omd-cli plot <run_id> --type convergence
```

- **Stalling** (residuals plateau): increase maxiter, tighten solver
  tolerances, try Newton instead of GS
- **Diverging** (residuals increase): check DV bounds, check scalers,
  try smaller step
- **Oscillating** (residuals bounce): add relaxation, reduce solver
  coupling

### 2. Infeasible (constraints violated)

```bash
range-safety assert <run_id> --plan plan.yaml
```

Check which constraints are violated and by how much:

- Are DV bounds too tight? Relax them.
- Are constraints contradictory? (e.g., very low weight + very high
  load factor)
- Is the mesh too coarse to resolve the physics?

### 3. Solver failure (NaN, AnalysisError)

- Check initial values: are they in a physically reasonable range?
- Check units: wrong units cause order-of-magnitude errors
- Try analysis mode first (no optimization) to verify baseline works
- Reduce mesh density temporarily to isolate the issue

### 4. Optimizer converging in 1-2 iterations

This almost always means DVs are not being applied:

- Check DV names match actual variable paths
- Check DV bounds are not identical (lower == upper)
- Check that `scaler` is set for small-valued DVs (like thickness_cp)
- Verify with `omd-cli results <run_id>` that DVs actually changed

## Replan process

### 1. Record the diagnosis

Add an entry to `decisions.yaml`:

```yaml
decisions:
  - id: dec-002
    timestamp: "2026-04-03T15:30:00Z"
    stage: diagnosis
    decision: "Thickness_cp hitting upper bound at station 2"
    rationale: >
      Run run-20260403T140000-abc123 showed thickness_cp[2] at the
      upper bound (0.05). This is an active constraint limiting the
      optimizer. Relaxing upper bound to 0.1.
    references:
      - run_id: run-20260403T140000-abc123
```

### 2. Modify the plan files

Edit the modular YAML files (not plan.yaml directly):

- Change DV bounds in `optimization.yaml`
- Change solver config in `solvers.yaml`
- Change mesh in `components/wing.yaml`

### 3. Re-assemble

```bash
omd-cli assemble my-plan/
```

The assembler auto-increments the version. The new plan.yaml will have
`parent_version` pointing to the previous version.

### 4. Validate again

```bash
omd-cli validate my-plan/plan.yaml
range-safety validate my-plan/plan.yaml --catalog-dir catalog/
```

### 5. Re-run

```bash
omd-cli run my-plan/plan.yaml --mode optimize
```

### 6. Compare results

```bash
omd-cli results <old_run_id> --summary
omd-cli results <new_run_id> --summary
```

### 7. Check provenance

```bash
omd-cli provenance <plan_id> --format text
```

This shows the full version chain:

```
Plan: plan-crm-aerostruct
  v1 [ASSEMBLE by omd] -> EXECUTE by omd: run-xxx (failed)
  v2 [ASSEMBLE by omd, derived from v1] -> EXECUTE by omd: run-yyy (optimal)
```

The `wasDerivedFrom` edge links v2 to v1, creating a traceable replan
lineage.

## Common fixes reference

| Symptom                    | Likely cause              | Fix                        |
|---------------------------|---------------------------|----------------------------|
| Optimizer stalls          | Solver tolerance too loose| Tighten atol/rtol          |
| Thickness at upper bound  | Bound too tight           | Relax upper bound          |
| NaN in results            | Bad initial values        | Set reasonable initials    |
| 1-2 iterations converged  | Missing scaler            | Add scaler to DVs          |
| Constraints all violated  | Mesh too coarse           | Increase num_y             |
| Solver diverges           | Newton without linesearch | Switch to GS first         |
