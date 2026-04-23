# Task: Paraboloid Optimization

Find the minimum of `f(x, y) = (x - 3)^2 + x*y + (y + 4)^2 - 3` through
the omd plan pipeline. The analytic minimum is `x=20/3`, `y=-22/3`,
`f=-82/3`.

## Requirements

- Component type: `paraboloid/Paraboloid`
- Design variables: `x in [-50, 50]`, `y in [-50, 50]`
- Objective: minimize `f_xy`
- Optimizer: SLSQP, `maxiter=50`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure, DV / objective
  configuration, optimizer settings, and the decision-logging contract.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode optimize`.
2. Reported optimal `x`, `y`, and `f_xy`, with a comparison against
   the analytic minimum.
3. `decisions.yaml` entries:
   - `dv_selection` (DV bounds rationale) before the run.
   - `convergence_assessment` (iteration count, final objective, match
     to analytic optimum) after the run.
4. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
