# Brelje 2018a Reproduction -- King Air Series-Hybrid MDO

Reproduces Figures 5 and 6 from:

> Brelje, B. J. and Martins, J. R. R. A., "Development of a Conceptual
> Design Model for Aircraft Electric Propulsion with Efficient Gradients,"
> AIAA/IEEE Electric Aircraft Technologies Symposium (EATS), 2018.

Both figures are 2x2 contour grids over design range (300-800 nmi) x
battery specific energy (300-800 Wh/kg). Each grid cell is an
independent MDO run.  Fig 5 minimizes `fuel_burn + MTOW/100`; Fig 6
minimizes trip direct operating cost (DOC).

## Current status

- [x] Stage 1: Lane A single-cell MDO (fuel) -- converged at (500 nmi,
      450 Wh/kg) with MTOW = 5700 kg (upper bound), fuel = 176 kg,
      cruise hybridization = 68.9%.
- [x] Stage 2: Lane B fuel MDO plan -- `aug_obj.mixed_objective`
      matches Lane A to 8 sig figs.
- [x] Stage 3: Sweep driver and Fig 5 5x5 coarse grid -- initial pass
      19/25 converged; `retry_failed.py` warm-starts each failure from
      its nearest converged neighbor (matches Brelje's recovery
      approach), pulling the grid to 25/25 (one cell accepted as
      feasible at SLSQP exit-mode 8 since all constraints are active
      at bounds).  See `figures/comparison_fig5.png`.
- [x] Stage 4: Cost model + Fig 6 -- OCP factory grew an
      `include_cost_model` flag (wires an inlined ExecComp with
      Brelje Section IV.D coefficients, including the engine-weight
      subtraction from airframe cost); Fig 6 5x5 grid produced
      25/25 converged.  The initial pass lands in a local minimum
      (MTOW ~4400 kg uniformly), so the final pass warm-starts each
      cell from the matching fuel-sweep optimum via
      `retry_failed.py --warm-from fig5_grid.csv` -- this recovers
      the paper's triangular MTOW pattern and drops DOC 3-6% at
      every affected cell.  See `figures/comparison_fig6.png`.
- [ ] Stage 5: Full 21x12 = 252-cell grid (optional refinement;
      estimated ~3 h wall time on 4 workers).
- [x] Stage 6: README, Lane C prompt, TODO.md update.

## Running

```bash
# Lane A single cell
uv run python packages/omd/demos/brelje_2018a/lane_a/hybrid_mdo.py \
    --range 500 --spec-energy 450 --objective fuel
uv run python packages/omd/demos/brelje_2018a/lane_a/hybrid_mdo.py \
    --range 500 --spec-energy 450 --objective cost

# Lane B
uv run omd-cli run packages/omd/demos/brelje_2018a/lane_b/fuel_mdo/plan.yaml --mode optimize
uv run omd-cli run packages/omd/demos/brelje_2018a/lane_b/cost_mdo/plan.yaml --mode optimize

# Fuel MDO (Fig 5): sweep, retry any failures, plot, comparison PNG
uv run python packages/omd/demos/brelje_2018a/sweep.py --objective fuel --grid 5x5 --workers 4
uv run python packages/omd/demos/brelje_2018a/retry_failed.py --objective fuel
uv run python packages/omd/demos/brelje_2018a/plotting.py --figure 5
uv run python packages/omd/demos/brelje_2018a/compare.py --figure 5

# Cost MDO (Fig 6): sweep, re-seed from fuel optimum (escapes local min), plot
uv run python packages/omd/demos/brelje_2018a/sweep.py --objective cost --grid 5x5 --workers 4
uv run python packages/omd/demos/brelje_2018a/retry_failed.py --objective cost \
    --warm-from packages/omd/demos/brelje_2018a/results/fig5_grid.csv
uv run python packages/omd/demos/brelje_2018a/plotting.py --figure 6
uv run python packages/omd/demos/brelje_2018a/compare.py --figure 6

# Full 21x12 grid (Stage 5; ~3 h)
uv run python packages/omd/demos/brelje_2018a/sweep.py --objective fuel --grid 21x12 --workers 4
uv run python packages/omd/demos/brelje_2018a/sweep.py --objective cost --grid 21x12 --workers 4
```

## What the pipeline does

