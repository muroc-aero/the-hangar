# Task: Rectangular Wing Twist Optimization

Optimize the twist distribution of a rectangular wing to minimize drag
at a target lift coefficient through the omd plan pipeline.

## Requirements

- Component type: `oas/AeroPoint`
- Wing and flight conditions: same as `aero_analysis.prompt.md`
  (10 m span, 1 m chord, Mach=0.84, alpha=5 deg)
- Design variable: `twist_cp`, bounds `[-10, 15]` deg
- Constraint: `CL = 0.5`
- Objective: minimize `CD` (use `scaler=10000` for optimizer scaling)
- Optimizer: SLSQP, `maxiter=100`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure, DV/constraint/objective
  configuration, and the decision-logging contract. Load the
  `oas-specifics.md` companion file for OAS-specific DV short names.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode optimize`.
2. Reported final `CL`, `CD`, and `L/D`, plus the drag-reduction
   percentage versus the baseline analysis.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the mesh and optimizer choice.
   - `dv_selection` documenting the DV bounds and constraint rationale.
   - `convergence_assessment` covering iteration count, constraint
     satisfaction (CL hit?), and acceptance.
4. `convergence`, `dv_evolution`, and `planform` plots via
   `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
