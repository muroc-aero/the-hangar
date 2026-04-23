# Task: Rectangular Wing Aerostructural Analysis

Run a coupled aero+structural analysis of a rectangular wing through
the omd plan pipeline. The wing uses a tube FEM structural model
coupled with VLM aerodynamics.

## Requirements

- Component type: `oas/AerostructPoint`
- Wing: rectangular, 10 m span, 1 m chord, `num_y=7`, tube FEM
- Material: aluminum
  (`E=70 GPa`, `G=30 GPa`, `yield=500 MPa`, `rho=3000 kg/m^3`)
- Tube thickness: `[0.01, 0.02, 0.01] m` (root, mid, tip)
- Flight: `velocity=248.136 m/s`, `alpha=5 deg`, `Mach=0.84`
- Solvers: `NewtonSolver` nonlinear, `DirectSolver` linear

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load the `oas-specifics.md` companion file for FEM model
  type, material properties, and aerostruct DV short names.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `CL`, `CD`, `structural_mass`, and `failure` from the run
   summary.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the mesh, FEM model, and
     solver choices.
   - `result_interpretation` covering structural safety (failure < 0?)
     and aerodynamic reasonableness.
4. `struct`, `vonmises`, and `planform` plots via `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
