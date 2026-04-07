# Task: Rectangular Wing Aerostructural Analysis

Run a coupled aero+structural analysis of a rectangular wing using
omd-cli. The wing uses a tube FEM structural model coupled with VLM
aerodynamics.

## Requirements

- Wing: rectangular, 10 m span, 1 m chord, num_y=7, tube FEM
- Material: aluminum (E=70 GPa, G=30 GPa, yield=500 MPa, rho=3000 kg/m^3)
- Tube thickness: [0.01, 0.02, 0.01] m (root, mid, tip)
- Flight: velocity=248.136 m/s, alpha=5 deg, Mach=0.84
- Solvers: Newton on the coupled group, DirectSolver for linear

## Deliverables

1. Create a plan YAML for an `oas/AerostructPoint` analysis with the
   parameters above
2. Run the analysis and report CL, CD, structural mass, and failure index
3. Record a result interpretation decision: is the structure safe
   (failure < 0)? Are the aero coefficients reasonable?
4. Generate structural deformation and von Mises stress plots

Use `/omd-cli-guide` for plan structure and component types. The
aerostruct component type requires fem_model_type and material
properties in the surface config.
