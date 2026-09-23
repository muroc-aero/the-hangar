# Paper results harness

Collects everything the paper reports -- the three-lane parity table, the
sandboxed local-model eval table, and the paper-reproduction figures -- and
makes each piece re-runnable from scratch. All commands run from the repo
root.

This file is the map of what exists and where it comes from. The step-by-step
runbook for regenerating the two tables is `paper/tables/README.md` -- start
there if you just want current numbers.

## Where this stands (2026-09-23)

What is current, what is stale, and what is unfinished. Update this section
when you change the answer -- it is the first thing to read when picking the
work back up.

**Current.** Lanes A, B and C (scripted) were re-run on 2026-09-20 at git
`ae3227b` (`paper/results/lane_parity_meta.json`): 31 comparisons, pytest
exit 0, every relative difference 0. The table now carries the five Aviary
cases (`avy_single_aisle`, `avy_bwb`, `avy_oas_wing`, `oas_avy_wing_mass`,
and `avy_three_tool` -- Aviary + OAS + pyCycle, the three-tool demo) and no
`ocp_three_tool` row: that case was deactivated the same day (skip marks in
both parity suites; on the numpy-2 stack its Lane A takes ~97 min and its
fuel burn moved from 2449.70 to 2855.08 kg) and comes back with PR #88
(`fix/ocp-three-tool-convergence`).

**Current, too.** The Lane C (agent) column and every row of
`sandboxed_evals` come from the `claude-opus-5` anchor arm run 2026-09-20
(hangar-evals campaigns `anchor_20260920T134338Z` + the resume
`anchor_20260920T200044Z`): 13 cases x 3 seeds, sandboxed, 38 of 39 graded
seeds pass, `Lost` and `Review` 0. This is the first arm on the numpy-2
stack, the first with the #107/#108 prompts and hangar-evals #24 budgets,
and the first with the Aviary cases: `avy_single_aisle` and
`avy_three_tool` (Aviary + OAS + pyCycle, the three-tool row) both 3/3,
every metric matching Lane A to the printed digits, so the three-tool
demo now has an agent column. The one failure -- `oas_aerostruct_rect`
seed 2, CD 0.0209 vs 0.0359, exactly the CD0 term the agent left out of
the surface -- is genuine and the agent's own report agreed. The
`oas_aero_rect` seed that failed on 09-11 passed this time. Two
`avy_three_tool` seeds were first lost to the plan's five-hour usage
limit and re-run after the reset; `--force` re-ran the 11 old cells.

Two operational notes from that run. The Mac slept for ~50 min during
`paraboloid` seed 2; the runner and the CLI both measure with monotonic
clocks, which stop during sleep, so the seed recorded 880 s and the
1100 s cap never fired. Run arms under `caffeinate -i -w <runner pid>`
(or keep the machine awake). And a rate-limit rejection mid-case shows up
as `Lost` seeds with a `rate_limit_event` in the harness stdout tail; the
plain `scripts/evals run anchor` (no `--force`) resumes exactly those.

