# Task: Caravan Mission with a Live Wing Solve in the Loop

Find the fuel a stock Cessna 208 Caravan burns on a three-phase mission
(climb / cruise / descent) when its drag comes from a vortex-lattice wing
model solved live inside the mission's own solver iteration -- a genuine
tight coupling, not a pre-trained surrogate.

## The mission and the wing model

- Stock Caravan, standard single turboprop.
- 250 NM range, cruising at 18,000 ft.
- Climb at 850 ft/min holding 104 knots equivalent airspeed; cruise at
  129 knots equivalent airspeed; descend at 400 ft/min holding 100 knots
  equivalent airspeed; 11 integration points per phase.
- Keep the vortex lattice coarse to bound the per-iteration cost:
  2 chordwise and 5 spanwise mesh points, twist described by 4 control
  points.

## What matters

- The wing solve must run live inside the mission's solver iteration. A
  pre-trained surrogate does not satisfy the task.
- A full aerodynamic solve inside every mission iteration is harder on the
  nonlinear solver; be prepared to give it more headroom than the defaults,
  and expect minutes rather than seconds of runtime.
- Confirm convergence was clean and record that interpretation.

## Report

Fuel burn, operating empty weight, and maximum takeoff weight, all in kg.

This task deliberately does not name the component type, slot providers,
parameter keys, or tool workflow. Consult the server's own reference
material to choose them.