- `shared.py` -- DV/constraint list copied from upstream
  `openconcept/examples/HybridTwin.py` lines 372-418.
- `lane_a/hybrid_mdo.py` -- programmatic MDO via
  `hangar.omd.factories.ocp.builder.build_ocp_full_mission` with
  `defer_setup=True`, then `add_design_var`/`add_constraint`/SLSQP.
- `lane_b/{fuel,cost}_mdo/plan.yaml` -- same MDO expressed as an omd
  plan.  Cost plan sets `include_cost_model: true` so the factory
  adds a trip-DOC ExecComp whose `doc_per_nmi` output is the
  objective.
- `sweep.py` -- patches a base plan per grid cell (new
  `mission_range_NM` and `battery_specific_energy`), runs via
  `hangar.omd.run.run_plan`, and appends converged outputs to
  `results/fig{5,6}_grid.csv`.  4-worker `multiprocessing.Pool` by
  default.
- `plotting.py` -- reads the CSV, pivots into 2D grids, and renders
  4-panel `contourf` figures matching the paper's axes and colorbar
  ranges.  When `doc_per_nmi` is absent (fuel-objective sweep didn't
  wire the cost model), DOC is post-computed from the same
  coefficients used in the factory, with OEW estimated as
  `MTOW - fuel - W_battery - payload`.
- `compare.py` -- pastes `figures/paper/fig{5,6}.png` next to
  `figures/reproduced/fig{5,6}.png` into `figures/comparison_fig{5,6}.png`.
- `figures/paper/README.md` documents the PDF crop procedure.

## Divergences from the paper

1.  **Grid resolution.**  The headline result uses 5x5 = 25 cells
    (~25 min wall time) rather than the paper's 21x12 = 252 cells.
    The coarser grid blurs the hybrid/electric boundary but preserves
    all qualitative trends.
2.  **Convergence rate.**  Paper reports 1/252 failures.  Our 5x5
    fuel sweep had 6/25 failures clustered at long range / low spec
    energy where hybrid is a marginal fit; the cost sweep had 0/25
    (the cost objective is more forgiving than fuel + MTOW/100).
    Better starting guesses per cell would likely close this gap.
3.  **Cost sweep warm-starts.**  The cost objective has competing
    local minima; the template-default starting point converges at
    MTOW ~4400 kg, while warm-starting from the fuel-optimized
    design for the same grid cell finds the true minimum at or near
    MTOW = 5700 kg.  The `sweep.py` output is therefore followed by
    `retry_failed.py --warm-from ...fig5_grid.csv` before plotting.
4.  **Battery energy model.**  We approximate
    `E_battery_used = 0.9 x W_battery x spec_energy`; upstream
    OpenConcept integrates actual battery draw over the trajectory.
    Both approaches use the $36/MWh coefficient.

## Files

```
packages/omd/demos/brelje_2018a/
  README.md                          <-- this file
  shared.py                          -- DV/constraint list
  sweep.py                           -- grid driver
  retry_failed.py                    -- warm-start failed cells from neighbors
  plotting.py                        -- 2x2 contourf grid
  compare.py                         -- paper vs reproduced PNG
  lane_a/hybrid_mdo.py               -- programmatic MDO
  lane_b/fuel_mdo/plan.yaml          -- Fig 5 plan
  lane_b/cost_mdo/plan.yaml          -- Fig 6 plan
  lane_c/hybrid_mdo.prompt.md        -- agent prompt
  figures/paper/fig{5,6}.png         -- PDF crops (see README there)
  figures/reproduced/fig{5,6}.png    -- omd output
  figures/comparison_fig{5,6}.png    -- side-by-side
  results/fig{5,6}_grid.csv          -- per-cell sweep results
```

## SDK hooks this added

- `packages/omd/src/hangar/omd/factories/ocp/builder.py` --
  `include_cost_model: bool` config flag on all three OCP mission
  entry points.  Wires `cost_model` ExecComp at AnalysisGroup scope
  for hybrid architectures; exposes `doc_per_nmi` and `trip_doc_usd`
  as promoted outputs.
- `packages/omd/src/hangar/omd/plan_validate.py` -- `mixed_objective`,
  `doc_per_nmi`, `fuel_mileage` added to `_OCP_COMMON` so plans can
  reference them as objective names without tripping the validator.
