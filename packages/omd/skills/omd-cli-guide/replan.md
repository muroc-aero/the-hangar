# Replan Workflow

What to do when an `omd-cli run` fails or produces unsatisfactory
results. Replanning is a first-class step in the omd workflow: every
replan must be recorded as a decision so the provenance DAG carries a
traceable `wasDerivedFrom` chain from the original plan version to
each fix attempt.

## When replanning is needed

- **Non-convergence**: optimizer hit `maxiter` without converging.
- **Infeasible**: constraints cannot be simultaneously satisfied.
- **Solver failure**: NaN, `AnalysisError`, or diverging residuals.
- **Poor results**: optimizer converged but results are physically
  wrong (objective unphysical, DV pegged at an arbitrary bound).
- **Reviewer feedback**: human engineer requests changes.

## Diagnosis checklist

### 1. Non-convergence (optimizer hit maxiter)

```bash
omd-cli plot <run_id> --type convergence
```

- **Stalling** (residuals plateau): increase `maxiter`, tighten solver
  tolerances, switch from GS to Newton.
- **Diverging** (residuals increase): check DV bounds, scalers, try a
  smaller step.
- **Oscillating** (residuals bounce): add relaxation, reduce solver
  coupling.

### 2. Infeasible (constraints violated)

```bash
range-safety assert <run_id> --plan plan.yaml
```

- Are DV bounds too tight? Relax them.
- Are constraints contradictory (e.g., very low weight + very high
  load factor)?
- Is the mesh too coarse to resolve the physics?

### 3. Solver failure (NaN, AnalysisError)

- Check initial values are in a physically reasonable range.
- Check units — wrong units cause order-of-magnitude errors.
- Run `--mode analysis` first to verify the baseline before optimizing.
- Reduce mesh density temporarily to isolate the issue.

### 4. Optimizer converging in 1-2 iterations

Almost always means DVs are not being applied:

- DV names do not match actual variable paths (check `var_paths` in
  the factory).
- DV bounds are identical (`lower == upper`).
- `scaler` not set for small-valued DVs (e.g., `thickness_cp`).
- Verify with `omd-cli results <run_id>` that DVs actually changed.

## Replan process

### 1. Record the diagnosis decision

Use the interactive builder so the decision is auto-appended to
`decisions.yaml` with a `dec-auto-*` id and `replan` stage:

```bash
omd-cli plan add-decision hangar_studies/my-plan \
    --stage diagnosis \
    --decision "Thickness_cp[2] pegged at upper bound 0.05" \
    --rationale "Run run-20260403T140000-abc123 showed thickness_cp[2] \
at the upper bound. Active constraint limits the optimizer; \
relaxing upper bound to 0.1 for the next attempt."
```

For a richer entry (alternatives considered, `element_path` to the
specific DV), edit `decisions.yaml` directly:

```yaml
- id: dec-replan-001
  stage: replan
  decision: Relax thickness_cp upper bound from 0.05 to 0.10
  rationale: >
    Active bound at station 2 prevented further objective reduction.
    Re-checked structural margins offline; 0.10 is still well below
    the manufacturing maximum of 0.20.
  element_path: "design_variables[thickness_cp].upper"
  alternatives_considered:
    - option: Tighten objective scaler instead
      rejected_because: Symptom is a pegged DV, not a scaling problem.
  references:
    - run_id: run-20260403T140000-abc123
```

### 2. Modify the modular YAML files

Edit the source files in the plan directory, **not** the assembled
`plan.yaml`:

- DV bounds → `optimization.yaml`.
- Solver config → `solvers.yaml`.
- Mesh / component config → `components/<id>.yaml`.

### 3. Re-assemble and re-validate

```bash
omd-cli assemble hangar_studies/my-plan/
omd-cli validate hangar_studies/my-plan/plan.yaml
range-safety validate hangar_studies/my-plan/plan.yaml
```

The assembler auto-increments the version. The new `plan.yaml`
records `parent_version` so the new entity in the provenance DB
carries a `wasDerivedFrom` edge back to the previous version.

### 4. Re-run

```bash
omd-cli run hangar_studies/my-plan/plan.yaml --mode optimize
```

### 5. Compare and assess

```bash
omd-cli results <old_run_id> --summary
omd-cli results <new_run_id> --summary
range-safety assert <new_run_id> --plan hangar_studies/my-plan/plan.yaml
```

### 6. Log a convergence_assessment decision

```bash
omd-cli plan add-decision hangar_studies/my-plan \
    --stage convergence_assessment \
    --decision "Run <new_run_id> converged in 47 iterations; objective \
1183 kg vs 1247 kg baseline; all constraints satisfied" \
    --rationale "Accept; relaxed bound was the binding fix."
omd-cli assemble hangar_studies/my-plan/
```

### 7. Inspect the version chain

```bash
omd-cli provenance <plan_id> --format text
```

Shows the full chain:

```
Plan: plan-crm-aerostruct
  v1 [ASSEMBLE] -> EXECUTE: run-xxx (failed)
  v2 [ASSEMBLE, derived from v1] -> EXECUTE: run-yyy (optimal)
```

The `wasDerivedFrom` edge links v2 to v1, creating a traceable
replan lineage in the DAG viewer.

## Common fixes reference

| Symptom                   | Likely cause                | Fix                       |
|---------------------------|-----------------------------|---------------------------|
| Optimizer stalls          | Solver tolerance too loose  | Tighten `atol` / `rtol`   |
| DV pegged at upper bound  | Bound too tight             | Relax the bound           |
| NaN in results            | Bad initial values          | Set reasonable initials   |
| 1-2 iterations converged  | Missing scaler / wrong path | Add `scaler`; check paths |
| Constraints all violated  | Mesh too coarse             | Increase `num_y`          |
| Solver diverges           | Newton without linesearch   | Switch to GS first        |
| Optimizer ignores DV      | Unrecognized DV name        | Check factory `var_paths` |
