# Task: Rectangular Wing Aero Study

Run a baseline VLM analysis and a twist optimization of a rectangular
wing through the omd plan pipeline, then compare the two runs.

## Requirements

- Component type: `oas/AeroPoint`
- Wing: rectangular, 10 m span, 1 m chord
- Flight: `Mach=0.84`, `alpha=5 deg` (full parameter set in
  `aero_analysis.prompt.md`)
- Optimization: DV `twist_cp in [-10, 15] deg`, constraint `CL=0.5`,
  objective minimize `CD`, SLSQP

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `oas-specifics.md` companion file for OAS-specific
  configuration.

## Deliverables

1. Two assembled plans under `hangar_studies/` (one analysis, one
   optimize) and successful `omd-cli run` for each.
2. Comparison table: baseline `CL`, `CD`, `L/D` vs. optimized values,
   with drag-reduction percentage.
3. `decisions.yaml` entries: `formulation_decision` on both plans,
   `result_interpretation` on the analysis, `dv_selection` and
   `convergence_assessment` on the optimization.
4. `planform` and `lift` plots for both runs.
5. Provenance timelines for both plans.
