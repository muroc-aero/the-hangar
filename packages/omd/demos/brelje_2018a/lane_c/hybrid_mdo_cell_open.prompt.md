# Series-hybrid King Air sizing MDO at one design condition

Size a twin series-hybrid-electric turboprop (a King Air C90GT re-engined
so a turboshaft drives a generator, and a battery plus that generator feed
two electric motors turning the propellers) for one design condition, by
running a multidisciplinary design optimization of the full mission.

## Design condition

- Design range: **{range_nm:g} nmi**
- Battery pack specific energy: **{spec_e:g} Wh/kg**

## Aircraft and mission

- Start from the King Air C90GT aircraft data with the twin series-hybrid
  propulsion architecture.
- Hybrid-variant airframe changes from the stock C90GT: structural weight
  factor 2.0 (the stock value is 1.6; ~25 % heavier OEW) and a 2.2 m
  propeller diameter. Start the engine rating at 1117.2 hp.
- Full mission with a balanced-field takeoff analysis, climb, cruise and
  descent, 11 analysis nodes per phase.
- Cruise altitude 29000 ft; climb 1500 ft/min at 124 kn EAS; cruise
  170 kn EAS; descent 600 ft/min at 140 kn EAS; payload 1000 lb.

## Optimization problem

{objective_text}

Design variables and bounds:

| variable | lower | upper |
|---|---|---|
| MTOW | 4000 kg | 5700 kg |
| wing reference area | 15 m^2 | 40 m^2 |
| turboshaft engine rating | 1 hp | 3000 hp |
| motor rating | 450 hp | 3000 hp |
| generator rating | 1 hp | 3000 hp |
| battery weight | 20 kg | 2250 kg |
| maximum fuel capacity | 500 kg | 3000 kg |
| climb / cruise hybridization (electric power fraction) | 0.001 | 0.999 |
| descent hybridization | 0.01 | 1.0 |

Constraints:

- MTOW margin (MTOW - OEW - fuel burned - battery - payload) >= 0
- balanced field length <= 4452 ft
- stall speed <= 81.6 kn EAS (42 m/s)
- battery state of charge at the end of descent >= 0
- engine-out climb gradient >= 0.02
- climb throttle <= 1.05 at every node
- engine, generator and battery power ratings not exceeded in climb,
  cruise and descent (component sizing margins <= 1), and battery rating
  not exceeded in the takeoff roll

Optimizer: SLSQP, up to 150 iterations, tolerance 1e-6.

This problem has more than one local optimum (a fuel-dominant and a
battery-dominant family of designs). Report the best feasible optimum you
find; it is up to you whether and how to check more than one starting
point.

## Report

Report the converged objective, MTOW, fuel burned, battery weight, wing
area, and the cruise, climb and descent hybridization of the design you
consider the answer, and the run that produced it.
