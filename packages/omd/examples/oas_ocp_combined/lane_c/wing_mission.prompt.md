# Task: Side-by-Side Wing Aero + Caravan Mission

Run an OAS VLM wing analysis and an OCP Caravan basic mission together
in a single omd plan using multi-component composition. The two
components run independently with no connections; this exercises the
composite-plan path, not coupled analysis.

## Requirements

- Component 1: `oas/AeroPoint`
  - Rectangular wing, 15.87 m span, 1.64 m chord (Caravan-like)
  - `num_x=2`, `num_y=7`, `symmetry=true`, `with_viscous=true`,
    `CD0=0.015`
  - Flight: `velocity=66.4 m/s`, `alpha=3 deg`, `Mach=0.194`,
    `rho=1.225 kg/m^3`
- Component 2: `ocp/BasicMission`
  - Aircraft template `caravan`, single turboprop
  - Mission: 250 NM range, 18,000 ft cruise, 11 nodes
- No `connections` or `shared_vars` between the two components.

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure (multi-component plans),
  the `oas-specifics.md` and `ocp-specifics.md` companion files for
  component-specific configuration, and the decision-logging contract.
  For coupled drag (OAS feeding OCP) see `slots-and-fidelity.md` and
  the `ocp_oas_coupled` example instead.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` containing both
   components and a successful `omd-cli run --mode analysis`.
2. Reported wing `CL`, `CD`, `L/D`, plus mission `fuel_burn_kg`,
   `OEW_kg`, and `MTOW_kg` from the run summary
   (`summary["components"][...]`).
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the choice to compose two
     uncoupled components in one plan.
   - `result_interpretation` covering both components.
4. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
