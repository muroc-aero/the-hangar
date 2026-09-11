# Task: Caravan Mission with a Gas-Turbine Cycle in the Loop

Run a stock Cessna 208 Caravan three-phase mission (climb / cruise /
descent) with its propulsion replaced by a thermodynamic turbojet cycle
model. The turbojet is deliberately unrealistic for this airframe -- the
point is to demonstrate that a cycle analysis can drive the mission's
thrust and fuel flow, not to design a sensible aeroplane.

## The mission and the engine

- Stock Caravan airframe.
- 250 NM range, cruising at 18,000 ft.
- Climb at 850 ft/min holding 104 knots equivalent airspeed; cruise at
  129 knots equivalent airspeed; descend at 400 ft/min holding 100 knots
  equivalent airspeed; 11 integration points per phase.
- Turbojet design point: 18,000 ft, Mach 0.35, 4,000 lbf net thrust,
  turbine inlet temperature 2,370 degrees Rankine.

## What matters

- The engine replacement must displace the default turboprop, not sit next
  to it. Expect a one-time engine-deck training step when the run starts.
- Confirm the solve converged, and record that interpretation.

## Report

Fuel burn, operating empty weight, and maximum takeoff weight, all in kg.

This task deliberately does not name the component type, slot providers,
parameter keys, or tool workflow. Consult the server's own reference
material to choose them.