**Current, three.** The `gemma4:26b-mlx` rows of `sandboxed_evals` come
from the local arm run 2026-09-21/22 (hangar-evals campaign
`gemma_20260921T200043Z`, `scripts/evals run gemma --force`): 13 cases x
5 seeds, OpenCode 1.17.5 in the sandbox container, omd over http, 7 h 49 min
on-device, against pushed integration branches
`integration/gemma-surface-20260921` in both repos (the-hangar `d91a3cb` =
PR #115 + #116; hangar-evals `9f7c9e9` = PR #27 + #28). **13 of 65 graded
seeds pass; `Lost` and `Review` 0.** Per cell: paraboloid 4/5,
ocp_hybrid_twin 3/5, ocp_caravan_full 2/5, oas_aero_rect / ocp_caravan_basic
/ ocp_oas_coupled / evt_native_sizing 1/5, the other six 0/5. Every seed
now opens by reading the reference and picks a real component type; the
remaining failures are (a) the model ending its turn mid-authoring with no
report (ocp_oas_direct median 4 turns, pyc_turbojet 11), (b) three omd
ergonomics gaps below, and (c) wrong numbers from a wrong setup
(oas_aero_rect seed 2, CL 0.376 vs 0.452).

The same arm run earlier that day WITHOUT the surface fixes
(`gemma_20260921T064421Z`, 8 h 19 min) scored **0 of 65**: every seed
invented component types (`VortexLatticeWing`,
`aerodynamic_analysis_component`), `plan_add_component` accepted them, and
the model looped or stopped. That arm is history, not in the table.

**Why gemma scored 0 before.** The anchor's first calls on every case read
`omd://reference` and `omd://plan-schema`, prompted by omd's MCP
`instructions`. OpenCode 1.17.5 forwards neither (verified in the binary):
a local model sees omd's tools and nothing else. Two fixes, both in the arm
above: hangar-evals #28 writes omd's instructions and the two resources
into the OpenCode workspace as `AGENTS.md` + files before every run;
the-hangar #116 makes every unknown-type error list the registered types
and rejects unknown types at `plan_add_component`. 0/65 -> 13/65 is what
those two changes bought; the anchor is unaffected by either.

**Current, four.** The `qwen3.6:35b-mlx` rows come from the local arm run
2026-09-22/23 (hangar-evals campaign `qwen_20260922T210813Z`,
`scripts/evals run qwen --force --only <12 cases>`, 23:08-06:35 CEST, 7 h
27 min; the `paraboloid` cell is from the same day's first launch
`qwen_20260922T072426Z`, stopped after that cell), against the pushed
integration branches (the-hangar `8ba69b2` = #115 + both #116 commits;
hangar-evals `4e4ce35` = #27 + #28). This is the first local arm with all
three omd gaps of item 3 below fixed, so the gemma rows above (at `d91a3cb`,
before the second #116 commit) and the qwen rows are NOT on the same omd.
**32 of 65 graded seeds pass; `Lost` 0, `Review` 1.** Per cell:
oas_aero_rect / ocp_caravan_full / evt_native_sizing 5/5, ocp_caravan_basic
/ avy_single_aisle 4/5, paraboloid / ocp_oas_coupled 3/5, ocp_hybrid_twin
2/5, oas_ocp_combined 1/5, oas_aerostruct_rect / ocp_oas_direct /
pyc_turbojet / avy_three_tool 0/5. Passing seeds match Lane A to the printed
digits (avy_single_aisle gross mass 116423 lbm, fuel 13814, range 1906 nmi).
The `Review` seed is avy_single_aisle seed 0: all four metrics match but the
agent's own report says it failed; it stays flagged for `evals review`.

The 33 failures sort into five kinds, by reading each seed's OpenCode event
stream and the Ollama request log:

- **Ended its turn mid-authoring** (the same stop gemma showed): the model
  writes "Let me now add more requirements and try to validate:" and the
  step finishes with reason `stop`, no tool call, no report. Most `NO RUN`
  seeds with 6-25 turns (every avy_three_tool seed after s0, pyc_turbojet
  s1-s3, oas_aerostruct_rect s1/s4, ocp_hybrid_twin s1, ocp_caravan_basic
  s3, avy_single_aisle s2).
- **Thinking exhausted the output budget:** one step emits 32 000 output
  tokens of reasoning, OpenCode ends the step with reason `length`, and the
  session ends with no tool call (oas_aerostruct_rect s0, ocp_oas_coupled
  s2, ocp_oas_direct s1/s4; 2-4 turns, 22-37k output tokens). Two more
  seeds spent the 1100 s cap the same way but had already produced the
  right numbers (oas_aero_rect s2, evt_native_sizing s4: graded PASS).
- **Wrong numbers from a wrong setup:** a run happened and the report named
  it, but the effects differ (ocp_hybrid_twin s0/s3, ocp_oas_direct
  s2/s3, oas_aerostruct_rect s3).
- **Three silent timeouts, first read as Ollama hangs:** oas_ocp_combined
  s0, pyc_turbojet s4 and avy_three_tool s0 hit the cap (1100 s, 1100 s,
  2700 s) with no completed model request for the last 11, 16 and 43 min
  and omd idle. They were marked as harness losses (an MLX runner hang
  past 30 GiB), Ollama was upgraded to 0.34.3, and the resume on 09-23
  19:17 reproduced the whole signature on the first seed at 25 GiB --
  `ollama ps` `Stopping...`, runner at ~70% CPU, an empty reasoning part,
  nothing in the access log -- with the GPU at 95-99%, then ended it on
  its own after 570 s: `step_finish reason=length`, 32 000 output tokens,
  no tool call. It is the "thinking exhausted the output budget" kind
  above, silent until it ends (`Stopping...` is the keep-alive expiring
  under the in-flight request); at ~56 tok/s a 32k step takes ~10 min, and
  the 0.30.10 seeds, slower under the leak, ran into their caps first.
  Model failures, so the marks were undone (hangar-evals `92ccbb6`,
  `mark-lost --undo`), the re-run was stopped after that one seed (it
  would have been a re-roll), and the three rows are the arm's timed-out
  FAILs. The one seed that did re-run also failed (`NO RUN`, 621 s); its
  row is in the file, superseded.
- **One omd path-resolution defect** (pyc_turbojet s0, item 5): the agent
  called `assemble_plan(output="turbojet_sizing/plan.yaml")`, which wrote
  next to the server's cwd instead of the workspace, and `validate_plan` /
  `read_plan` then resolved that cwd copy first, so the agent's three
  `write_plan` rewrites (which removed the offending `shared_vars`) were
  never the file being validated. It rewrote, validated, and got the same
  error three times, then gave up.

Operational notes from this arm, all in hangar-evals' README and
`eval-arm-sleep-and-rate-limits`: (a) Ollama 0.30.10's MLX runner grows
~0.5 GiB per request and never shrinks (20 -> 36 GB inside one seed, swap
full); the driver now unloads the model after every seed (`keep_alive: 0`),
which is why a whole arm ran without the one-turn seeds the first launch
showed. (b) `caffeinate -i` does not stop lid-closed / Deep Idle sleep: a
first relaunch (`qwen_20260922T090900Z`, not in the table) ran 7 h in
15-minute DarkWake slivers, seeds recorded minutes while taking hours, and
was stopped; this arm waited for a full `Wake` in `pmset -g log` and ran
under `caffeinate -i -s -w <runner pid>` with a pmset watch (no sleep
transition in 7.5 h). (c) The local `qwen3.6:35b-mlx` tag has
`PARAMETER num_ctx 131072` baked in (digest `ef9ec5d0a73a`); the plist
`OLLAMA_CONTEXT_LENGTH` was not being applied.

**Unfinished:**

1. **The gemma rows predate the second #116 commit** (`8534f55`: typed
   plan-directory / OAS-surface errors, `avy/Sizing` in the reference), the
   qwen rows include it. Re-run gemma (`scripts/evals run gemma --force`,
   ~8 h) on the same SHAs as the qwen arm before putting the two local rows
   side by side.
2. **The anchor image pins Claude Code 2.1.212** while the host CLI is
   2.1.270. The anchor arm ran on 2.1.212; bump `containers/build.sh` and
   `ANCHOR_IMAGE` before the next arm if it should be on the current CLI.
3. **Three omd ergonomics gaps the gemma arm hit, none fixed before it
   ran:** (a) `run_plan` / `validate_plan` given a plan *directory* raise a
   bare `[Errno 21] Is a directory` instead of a typed error naming
   `plan.yaml` (the most common way a seed was lost); (b) the OAS factory
   raises bare `KeyError('num_y')` / `'name'` when mesh keys sit at the
   component top level with `surfaces: [{id}]` (every oas_aerostruct_rect
   and oas_ocp_combined seed, up to 40 retries); (c) `omd://reference`'s
   component-type table lacks `avy/Sizing`, the one registered type
   missing, so 4 of 5 avy_single_aisle seeds chose `ocp/FullMission` with
   the b738 template as a "proxy". All three are fixed in the-hangar #116
   (second commit, `8534f55`: typed errors + `avy/Sizing` in the reference
   with a coverage test); the qwen arm above is the first with them, and
   none of its 33 failures is one of these three.
4. **No qwen seed is a harness loss.** The three silent timeouts were
   re-read on 09-23 (failure list above) and are model failures; the
   `HarnessLoss` marks are undone and the cell numbers above stand as the
   arm recorded them. What the episode left behind: hangar-evals (PR #28)
   copies the container's OpenCode store and process list out on a
   timeout, writes a timeout note that says to check the GPU before
   calling a silent seed a hang, and has `evals mark-lost` / `--undo` for
   the day a seed really is lost. Ollama is now 0.34.3 (MLX 0.32.1); the
   next local arm records that in its manifest.
5. **omd resolves relative plan paths against the server cwd before the
   workspace, and `assemble_plan`'s `output` only against the cwd**
   (`tools/_helpers.py resolve_plan_path`, `tools/execution.py
   assemble_plan`); `write_plan` writes only into the workspace. On the http
   transport the two differ, and pyc_turbojet seed 0 lost its cell to it.
   Fix: workspace first for reads, `workspace_write_target` for the
   assemble output; and the "Plan path not found" message should stop
   listing absolute host paths (seed 1 spent six turns running `find`
   over `/Users` inside the sandbox because of them).

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
rather than a value from some other run -- today `avy_bwb`, `avy_oas_wing`
and `oas_avy_wing_mass`, which have no Lane C and are not in the manifest. The legacy
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
op run --env-file=op.env -- scripts/evals run anchor   # 13 cases x 3 seeds, ~4 h
scripts/evals run gemma                                # on-device, ~8.5 h, free
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
