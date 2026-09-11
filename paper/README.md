# Paper results harness

Collects everything the paper reports -- the three-lane parity table, the
sandboxed local-model eval table, and the paper-reproduction figures -- and
makes each piece re-runnable from scratch. All commands run from the repo
root.

This file is the map of what exists and where it comes from. The step-by-step
runbook for regenerating the two tables is `paper/tables/README.md` -- start
there if you just want current numbers.

## What gets produced

```
paper/
  results/
    lane_parity.jsonl        # raw lane comparisons (run_lanes.py)
    lane_parity_meta.json    # timestamp, git sha, pytest exit code
    lane_c_agent.json        # optional: live-agent Lane C runs (eval_lane_c.py)
  (../hangar-evals/results/)
    regraded/                # per-cell summaries + the ambiguity counts
    campaigns/<arm>_<stamp>/ # per-run table.md, manifest.json, campaign.log
  tables/
    lane_parity.{csv,md,tex}      # Lane A vs B vs C per example/metric
    sandboxed_evals.{csv,md,tex}  # hangar-evals model x harness summary
  figures/
    brelje_2018a/            # paper-vs-reproduced Figs 5 & 6
    adler_2022a/             # only via --only adler / --all (unverified)
    abu_scitech_2026/        # only via --only abu / --all (unverified)
```

## Lanes

| Lane | What runs | Where it comes from |
|------|-----------|---------------------|
| A | direct OpenMDAO/OAS/OCP/pyCycle/evt scripts | `packages/omd/examples/*/lane_a/` |
| B | omd plan YAML through the omd pipeline | `packages/omd/examples/*/lane_b/` |
| C (scripted) | the omd MCP tool surface, driven in process | `packages/omd/examples/tests/test_parity_lane_c.py` |
| C (agent) | a blind Claude agent, omd MCP tools only | `packages/omd/examples/agent_eval/eval_lane_c.py` |
| C (sandboxed) | local models x OpenCode/OpenHands harnesses | sibling `hangar-evals` repo |

## Recipes

### 1. Lane parity table (A vs B vs scripted C)

```bash
uv run python paper/run_lanes.py            # full suite (slow tests included)
uv run python paper/run_lanes.py --quick    # paraboloid-only smoke (~1 min)
uv run python paper/make_tables.py
```

`run_lanes.py` re-runs the existing pytest parity suites with a JSONL
recording hook (`PARITY_RESULTS_JSONL`) -- the tests remain the single
source of truth for how each lane executes and what tolerance counts as
a pass. A nonzero pytest exit is recorded in `lane_parity_meta.json` and
stamped into the table comment.

One case is excluded by default: `ocp_pyc_coupled` deliberately has no
Lane B plan -- a faithful plan cannot reach parity with its Lane A
reference, and the example is documented as non-physical (see
`packages/omd/examples/ocp_pyc_coupled/TODO.md` for the analysis and
the recommended physical replacement). Run with `--include-known-gaps`
to include it anyway.

The scripted Lane C suite covers every table case (`ocp_pyc_coupled`
excepted, as above), so the "Lane C (scripted)" column is fully
populated by a full `run_lanes.py` sweep.

### 2. Live-agent Lane C column (optional, needs API credentials)

```bash
uv run --with claude-agent-sdk \
    packages/omd/examples/agent_eval/eval_lane_c.py all \
    --save-json paper/results/lane_c_agent.json
uv run python paper/make_tables.py          # agent columns appear automatically
```

Each agent case runs from the example's `lane_c/*_open.prompt.md`:
engineering goal and physical inputs only, no component types, config
keys, or tool-call sequence -- the agent must work the MCP surface out
for itself (see `packages/omd/examples/agent_eval/README.md`).

### 3. Sandboxed Lane C (hangar-evals)

The sandboxed eval table is built from `*_summary.json` files in the
sibling `hangar-evals` repo. One command runs an arm end to end and
re-renders these tables when it finishes:

```bash
cd ../hangar-evals
op run --env-file=op.env -- scripts/evals run anchor   # 11 cases x 3 seeds, ~5 h
scripts/evals run gemma                                # on-device, ~14 h, free
scripts/evals run anchor --dry-run                     # plan only, no spend
```

Re-running continues rather than restarts: graded cases are skipped and
cases carrying error rows resume on just those seeds. `scripts/evals table`
re-renders without running anything.

Pass `--evals-dir ../hangar-evals/results/regraded` to `make_tables.py`
(the runner does): the regraded summaries add `n_ambiguous` and
`n_report_disagrees`, the two counts that say whether a `Passed` cell can
be read at face value. `make_tables.py` keeps the latest summary per
(case, harness, model), so arms accumulate across runs and retired model
generations stay in for comparison.

### 4. Brelje 2018a Figs 5 & 6

Committed figures are collected by default; `--regenerate` re-renders
from the committed 11x12 grid CSVs (fast, no optimization re-run):

```bash
uv run python paper/make_figures.py --only brelje --regenerate
```

Full from-scratch reproduction (264 MDO cells, ~5-9 h):

```bash
bash packages/omd/demos/brelje_2018a/run_paper_grid.sh --multistart
uv run python paper/make_figures.py --only brelje --regenerate
```

Fidelity anchors are in `packages/omd/demos/brelje_2018a/README.md`
(Table 4 cells within <2 % objective, physics vs upstream to 1e-5).

### 5. Other reproductions (not collected by default)

The adler/abu figure sources are excluded from the default
`make_figures.py` run until their match against the source papers is
verified; opt in with `--only adler`, `--only abu`, or `--all`.

- **AIAA SciTech 2026 eVTOL case study** (`packages/evt/examples/abu_scitech_2026`
  + omd study wrapper in `packages/omd/demos/abu_scitech_2026`): the
  18-case numeric grid reproduces the golden values exactly
  (`compare_to_golden.py`), but the committed figures still need review
  before going in the paper.
- **Adler 2022a** (`packages/omd/demos/adler_2022a`): comparison figures
  for figs 7, 9-13 are committed on main but not yet verified against
  the paper; the generating pipeline lives on the `adler-2022a-demo`
  branch (stalled).
- **Fouda 2022** (five propulsion architectures on the King Air): best
  candidate for the next new reproduction -- pure extension of the
  working Brelje/OCP infrastructure, no new tool development. See
  `packages/omd/demos/TODO.md`.

### Everything at once

The tables, including the sandboxed arms, are one command from the sibling
checkout -- it runs the lane suites, the agent column, and every arm, then
re-renders `paper/tables/`:

```bash
cd ../hangar-evals && op run --env-file=op.env -- scripts/evals run paper
```

Figures are separate (they have no eval arm):

```bash
uv run python paper/make_figures.py --regenerate
```

Tables only, from results that already exist -- no runs, no spend:

```bash
cd ../hangar-evals && scripts/evals table
```
