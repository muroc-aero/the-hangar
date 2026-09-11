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
- **No cell with `Ambig > 0` is being read as a clean fail.** The oracle grades
  the last successful run of the matching mode, and several Lane C prompts ask
  for a comparison run, so an agent that obeys can leave a control run last. The
  score then turns on run order. `Rep-dis > 0` means the agent's own verdict
  contradicts the effect grade — in the 2026-09-10 anchor arm every such seed
  reported the Lane A value exactly. See `ocp_caravan_full`.

## Single cases, by hand

For finer control than an arm, the per-case configs still drive the runner
directly:

```bash
cd ../hangar-evals
uv run --project ../the-hangar --with-editable ".[anchor]" \
    python -m hangar.evals.run --config configs/lane_c_anchor/paraboloid.json
```
