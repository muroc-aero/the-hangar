# Task: Rectangular Wing Aero Analysis

Run a VLM aerodynamic analysis of a rectangular wing at transonic
cruise conditions through the omd plan pipeline.

## Requirements

- Component type: `oas/AeroPoint`
- Wing: rectangular planform, 10 m span, 1 m chord
- Mesh: `num_x=2`, `num_y=7`, `symmetry=true`
- Flight: `velocity=248.136 m/s`, `alpha=5 deg`, `Mach=0.84`,
  `Re=1e6`, `rho=0.38 kg/m^3`
- Viscous drag enabled, `CD0=0.015`

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure, component types, and the
  decision-logging contract. Load the `oas-specifics.md` companion
  file for OAS mesh and surface configuration details.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `CL`, `CD`, and `L/D` from the run summary.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the mesh / fidelity choice.
   - `result_interpretation` with specific CL/CD values and a physics
     reasonableness check for a rectangular wing at this Mach number.
4. `planform` and `lift` plots via `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
