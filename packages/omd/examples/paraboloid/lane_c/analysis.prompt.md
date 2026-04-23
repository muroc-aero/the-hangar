# Task: Paraboloid Analysis

Evaluate `f(x, y) = (x - 3)^2 + x*y + (y + 4)^2 - 3` at `x=1.0, y=2.0`
through the omd plan pipeline.

## Requirements

- Component type: `paraboloid/Paraboloid`
- Evaluation point: `x=1.0`, `y=2.0`
- Mode: analysis (no optimization)

## Tools

- `omd-cli` for plan authoring (`plan init`, `plan add-component`, ...),
  assembly, execution, results query, and provenance.
- `/omd-cli-guide` skill for plan structure, component types, CLI
  subcommand flags, and the decision-logging contract.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `f_xy` from `omd-cli results <run_id> --summary`.
3. `decisions.yaml` entry of type `result_interpretation` with the
   specific f_xy value and a brief reasonableness check.
4. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
