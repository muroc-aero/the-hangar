# Reproducing the tables

Every number in `lane_parity.*` and `sandboxed_evals.*`. Background on what each
lane means is in `paper/README.md`; this file is the runbook only.

## Prerequisites (once)

```bash
bash scripts/dev-setup.sh          # pinned upstreams + all packages
colima start                       # container runtime for the sandboxed arms
```

The sandboxed anchor authenticates with a Claude Code subscription token
(`claude setup-token`) stored in 1Password as the `claude-code` item's `token`
field. `op run` resolves it once and scopes it to that process tree — never
export it into your shell.

## Everything, in one command

From the sibling `hangar-evals` checkout:

```bash
cd ../hangar-evals
op run --env-file=op.env -- scripts/evals run paper
```

That runs the lane-parity suites, the Lane C agent column, the anchor arm, and
the gemma arm; prints every seed as it lands; and re-renders
`paper/tables/{lane_parity,sandboxed_evals}.{csv,md,tex}` when it finishes. One
unlock covers the whole run. Budget ~20 h for a cold start — but it skips
anything already graded, so in practice it runs only what is missing.

Check what it would do first:

```bash
scripts/evals run paper --dry-run   # preflight + per-case plan + time estimate
```

## One arm at a time

```bash
op run --env-file=op.env -- scripts/evals run anchor   # 11 cases x 3 seeds, ~5 h
scripts/evals run gemma                                # on-device, ~14 h, free
scripts/evals run anchor --only ocp_caravan_full,paraboloid
```

Re-running the same command continues rather than restarts: cases that are
**graded** are skipped, and cases carrying **error rows** resume on just those
seeds. A graded FAIL is a result and stays put; an error row is an absence and
comes back. `--force` re-runs a graded case anyway.

The anchor re-probes auth between cases and halts cleanly if the plan's usage
window closes, leaving the remaining cases untouched — re-run to pick up.

## Without running anything

```bash
scripts/evals status    # the table from stored results
scripts/evals table     # regrade + re-render the paper tables
```

`table` is the one to reach for after an interrupted run, or when only the
rendering changed.

## Reading the output

Each run leaves `results/campaigns/<arm>_<stamp>/` with `table.md` (rewritten
after every case, so it is current mid-run), `manifest.json` (what ran, at which
SHA, with what outcome), and `campaign.log`.

Before using the rendered tables:

- `lane_parity.md`'s header comment: pytest exit 0, and a git SHA matching the
  code the numbers should describe.
- Every case you expect is present — a missing arm is an absent row, not an error.
- **`Lost` is 0 everywhere.** A lost seed is one the harness never measured — it
  crashed, or its credential or network went. That is not a result, and the fix
  is to repair the cause and run the case again, never to footnote it. A table
  with a nonzero `Lost` is not finished.
- **`Review` is 0, or you have looked at each one.** These are seeds whose
  agent-reported verdict contradicts the effect grade. No rule can settle that,
  so a person opens the artifacts:

```bash
cd ../hangar-evals && scripts/evals review
```

  It prints each flagged seed, which metrics diverged, and the paths to that
  seed's provenance DB and agent transcript.

  One cause of this flag has been removed rather than reviewed. Every `Review`
  on the 2026-09-11 anchor arm turned out to be the grader's fault: the agent
  reported the right answer, then kept working, and the policy graded whichever
  run happened to be last. Since 2026-09-12 the graded run is the one the agent
  names in its report, so a `Review` now means what it says — the agent's claim
  and its own runs disagree.

`Passed` and `Failed` are results about the agent and need no caveat: a graded
FAIL means the agent did the work and got it wrong, and re-running it would just
be sampling until the answer flatters.

## Harness health

`scripts/evals run` ends with a `harness health` section when the measurement
itself misbehaved — seeds scored on whichever same-mode run happened to execute
last, or seeds that graded but whose harness exited abnormally. These never
change a verdict and are deliberately kept out of the table: they are defects to
fix, not caveats to carry. The end state is a `--force` re-run that reports none
of them.

## Single cases, by hand

For finer control than an arm, the per-case configs still drive the runner
directly:

```bash
cd ../hangar-evals
uv run --project ../the-hangar --with-editable ".[anchor]" \
    python -m hangar.evals.run --config configs/lane_c_anchor/paraboloid.json
```
