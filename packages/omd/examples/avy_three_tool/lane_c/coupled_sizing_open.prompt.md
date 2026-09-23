# Task: Three-Tool Coupled Transport Sizing (open prompt)

Using the omd plan tools, size an advanced-technology single-aisle
transport (~150 passengers, FLOPS-class empirical methods, the
`advanced_single_aisle` deck that ships with the sizing tool) on its
design mission, with two physics-based models replacing empirical ones:

- **Wing mass** from an OpenAeroStruct wingbox structural model that runs
  inside the sizing loop (instead of the FLOPS wing-mass estimate). Use the
  mission definition the tooling provides for that wingbox coupling, not
  the default energy-state mission.
- **Engine performance** from a pyCycle high-bypass turbofan cycle model,
  tabulated as an engine deck (instead of the file engine deck). Design
  point: 35,000 ft, Mach 0.8, 5,900 lbf net thrust, 2,857 degR turbine
  inlet temperature, tabular thermodynamics. Tabulate the deck at
  altitudes 0 / 10,000 / 20,000 / 30,000 / 37,000 ft, Mach 0 / 0.25 /
  0.5 / 0.8, and throttle 0.5 / 0.7 / 0.85 / 1.0.

Optimize with SLSQP and allow up to 60 iterations.

Engineering context: the analysis couples aircraft sizing with a
climb/cruise/descent trajectory optimization -- a single optimization run
solves both, and the component supplies its own design variables and
objective. Expect the run to take a few minutes; the first run also pays
for the engine-deck sweep if no cached deck exists. Before trusting any
number, confirm the optimization actually converged; a non-converged run
still returns values.

Report the sized takeoff gross mass, total mission fuel, the wingbox wing
mass that replaced the empirical estimate, achieved range, mission
duration, and the thrust scale factor the sizing applied to the tabulated
engine deck to meet the airframe's sea-level-static thrust rating.

This task deliberately does not name the component type, config keys,
subsystem or engine-deck identifiers, or tool workflow. Consult the
server's own reference material (`omd://reference`, tool descriptions,
and error messages) to choose them.
