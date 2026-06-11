# Brelje 2018a Reproduction -- King Air Series-Hybrid MDO

Reproduces Figures 5 and 6 from:

> Brelje, B. J. and Martins, J. R. R. A., "Development of a Conceptual
> Design Model for Aircraft Electric Propulsion with Efficient
> Gradients," AIAA/IEEE Electric Aircraft Technologies Symposium
> (EATS), 2018.

Both figures are 2x2 contour grids over **design range (300-800 nmi)**
x **battery specific energy (250-800 Wh/kg)**.  Each grid cell is an
independent MDO run.  Fig 5 minimizes `fuel_burn + MTOW/100`; Fig 6
minimizes trip direct operating cost (DOC).

## Status

- **Grid:** 11x12 = 132 cells per figure (paper-correct axes)
- **Convergence:** fig5 132/132, fig6 132/132 -- **264/264 (100 %)**
- **Physics fidelity:** matches upstream `HybridTwinTestCase` published
  values to 1e-5 (see `validation/check_omd_physics.py`)
- **Numerical fidelity vs paper Table 4:** mixed_objective within
  <2 % at all three published reference cells; MTOW within 0.01-1.6 %.

| paper Table 4 cell | objective omd vs paper | MTOW omd vs paper |
|---|---|---|
| 500 nmi, 250 Wh/kg | 382.4 / 387.2 (1.24 %) | 8912.8 / 8913.3 (0.01 %) |
| 500 nmi, 500 Wh/kg | 292.9 / 287.1 (1.97 %) | 12564.6 / 12566.3 (0.01 %) |
| 500 nmi, 750 Wh/kg | 56.7 / 56.2 (0.85 %)   | 12505.4 / 12305.8 (1.60 %) |

The remaining differences (free DVs at higher spec_energy) sit on
flat objective ridges where multiple feasible designs share the same
cost; the optimizer picks different points on the same ridge
depending on initial conditions.

See `figures/comparison_fig{5,6}.png` for the full side-by-side render.

## Layout

```
packages/omd/demos/brelje_2018a/
  README.md                            <-- this file
  run_paper_grid.sh                    -- one-command full reproduction (~5-9 h)
  shared.py                            -- DV/constraint list (used by Lane A)

  pipeline/                            -- reproduction pipeline scripts
    sweep.py                           -- 11x12 grid driver
    retry_failed.py                    -- warm-start failed cells from neighbors
    retry_stuck_cells.py               -- multi-neighbor + bracket retry for stragglers
    plotting.py                        -- 2x2 contour or pcolormesh figure render
    compare.py                         -- paper vs reproduced PNG side-by-side

  validation/
    check_omd_physics.py               -- omd factory vs upstream HybridTwinTestCase

  lane_a/                              -- programmatic, single-cell
    hybrid_mdo.py

  lane_b/                              -- omd plan, single-cell
    fuel_mdo/plan.yaml                 -- Fig 5 plan
    cost_mdo/plan.yaml                 -- Fig 6 plan

  lane_c/                              -- agent-driven, single-cell
    hybrid_mdo.prompt.md               -- agent brief
    cells.yaml                         -- one-by-one comparison cells
    compare_to_lane_b.py               -- baseline / check harness

  figures/
    paper/fig{5,6}.png                 -- PDF crops (see paper/README.md)
    reproduced/fig{5,6}.png            -- contour render
    reproduced/fig{5,6}_paper.png      -- pcolormesh + contour-overlay render
    comparison_fig{5,6}.png            -- side-by-side paper vs reproduced

  results/
    fig{5,6}_grid.csv                  -- per-cell sweep results (11x12)
    paper_grid_<ts>.log                -- run log
    retry_stuck_<ts>.log               -- final retry log
```

## Reproduction

### One-shot full sweep (overnight)

```bash
bash packages/omd/demos/brelje_2018a/run_paper_grid.sh --multistart
# resume after a crash:
bash packages/omd/demos/brelje_2018a/run_paper_grid.sh --resume --multistart
```

Wall time on 2 workers / WSL: ~5 h single-shot, ~9 h with multistart.
Multistart runs each fig5 cell from both `low` and `high` DV brackets
and keeps the better optimum -- recommended.

### Study-layer spec (new)

`study/fig5_study.yaml` expresses the same Fig 5 grid (plus a manual
HybridTwinTestCase reference cell) through the study layer
(`docs/STUDIES.md`): matrix expansion, low/high multistart, checkpointed
incremental runs, and a spreadsheet case table replace the bespoke
`pipeline/sweep.py` mechanics.

```bash
omd-cli study review packages/omd/demos/brelje_2018a/study/fig5_study.yaml
omd-cli study run    packages/omd/demos/brelje_2018a/study/fig5_study.yaml --max-cases 4
omd-cli study results brelje-2018a-fig5
```

The CSV pipeline below remains the verified full-reproduction path until
the study layer grows the retry heuristics and fig6 warm-from (see the
deferred list in `docs/STUDIES.md`).

### Modular steps

The wrapper above just chains these:

