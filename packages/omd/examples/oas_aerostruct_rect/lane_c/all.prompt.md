# Task: Rectangular Wing Aerostructural Study

Run a coupled aero+structural analysis of a rectangular aluminum wing
with tube FEM through the omd plan pipeline, then verify the results
and the provenance chain.

## Requirements

- Component type: `oas/AerostructPoint`
- Wing: rectangular, 10 m span, 1 m chord, tube FEM, aluminum
- Flight: `Mach=0.84`, `alpha=5 deg`
- Full parameter set in `aerostruct_analysis.prompt.md`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `oas-specifics.md` companion file for FEM model
  type and material properties.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `CL`, `CD`, `L/D`, `structural_mass`, and `failure`.
3. `decisions.yaml` entries: `formulation_decision` and
   `result_interpretation` (with explicit structural-safety check).
4. `struct` and `planform` plots via `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
