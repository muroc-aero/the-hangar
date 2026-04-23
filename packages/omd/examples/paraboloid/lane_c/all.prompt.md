# Task: Paraboloid Analysis and Optimization

Run both a function evaluation and an optimization of
`f(x, y) = (x - 3)^2 + x*y + (y + 4)^2 - 3` through the omd plan
pipeline, then compare the two runs.

## Requirements

- Component type: `paraboloid/Paraboloid`
- Analysis: `x=1.0`, `y=2.0`
- Optimization: DVs `x, y in [-50, 50]`, objective `f_xy`, SLSQP
- Analytic minimum reference: `x=20/3`, `y=-22/3`, `f=-82/3`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure, DV / objective
  configuration, and the decision-logging contract.

## Deliverables

1. Two assembled plans under `hangar_studies/` (one analysis, one
   optimize) and successful `omd-cli run` for each.
2. Comparison table: analysis `f_xy` vs. optimized `f_xy` and DV values.
3. `decisions.yaml` entries on the optimization plan: `dv_selection`
   before, `convergence_assessment` after.
4. Provenance timelines for both plans.
