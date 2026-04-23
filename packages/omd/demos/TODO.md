# Paper Reproduction Demos

Reproduce published MDAO results using the hangar toolchain and include
visual comparison against the paper's plots. Each demo follows the
`examples/lanes` structure (lane_a raw, lane_b omd plan, lane_c prompt)
and adds a `figures/` folder with regenerated plots next to the
paper's originals.

## Candidates (ordered by readiness)

### 1. Brelje 2018a -- King Air C90GT hybrid sweep (OpenConcept)
- **Status:** Figs 5 and 6 reproduced at 5x5 coarse grid (see
  `brelje_2018a/`).  End-to-end pipeline works: Lane A/B/C, sweep
  driver, cost-model flag in OCP factory, 2x2 contour plot, paper-vs-
  reproduced comparison PNG.  Three of four Fig 6 panels match the
  paper; MTOW panel diverges due to a simplified airframe-cost term
  (see `brelje_2018a/README.md` for details).  Full 21x12 grid is
  optional refinement.
- **Starting point:** `examples/ocp_hybrid_twin/lane_b/hybrid_mission/plan.yaml`
  (kingair template, `twin_series_hybrid`, full mission with BFL).
- **Artifacts:** `brelje_2018a/figures/comparison_fig{5,6}.png`.
- **PDF:** `Brelje2018a_OCPpareto.pdf`

### 2. Adler 2022a -- B737-800 Breguet vs. mission-integration delta
- **Status:** second-best. Three-tool coupling already works.
- **Starting point:** `examples/ocp_three_tool/` (B738 + OAS VLM drag +
  pyCycle HBTF, both surrogate and direct-coupled variants).
- **Headline result:** delta between closed-form Breguet range and
  numerically integrated mission fuel burn across the design space.
- **Gap:** add a Breguet-baseline lane (can reuse `b738` template
  constants), compute the delta across a sweep, and plot the
  comparison.
- **PDF:** `Adler2022a_OAS_and_OCP.pdf`

### 3. Fouda 2022 -- Five propulsion architectures on the King Air
- **Status:** extension of the Brelje demo.
- **Starting point:** `examples/ocp_hybrid_twin/` once the sweep
  harness is in place.
- **Headline result:** side-by-side comparison of `turboprop`,
  `twin_turboprop`, `series_hybrid`, `twin_series_hybrid`,
  `twin_turbofan` on the same mission.
- **Gap:** loop over the five OCP architectures, normalize outputs,
  stacked bar / radar plot.
- **PDF:** `Fouda2022_OCP_Arch_Compare_ICAS2022_0593_paper.pdf`

### 4. Hendricks 2019 -- N+3 geared turbofan cycle verification
- **Status:** partial. Needs a new archetype.
- **Starting point:** `examples/pyc_turbojet/` (wrong archetype) and
  the pyc/hbtf archetype used inside `ocp_three_tool`.
- **Headline result:** match NPSS reference deck at design point and
  across an off-design sweep (TSFC, Fn, OPR, T4).
- **Gap:** add a pyc/geared-fan archetype (or extend hbtf with gear
  ratio + LPC offload), build a standalone demo with design-point and
  off-design plans, plot delta vs. NPSS reference numbers extracted
  from the paper.
- **PDF:** `Hendricks2019_pyCycle_A_Tool_for_Efficient_Optimization_of_Gas_T.pdf`

### 5. Chauhan 2018b -- uCRM-9 tapered transport wingbox
- **Status:** needs new demo. No existing transport/uCRM example.
- **Starting point:** `examples/oas_aerostruct_rect/` (rect wing + tube
  FEM, wrong geometry but correct aerostruct flow).
- **Headline result:** tapered transport wing + wingbox sized for
  structural mass under aero loads; drag/lift distribution plots.
- **Gap:** build uCRM-9 planform (taper, sweep, dihedral), switch FEM
  to `wingbox` with appropriate material, reproduce span-wise lift
  and thickness plots.
- **PDF:** `Chauhan2018b_OAS_uCRM.pdf`

### 6. Gratz 2024 -- N3CC verification vs. GASP/FLOPS (Aviary)
- **Status:** blocked. No Aviary tool in the workspace.
- **Starting point:** none.
- **Gap:** scaffold `packages/aviary/` via the `/new-tool` skill
  (wrap Aviary's sizing/mission APIs, expose MCP + CLI), then build
  the demo.
- **PDF:** `Gratz2024_Aviary.pdf`

## Proposed folder layout per demo

```
demos/<paper-short-id>/
  README.md              # paper citation, headline claim, reproduction scope
  lane_a/                # raw toolchain script (optional)
  lane_b/                # omd plan(s)
  lane_c/                # agent prompt (optional)
  figures/
    paper/               # screenshots/crops from the PDF for comparison
    reproduced/          # plots regenerated from the run
  compare.py             # script that produces the side-by-side figures
```

## Order of work
1. Brelje 2018a -- establishes the reproduction+visualization pattern.
2. Adler 2022a -- second tool-composition demo, reuses three-tool
   scaffolding.
3. Fouda 2022 -- incremental extension of #1.
4. Hendricks 2019 -- new pyc archetype.
5. Chauhan 2018b -- new OAS geometry + wingbox story.
6. Gratz 2024 -- blocked on Aviary packaging.
