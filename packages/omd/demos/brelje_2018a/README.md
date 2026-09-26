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

- **Grid:** the omd sweep (`results/fig{5,6}_grid.csv`) is 11x12 = 132
  cells per figure. The paper's own grid is **21x12** (25 nmi range
  steps; read off the pcolormesh cell edges in the figure crops); the
  upstream truth lane and the digitized paper both use it, and the 11x12
  cells are a subset.
- **Convergence -- corrected 2026-09-26.** The committed grids report
  264/264 converged, but re-scoring every design in the upstream model
  (`stats/rescore_sweep.py` -> `results/rescored/`) shows that only
  **125/132 fig5 and 0/132 fig6 cells solve the paper's problem**. The
  other 139 cells came from `pipeline/retry_failed.py` /
  `retry_stuck_cells.py`, which build through `lane_a/hybrid_mdo.py`.
  That file lacked the paper overrides (structural fudge 2.0, 2.2 m
  prop) until this date. So those cells optimized the stock C90GT: an
  MTOW margin of -2 to -956 lb and ~4070 ft BFL when evaluated with the
  paper airframe. Every fig6 cell has a `retry-warm-start` run_id. The
  lane A fix makes future retries correct; the fig6 grid needs a re-run
  (`run_paper_grid.sh`). `stats/collect_stats.py` counts these cells as
  not covered.
- **Physics fidelity:** matches upstream `HybridTwinTestCase` published
  values to 1e-5 (see `validation/check_omd_physics.py`)
- **MDO fidelity vs upstream:** the omd optimum equals OpenConcept's own
  HybridTwin MDO (`lane_a_upstream/`) to <1e-6 at the 500 nmi reference
  cells:

| 500 nmi cell | objective: omd grid = upstream truth | MTOW: truth / paper Fig 5 (digitized) |
|---|---|---|
| 250 Wh/kg | 387.20 kg | 8913 / 8914 lb |
| 450 Wh/kg | 324.89 kg | 12566 / 12574 lb |
| 500 Wh/kg | 287.08 kg | 12566 / 12574 lb |
| 750 Wh/kg | 56.24 kg  | 12306 / 12491 lb |

The paper has no numeric table for these cells: the figures are the
publication's only numbers. An earlier version of this README and
`lane_c/cells.yaml` quoted "paper Table 4" values (382.4 / 292.9 /
56.7 kg); they match neither the figures nor the upstream model and have
been replaced (see `cells.yaml`). The paper-vs-model comparison is now
per cell, over the whole grid: `stats/collect_stats.py`.

**The paper's "degree of hybridization (electric percent)" panel is the
battery share of motor electrical energy, not cruise hybridization.**
At 500 nmi the paper shows 3.5 / 45.1 / 52.4 / 99.5 % at 250 / 450 / 500 /
750 Wh/kg; the upstream energy fraction is 3.1 / 46.7 / 54.2 / 99.9 %,
while cruise hybridization is 0.1 / 50.6 / 59.2 / 99.9 %. The omd sweep
CSV and `pipeline/plotting.py` plot `100 x cruise_hybridization`, so
that panel is not the paper's quantity; the truth lane records both
(`electric_energy_frac`, `cruise_hybridization`).

See `figures/comparison_fig{5,6}.png` for the full side-by-side render.

## Reproduction statistics (paper vs truth vs scripted vs agent)

Three pieces turn "does it match the paper?" into numbers:

1. **Paper reference** -- `paper_ref/digitize_paper_figs.py` inverts each
   panel of the figure crops through its own colorbar into per-cell
   values (`paper_ref/fig{5,6}_paper_digitized.csv`, 21x12). Pcolormesh
   panels (MTOW, electric percent, Fig 5 DOC, Fig 6 fuel mileage) read
   back exactly up to colour quantisation; contourf panels (Fig 5 fuel
   mileage, Fig 6 DOC) read back as a band, and the band half-width is
   carried as the uncertainty.
