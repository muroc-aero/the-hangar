# Task: Rectangular Wing Aero Analysis

Run a VLM aerodynamic analysis of a rectangular wing at transonic
cruise conditions using omd-cli.

## Requirements

- Wing: rectangular planform, 10 m span, 1 m chord
- Mesh: num_x=2, num_y=7, symmetry=true
- Flight: velocity=248.136 m/s, alpha=5 deg, Mach=0.84, Re=1e6, rho=0.38 kg/m^3
- Include viscous drag (with_viscous=true), parasitic CD0=0.015

## Deliverables

1. Create a plan YAML for an `oas/AeroPoint` analysis
2. Run the analysis and report CL, CD, and L/D
3. Record a result interpretation decision explaining whether the
   aerodynamic coefficients are physically reasonable for a rectangular
   wing at these conditions
4. Generate plots (planform, lift distribution)

Use `/omd-cli-guide` to learn the plan structure and `/oas-cli-guide`
for OAS-specific configuration details.
