# Task: Side-by-Side Wing Aero + Caravan Mission

Run an OAS VLM wing analysis and an OCP Caravan basic mission together
in a single omd Problem using multi-component composition.

## Requirements

- Component 1: OAS aero-only wing analysis
  - Rectangular wing, 15.87 m span, 1.64 m chord (Caravan-like)
  - num_x=2, num_y=7, symmetry=true, with_viscous=true, CD0=0.015
  - Flight: velocity=66.4 m/s, alpha=3 deg, Mach=0.194, rho=1.225

- Component 2: OCP Caravan basic mission
  - Aircraft: Caravan template, single turboprop
  - Mission: 250 NM, 18,000 ft cruise, 11 nodes

- The two components run independently (no connections between them).
  This demonstrates multi-component composition, not coupled analysis.

## Deliverables

1. Create a plan YAML with two components: an `oas/AeroPoint` and an
   `ocp/BasicMission`, each with their own config
2. Run the plan and report wing CL, CD, L/D alongside mission fuel burn
3. Record a result interpretation decision

Use `/omd-cli-guide` to learn how to define multiple components in a
single plan. Note: for coupled drag analysis where OAS feeds into OCP,
see the `ocp_oas_coupled` example which uses the slot system instead.
