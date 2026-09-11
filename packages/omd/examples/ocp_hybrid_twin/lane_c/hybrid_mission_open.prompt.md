# Task: Series-Hybrid King Air Fuel Burn

Find the fuel burned by a King Air C90GT re-engined as a twin series-hybrid
electric aircraft on a full mission (balanced-field takeoff plus climb /
cruise / descent).

## The aircraft and the mission

- Start from the stock King Air C90GT definition that ships with the
  tooling; swap its propulsion for a twin series-hybrid architecture.
- Battery specific energy: 450 Wh/kg.
- Cruise hybridization fraction: 0.058 (5.8% of cruise power from the
  battery).
- Payload: 1,000 lb.
- Mission: 500 NM range, cruising at 29,000 ft.
- Climb at 1,500 ft/min holding 124 knots equivalent airspeed.
- Cruise at 170 knots equivalent airspeed.
- Descend at 600 ft/min holding 140 knots equivalent airspeed.
- Integrate each phase on 11 points.

## What matters

- The hybrid architecture changes the model topology; make sure the
  propulsion choice is applied before the mission is analysed.
- Confirm the solve converged, and record that interpretation.

## Report

Fuel burn, operating empty weight, and maximum takeoff weight, all in kg.

This task deliberately does not name the component type, parameter keys, or
tool workflow. Consult the server's own reference material to choose them.