2. **Truth lane (Lane A, upstream)** -- `lane_a_upstream/upstream_truth.py`
   runs the MDO on OpenConcept's own `HybridTwin` model and solver
   settings, with the DV / constraint block transcribed verbatim from
   `HybridTwin.py`. No hangar code is involved. It adds the paper's Sec. IV.D
   cost model as an output-only subsystem (upstream has none), and a
   multistart (the upstream start plus the `high` bracket). It also
   re-scores externally produced designs (`rescore_design`), which is
   how agent runs are graded.
   Fig 6 needs objective scaling the upstream script never had to
   choose. Unscaled, DOC/nmi (~0.7) stops SLSQP a few iterations in and
   no two starts agree; with `ref=0.01` all starts agree. At 500 nmi /
   450 Wh/kg the result is DOC 0.660, MTOW 8819 lb and 7.9 % electric,
   against the paper's ~0.663 / 8817 lb / 6.4 %. Fig 6 cells also start
   from the Fig 5 truth optimum. `polish` re-runs any cell where truth
   is infeasible or another source found a better optimum, warm-started
   from that design and the neighbours. Upstream's own optimum is always
   the one recorded.
3. **Statistics** -- `stats/collect_stats.py` joins paper, truth, the
   scripted omd sweep (`lane_b`), and any number of agent-driven runs,
   and reports per figure and metric: coverage, pass rate at tolerance,
   median / p90 / max relative error, signed bias, the objective's
   optimality gap vs truth (matched / worse / better optimum), and
   regime (fuel / hybrid / electric basin) agreement. Output is
   `results/stats/{summary.md,summary.json,per_cell.csv,err_fig{5,6}.png}`.

Agent-driven execution across the full case set is
`stats/agent_campaign.py`: one blind agent per cell (omd MCP tools only,
isolated data root) briefed with `lane_c/hybrid_mdo_cell_open.prompt.md`.
The agent's named run is read back from its analysis DB and re-scored in
the upstream model, so a cell is graded by what the design actually does
in the truth model, not by the agent's report. A full-figure agent study
(`study/fig{5,6}_study.prompt.md`) plugs into the same statistics
through its `cases.csv`.

