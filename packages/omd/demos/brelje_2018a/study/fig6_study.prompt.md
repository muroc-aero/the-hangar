# Lane C (study): agent prompt for Brelje 2018a Fig 6 reproduction

Set up and run an omd **study** that reproduces Figure 6 of Brelje &
Martins 2018a in full, then render the figure from the study results.

Figure 6 is the same trade space as Figure 5 over the same aircraft and
the same grid, but each cell is optimized for a **different objective**.
If you have already built the Fig 5 study, this is mostly a re-targeting
of it; read `fig5_study.prompt.md` first for the shared context. Plan
the work yourself and ask before committing to a long compute run.

## The problem

Brelje 2018a sizes a King Air C90GT class aircraft re-engined as a
**twin series-hybrid**. Figure 6 is a 2x2 panel of contour maps over a
two-axis design space; every point is an **independent MDO**, but here
the optimizer minimizes **trip direct operating cost (DOC)** rather than
fuel burn. The four panels show the same quantities as Figure 5 (fuel
mileage, trip DOC, degree of hybridization, MTOW), so the contrast
between the two figures is exactly the effect of optimizing for cost
instead of fuel.

## Goal

1. A study spec that runs one minimum-DOC MDO per grid cell across the
   full design space, review-first and resumable.
2. All cells converged.
3. The 2x2 Fig 6 figure rendered from the study's results.

## Conditions

**Design space (the two grid axes):** identical to Fig 5: design range
300 to 800 nmi, battery specific energy 250 to 800 Wh/kg, paper grid
11 x 12. Confirm the final resolution.

**Per-cell optimization problem.** Same aircraft, mission, design
variables, and constraints as Fig 5. Two differences:
- The objective is trip DOC per nautical mile, not fuel + MTOW/100.
- The cost model must be active so that DOC exists as an output. The
  single-cell version is captured in `lane_b/cost_mdo/plan.yaml`
  (note `include_cost_model: true` on the mission component and the
  `doc_per_nmi` objective); reuse it as the per-cell base unless you
  have a reason not to. The DOC coefficients follow the paper's
  Section IV.D cost model.

**Paper-specific overrides:** same as Fig 5 (heavier structure,
2.2 m prop), already in the base plan; preserve them.

**Convergence.** Same multistart pick-best recipe as Fig 5. Cost
objectives can warm-start well from the corresponding fuel-objective
grid (a converged Fig 5 cell is a good initial guess for the same
Fig 6 cell); use that if it helps the boundary cells, but a cold
multistart is the baseline.

## Anchors

The paper does not tabulate Fig 6 cells the way Table 4 does for Fig 5.
Sanity-check instead by comparison: at a given cell, the min-DOC design
should never burn less fuel than the min-fuel design, and at low battery
specific energy (where electrification is expensive) the two figures
should look similar; they diverge most at high specific energy. If the
two figures look identical everywhere, something is wrong with the
objective wiring.

## How to work

Same as the Fig 5 prompt: lean on the study layer (`docs/STUDIES.md`,
`omd-cli-guide`, `design-study-workflow`) rather than a bespoke driver;
review and pilot before the full run; render the trade grid with
`omd-cli study plot <study_id>` (the OCP provider produces the same
four-panel layout for a cost-objective study, with DOC read straight
from the recorded `doc_per_nmi` output). Ask if the grid resolution,
file locations, compute budget, or base-plan choice are unclear.
