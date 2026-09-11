# Task: Caravan Mission with Wing-Derived Drag

Find the fuel a stock Cessna 208 Caravan burns on a three-phase mission
(climb / cruise / descent) when its drag comes from an actual wing
aerodynamics model instead of the default parabolic drag polar. The wing
model should be a vortex-lattice method wrapped as a pre-trained surrogate,
not solved live inside the mission iteration.

## The mission and the wing model

- Stock Caravan, standard single turboprop.
- 250 NM range, cruising at 18,000 ft.
- Climb at 850 ft/min holding 104 knots equivalent airspeed; cruise at
  129 knots equivalent airspeed; descend at 400 ft/min holding 100 knots
  equivalent airspeed; 11 integration points per phase.
- Vortex-lattice resolution: 2 chordwise and 7 spanwise mesh points, with
  the twist distribution described by 4 control points.

## What matters

- The drag replacement is the point of the task: the mission's default drag
  model must be swapped for the VLM-surrogate one, not run alongside it.
- Confirm the solve converged, and record that interpretation.

## Report

Fuel burn, operating empty weight, and maximum takeoff weight, all in kg.

This task deliberately does not name the component type, slot providers,
parameter keys, or tool workflow. Consult the server's own reference
material to choose them.