```bash
DEMO=packages/omd/demos/brelje_2018a

# 1.  Fig 5 sweep (fuel + MTOW/100 objective)
uv run python $DEMO/pipeline/sweep.py \
    --objective fuel --grid 11x12 --workers 2 \
    --range-bounds 300,800 --energy-bounds 250,800 \
    --starts low,high

# 2.  Rescue any failed fig5 cells via nearest-neighbor warm starts
uv run python $DEMO/pipeline/retry_failed.py --objective fuel

# 2a. (optional) Multi-neighbor + cold-bracket retry for cells that
#     the simple retry can't fix -- one cell at a time
uv run python $DEMO/pipeline/retry_stuck_cells.py \
    --objective fuel --cells 700,450 750,550 --k-neighbors 6

# 3.  Fig 6 sweep (DOC objective), warm-started from the fuel grid
uv run python $DEMO/pipeline/sweep.py \
    --objective cost --grid 11x12 --workers 2 \
    --range-bounds 300,800 --energy-bounds 250,800 \
    --warm-from $DEMO/results/fig5_grid.csv

# 4.  Plots (each figure in two styles)
uv run python $DEMO/pipeline/plotting.py --figure 5 --style contour
uv run python $DEMO/pipeline/plotting.py --figure 5 --style paper
uv run python $DEMO/pipeline/plotting.py --figure 6 --style contour
uv run python $DEMO/pipeline/plotting.py --figure 6 --style paper

# 5.  Side-by-side comparison vs paper crops
uv run python $DEMO/pipeline/compare.py --figure 5
uv run python $DEMO/pipeline/compare.py --figure 6
```

### Single-cell reproduction (Lane A, B)

```bash
DEMO=packages/omd/demos/brelje_2018a

# Lane A -- programmatic; fast iteration
uv run python $DEMO/lane_a/hybrid_mdo.py \
    --range 500 --spec-energy 450 --objective fuel

# Lane B -- omd plan; canonical
uv run omd-cli run $DEMO/lane_b/fuel_mdo/plan.yaml --mode optimize
uv run omd-cli run $DEMO/lane_b/cost_mdo/plan.yaml --mode optimize
```

### Single-cell reproduction (Lane C, agent-driven)

Lane C is the agent path: the model is briefed with the prompt and
must produce a plan that converges to the expected values.

```bash
DEMO=packages/omd/demos/brelje_2018a

# 1. Pick a cell from cells.yaml and print its expected values
uv run python $DEMO/lane_c/compare_to_lane_b.py \
    --cell paper-fuel-500-250 --mode baseline

# 2. Brief the agent with $DEMO/lane_c/hybrid_mdo.prompt.md +
#    the cell parameters from step 1.

# 3. After the agent run, dump its converged values to a JSON file
#    (mixed_objective, MTOW_lb, fuel_lb, W_battery_lb, Sref_ft2)
#    then check vs the expected:
uv run python $DEMO/lane_c/compare_to_lane_b.py \
    --cell paper-fuel-500-250 --mode check \
    --result lane_c_run.json
```

`cells.yaml` ships with three Brelje Table 4 reference cells (the
"hard" 250 Wh/kg cell, the mid-energy 500 cell, the all-electric 750
cell) plus three omd-sweep cells: an easy mid-grid cell, a hard
boundary cell ((700, 450) -- recovered by `retry_stuck_cells.py`),
and a cost-objective cell.

### Physics validation (no driver)

```bash
uv run python packages/omd/demos/brelje_2018a/validation/check_omd_physics.py
```

Builds the omd OCP factory at the upstream HybridTwinTestCase
operating point (500 nmi / 450 Wh/kg / cruise.hybridization=0.05841)
and asserts the 5 published outputs (climb.OEW, rotate.range_final,
engineoutclimb.gamma, descent.fuel_used_final,
descent.propmodel.batt1.SOC_final) match upstream to 1e-5 relative.

## Paper-specific overrides

The stock `kingair` template is the unhybridized C90GT.  The paper
modifies it for series-hybrid (HybridTwin.py:243-245); these go into
both Lane B plans as plan-level `initial_values`:

| variable | paper | template | effect |
|---|---|---|---|
| `analysis.cruise.acmodel.OEW.const.structural_fudge` | 2.0 | 1.6 | OEW ~25 % heavier |
| `ac|propulsion|propeller|diameter` | 2.2 m | 2.28 m | smaller prop |
| `ac|propulsion|engine|rating` (initial) | 1117.2 hp | 750 hp | starts SLSQP at the paper-sized engine |

Without these, omd's MDO converges in a different basin (~25 % lighter
aircraft, more electric optima).  The `validation/check_omd_physics.py`
script applies the same overrides at the model-evaluation level.

## Deploying to the landing page

The static case study lives at `deploy/landing/studies/brelje-2018a/`
and is git-tracked.  Binary artifacts (figures, N2 HTML, provenance
DAG) ship as a tarball.

On the dev machine, after a fresh sweep:

```bash
./deploy/scripts/package-case-study.sh brelje-2018a
# emits deploy/landing/studies/brelje-2018a.tar.gz
scp deploy/landing/studies/brelje-2018a.tar.gz <vps>:/tmp/
```

On the VPS:

```bash
cd /opt/the-hangar
git pull
./deploy/scripts/unpack-case-study.sh /tmp/brelje-2018a.tar.gz
# Caddy serves immediately; no restart
```

See `deploy/scripts/package-case-study.sh` and
`deploy/scripts/unpack-case-study.sh` for what's bundled and where it
gets unpacked.

## SDK hooks this added

- `packages/omd/src/hangar/omd/factories/ocp/builder.py` --
  `include_cost_model: bool` config flag on the OCP mission entry
  points.  Wires `cost_model` ExecComp at AnalysisGroup scope for
  hybrid architectures; exposes `doc_per_nmi` and `trip_doc_usd` as
  promoted outputs.
- `packages/omd/src/hangar/omd/plan_validate.py` -- `mixed_objective`,
  `doc_per_nmi`, `fuel_mileage` added to `_OCP_COMMON` so plans can
  reference them as objective names.
- `packages/omd/src/hangar/omd/materializer.py` +
  `plan_schema.py` -- plan-level initial-value overrides (per-DV
  `initial:` and top-level `initial_values:` list).  Materializer
  applies them after `prob.setup()`, overriding factory defaults.
  Enables the paper-specific overrides above without touching factory
  code.
