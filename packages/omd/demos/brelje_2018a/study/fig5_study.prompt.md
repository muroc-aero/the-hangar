# Lane C (study): agent prompt for Brelje 2018a Fig 5 reproduction

Set up and run an omd **study** that reproduces Figure 5 of Brelje &
Martins 2018a in full, then render the figure from the study results.

This is the multi-case sibling of `lane_c/hybrid_mdo.prompt.md` (which
reproduces a single grid cell). Here the deliverable is the whole trade
space, not one point. Plan the work yourself: pick how to express the
sweep, how to get every cell to converge, and how to plot the result.
Ask before committing to a long compute run.

## The problem

Brelje 2018a sizes a King Air C90GT class aircraft re-engined as a
**twin series-hybrid** (turbogenerator charging a battery that drives
electric props). Figure 5 is a 2x2 panel of contour maps over a
two-axis design space; every point on every map is an **independent
fuel-burn MDO** of the aircraft at that design condition.

The four panels show, per cell: fuel mileage, trip direct operating
cost, degree of hybridization (electric energy fraction), and maximum
takeoff weight.

## Goal

1. A study spec that runs one MDO per grid cell across the full design
   space, review-first and resumable.
2. All cells converged (expect a handful of boundary cells to need
   extra help; see "convergence" below).
3. The 2x2 Fig 5 figure rendered from the study's results.

## Conditions

**Design space (the two grid axes):**
- Design range: 300 to 800 nmi.
- Battery pack specific energy: 250 to 800 Wh/kg.
- Paper-resolution grid is 11 range points x 12 energy points. You may
  pilot on a coarser grid first; confirm the final resolution.

**Per-cell optimization problem.** Each cell is the same series-hybrid
fuel-burn MDO already captured as a single-cell omd plan in
`lane_b/fuel_mdo/plan.yaml` (King Air template, `twin_series_hybrid`,
`ocp/FullMission`, `num_nodes: 11`; objective `mixed_objective` =
fuel burn + MTOW/100 kg; 10 sizing/mission design variables; takeoff
field length, stall speed, battery SOC, engine-out climb gradient,
throttle, and component-sizing constraints). The two grid axes set the
mission range and the battery specific energy for that cell; everything
else is the per-cell MDO. Reuse that plan as the per-cell base unless
you have a reason not to.

**Mission / aircraft assumptions** (already in the base plan, listed
here so you can sanity-check a cell): cruise 29000 ft, climb 1500 ft/min
at 124 kn, cruise 170 kn, descent 600 ft/min at 140 kn, 1000 lb payload.

**Paper-specific overrides (non-obvious, keep them).** The stock King
Air template is the unhybridized C90GT. The paper's hybrid variant uses
a heavier structure (`structural_fudge` 2.0 vs the template's 1.6,
~25% heavier OEW) and a 2.2 m propeller. Without these the MDO settles
in a different, lighter basin and the contours do not match the paper.
These already live in the base plan's `initial_values`; preserve them.

**Convergence.** SLSQP from a single start strands some cells in
infeasible or poor local optima. The verified recipe runs each cell
from more than one starting point (a low-hybridization / small-battery
start and a high-hybridization / large-battery start) and keeps the
better optimum. A few cells near the grid boundary may still fail a
cold multistart and need a warm start from a converged neighbor.

## Anchors (to check you are in the right basin)

Paper Table 4 publishes three reference cells at 500 nmi. Spot-check
your converged cells against them (a few percent is fine; the all-
electric high-energy cell sits on a flatter ridge, so allow more):

| range, spec energy | mixed objective (kg) | MTOW |
|---|---|---|
| 500 nmi, 250 Wh/kg | ~382 | ~8900 lb |
| 500 nmi, 500 Wh/kg | ~293 | ~12600 lb |
| 500 nmi, 750 Wh/kg | ~57  | ~12500 lb |

## How to work

- The study layer (matrix expansion, multistart pick-best, checkpointed
  incremental runs, a per-cell results table) is documented in
  `docs/STUDIES.md`; the commands and plan-authoring conventions are in
  the `omd-cli-guide` skill, and `design-study-workflow` covers the
  requirements -> run -> conclusion loop. Read what you need; do not
  hand-roll a bespoke sweep driver.
- **Review before you run.** Matrix axes multiply, and the full grid is
  many hours of compute. Review the case count and estimate, run a small
  pilot batch first, confirm the anchors look right, then commit to the
  rest. The run is resumable.
- For plotting: the study layer renders the 2x2 trade grid directly with
  `omd-cli study plot <study_id>` (OCP mission studies get the Fig 5/6
  four-panel layout, including the derived fuel-mileage / electric-percent
  / DOC panels). The older `pipeline/plotting.py` renders the same figure
  from the CSV pipeline's per-cell grid and is still the path the full
  verified reproduction uses.
- If anything here is ambiguous (final grid resolution, where to write
  files, how much compute to spend, whether to reuse the lane_b plan),
  ask before running.