```bash
DEMO=packages/omd/demos/brelje_2018a

# paper reference (seconds)
uv run python $DEMO/paper_ref/digitize_paper_figs.py --check

# truth: one cell, or the paper grid (resumable; ~1 start/min on 4 cores)
uv run python $DEMO/lane_a_upstream/upstream_truth.py cell --range 500 --spec-energy 450
uv run python $DEMO/lane_a_upstream/upstream_truth.py grid --objective fuel \
    --grid paper --subset demo --workers 4 --resume      # the 11x12 cells first
uv run python $DEMO/lane_a_upstream/upstream_truth.py grid --objective cost \
    --grid paper --workers 4 --resume
# polish: warm-start cells where truth is infeasible or another source
# (the omd sweep, a neighbour) reached a better optimum; upstream still
# owns the answer -- foreign designs are only starting points
uv run python $DEMO/lane_a_upstream/upstream_truth.py polish --objective fuel \
    --ref $DEMO/results/fig5_grid.csv

# agent campaign: one blind agent per cell, N seeds (needs claude-agent-sdk)
uv run python $DEMO/stats/agent_campaign.py run --arm opus --grid demo --dry-run
uv run --with claude-agent-sdk python $DEMO/stats/agent_campaign.py run \
    --arm opus --model <model> --seeds 3 --grid demo --workers 2
uv run python $DEMO/stats/agent_campaign.py status --arm opus
# grade a run made elsewhere (e.g. an interactive session) into an arm
uv run python $DEMO/stats/agent_campaign.py grade --arm session --figure 5 \
    --range 500 --spec-energy 450 --run-id <run_id>

# statistics over everything present
uv run python $DEMO/stats/collect_stats.py \
    --agent opus=$DEMO/results/agent_campaign/opus/seed0/fig5 \
    --agent study=hangar_data/studies/brelje-2018a-fig5
uv run python $DEMO/stats/agent_campaign.py collect opus     # all seeds of an arm
```

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

  lane_a/                              -- programmatic, single-cell (hangar OCP factory)
    hybrid_mdo.py

  lane_a_upstream/                     -- truth: OpenConcept HybridTwin, unmodified
    upstream_truth.py                  -- cell / grid / rescore

  paper_ref/                           -- the paper as numbers
    digitize_paper_figs.py             -- figure crops -> per-cell values
    fig{5,6}_paper_digitized.csv       -- 21x12, with band half-widths

  stats/                               -- reproduction statistics
    collect_stats.py                   -- paper vs truth vs lane_b vs agent arms
    agent_campaign.py                  -- one blind agent per cell, effect-graded

  lane_b/                              -- omd plan, single-cell
    fuel_mdo/plan.yaml                 -- Fig 5 plan
    cost_mdo/plan.yaml                 -- Fig 6 plan

  lane_c/                              -- agent-driven, single-cell
    hybrid_mdo.prompt.md               -- agent brief (500 nmi / 450 Wh/kg)
    hybrid_mdo_cell_open.prompt.md     -- open per-cell brief (agent_campaign.py)
    cells.yaml                         -- one-by-one comparison cells
    compare_to_lane_b.py               -- baseline / check harness

  study/                               -- study-layer specs + agent briefs
    fig5_study.yaml                    -- Fig 5 grid as a study (a worked outcome)
    fig5_study.prompt.md               -- agent brief: build+run the Fig 5 study
    fig6_study.prompt.md               -- agent brief: build+run the Fig 6 study

  figures/
    paper/fig{5,6}.png                 -- PDF crops (see paper/README.md)
    reproduced/fig{5,6}.png            -- contour render
    reproduced/fig{5,6}_paper.png      -- pcolormesh + contour-overlay render
    comparison_fig{5,6}.png            -- side-by-side paper vs reproduced

  results/
    fig{5,6}_grid.csv                  -- per-cell sweep results (11x12)
    lane_a_upstream/fig{5,6}_paper.csv -- upstream truth, best start per cell
    lane_a_upstream/fig{5,6}_paper_starts.csv -- every start (start sensitivity)
    stats/                             -- collect_stats.py output
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
omd-cli study plot   brelje-2018a-fig5        # 2x2 trade grid from cases.csv
```

`omd-cli study plot` renders the Fig 5/6 four-panel trade grid straight
from the study's `cases.csv` (non-converged cells left blank). It is the
study-layer equivalent of `pipeline/plotting.py`: the OCP plot provider
owns the derived panels (fuel mileage, electric percent, MTOW in lb, and
an offline DOC estimate for the min-fuel grid). Output lands in
`hangar_data/studies/brelje-2018a-fig5/plots/`.

The CSV pipeline below remains the verified full-reproduction path until
the study layer grows the retry heuristics and fig6 warm-from (see the
deferred list in `docs/STUDIES.md`).

#### Agent-driven study (Lane C, full figure)

`study/fig5_study.prompt.md` and `study/fig6_study.prompt.md` are agent
briefs: each describes the problem, the trade-space conditions, and the
acceptance anchors, and asks the agent to author and run the study
(and render the figure) itself. They are the multi-case counterpart to
`lane_c/hybrid_mdo.prompt.md` (single cell). The `fig5_study*.yaml`
specs in this directory are one correct outcome of the Fig 5 brief, not
inputs to it.

### Modular steps

The wrapper above just chains these. The `pipeline/` scripts import
pandas, which is not a workspace dependency; add `--with pandas` to
`uv run` if it is not installed.

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

`cells.yaml` ships with three 500 nmi reference cells whose expected
values come from the upstream truth lane (the "hard" 250 Wh/kg cell,
the mid-energy 500 cell, the all-electric 750 cell) plus three omd-sweep
cells: an easy mid-grid cell, a hard
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
