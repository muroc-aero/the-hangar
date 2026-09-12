# Paper results harness

Collects everything the paper reports -- the three-lane parity table, the
sandboxed local-model eval table, and the paper-reproduction figures -- and
makes each piece re-runnable from scratch. All commands run from the repo
root.

This file is the map of what exists and where it comes from. The step-by-step
runbook for regenerating the two tables is `paper/tables/README.md` -- start
there if you just want current numbers.

## Where this stands (2026-09-12)

What is current, what is stale, and what is unfinished. Update this section
when you change the answer -- it is the first thing to read when picking the
work back up.

**Current.** The Lane C (agent) column and every row of `sandboxed_evals`
come from the `claude-opus-5` anchor arm run 2026-09-10/11 and re-scored
offline on 09-12 under the named-run grading policy. 32 of 33 seeds pass.
The one failure -- `oas_aero_rect` seed 0, CD off by 2.7 % -- is genuine, and
the agent's own report agreed it had failed. `Lost` and `Review` are 0.

**Stale.** Lanes A, B and C (scripted) are from 2026-07-17 at git `ac32a6f`
(`paper/results/lane_parity_meta.json`), 26 comparisons, pytest exit 0. They
are a `paper/run_lanes.py` away from current, but that refresh waits on a
decision about PR #88 (`fix/ocp-three-tool-convergence`), which changes the
B738 row. Deciding #88 first avoids rendering the table twice.

**Unfinished:**

1. **`ocp_three_tool` is not in the anchor manifest.** `configs/lane_c_anchor/`
   holds 11 cases and that is not one of them, so its agent cells read `--`.
   Adding it to the arm is the fix -- not back-filling from the retired
   `eval_lane_c.py` harness, which would give that one column a second
   provenance. Budget a Lane A reference run first.
2. **The local arms predate the current policy.** The newest gemma records are
   2026-08-11 and the newest qwen ones 2026-06/07, so both were graded under
   last-run-of-mode and ran on the pre-calibration budgets. They are in the
   table for reference but are **not comparable with the anchor** until
   re-run (gemma ~14 h, qwen ~9 h, both on-device and free).
3. **The prompt and budget changes have never been exercised by a fresh run.**
   the-hangar #107/#108 and hangar-evals #24 landed after the arm was measured,
   and the 09-12 work re-*scored* the stored arm rather than re-running it.
   The next anchor arm is the first real test of them.

## What gets produced

```
paper/
  results/
    lane_parity.jsonl        # raw lane comparisons (run_lanes.py)
    lane_parity_meta.json    # timestamp, git sha, pytest exit code
    lane_c_agent.json        # legacy single-seed agent runs (eval_lane_c.py);
                             #   no longer read by make_tables.py
  (../hangar-evals/results/)
    regraded/                # per-cell summaries + outcome counts
    campaigns/<arm>_<stamp>/ # per-run table.md, manifest.json, campaign.log
  tables/
    lane_parity.{csv,md,tex}      # Lane A vs B vs C per example/metric
    sandboxed_evals.{csv,md,tex}  # hangar-evals model x harness summary
                                  #   .csv/.md keep the slugs; .tex is a
                                  #   paste-ready table* float using the
                                  #   paper's names (see tables/README.md)
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
| C (agent) | a blind Claude agent, omd MCP tools only | the sandboxed arm's records (below) |
| C (sandboxed) | local models x OpenCode/OpenHands harnesses | sibling `hangar-evals` repo |

The last two rows are two readings of the **same runs**, not two sets of runs:

- `lane_parity.md`'s **Lane C (agent)** column answers *does the agent's lane
  reproduce Lane A* -- one number per metric, the worst seed of the arm, so it
  bounds agreement rather than flattering it.
- `sandboxed_evals.md` answers *how reliably* -- pass rate across seeds, turns,
  wall clock, seeds lost, seeds needing review.

The values are effect-graded: what the agent's graded run actually produced,
read from its omd provenance DB, not the numbers it reported for itself.

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

### 2. Live-agent Lane C column

Nothing to run: it comes from the sandboxed arm (recipe 3), so one agent run
fills both tables.

```bash
uv run python paper/make_tables.py --agent-model claude-opus-5   # the default
```

The arm is the column's only source. A case the arm has not run shows `--`
rather than a value from some other run -- today that is `ocp_three_tool`
alone, which needs adding to the anchor manifest. The legacy
`eval_lane_c.py` harness still runs a single blind case if you want one, but
`make_tables.py` no longer reads its output.

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
(the runner does, and it is now the default): the regraded summaries add
`Lost` -- seeds the harness never measured, which are not failures and
mean the arm needs re-running -- and `Review`, seeds whose reported
verdict contradicts the grade and need a human look (`evals review`).
`make_tables.py` keeps the latest summary per (case, harness, model), so
arms accumulate across runs and retired model generations stay in for
comparison.

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
