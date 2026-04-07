# Task: Rectangular Wing Aerostructural Study

Run a coupled aero+structural analysis of a rectangular aluminum wing
with tube FEM, then verify the results and provenance chain.

## Requirements

- Wing: rectangular, 10 m span, 1 m chord, tube FEM, aluminum
- Flight: Mach=0.84, alpha=5 deg
- See aerostruct_analysis.prompt.md for full parameter details

## Deliverables

1. Create the plan, run the analysis, and report CL, CD, L/D,
   structural mass, and failure index
2. Assess structural safety (failure < 0 means safe with margin)
3. Show the provenance timeline for the run
4. Generate structural deformation and planform plots

Use `/omd-cli-guide` to learn the plan YAML structure.
