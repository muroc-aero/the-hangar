# Lane C Agent Eval

Stage 2 of Lane C parity coverage. Stage 1
(`../tests/test_parity_lane_c.py`) scripts the MCP tool surface in
process; this harness runs the real thing: a blind agent driving a
live omd MCP server, scored against the Lane A reference scripts.

## What it does

For each case, the harness:

1. Computes the Lane A reference by running the example's
   `lane_a/<module>.run()` in its own subprocess (one process per
   example; the `shared.py` modules collide otherwise).
2. Launches an agent via the Claude Agent SDK with:
   - the Lane C task prompt (`<example>/lane_c/*.prompt.md`) wrapped in
     MCP-only rules and a required JSON report format,
   - only the omd MCP tools allowed (stdio server, isolated data root
     in a temp dir; Bash/Read/Write/Glob/Grep/web all disallowed),
   - no access to the repo, so it cannot peek at lane_a/lane_b.
3. Parses the agent's fenced JSON report and scores each metric
   against Lane A within per-metric relative tolerances.

Exit code is nonzero if any required metric fails, so this can run in
automation (cron, CI with API credentials) as well as by hand.

## Running

Requires the Claude Code CLI (authenticated) and `claude-agent-sdk`:

```bash
# one case
uv run --with claude-agent-sdk \
    packages/omd/examples/agent_eval/eval_lane_c.py paraboloid

# all cases (paraboloid, ocp_caravan_basic, ocp_oas_coupled)
uv run --with claude-agent-sdk \
    packages/omd/examples/agent_eval/eval_lane_c.py all

# useful flags
#   --model <name>   model override for the agent
#   --verbose        stream agent text while it works
#   --keep-data      keep the temp omd data root for inspection
```

## Cases and tolerances

| Case | Metrics (required) | rtol |
|------|--------------------|------|
| `paraboloid` | `analysis_f_xy`, `opt_f_xy` | 1e-6, 1e-4 |
| `paraboloid` | `opt_x`, `opt_y` (warn-only: DV retrieval is a known tool-surface gap, see FEATURE_BACKLOG) | 1e-3 |
| `ocp_caravan_basic` | `fuel_burn_kg`, `OEW_kg`, `MTOW_kg` | 1e-3, 1e-3, 1e-6 |
| `ocp_oas_coupled` | `fuel_burn_kg`, `OEW_kg`, `MTOW_kg` | 1e-3, 1e-3, 1e-6 |

The `ocp_oas_coupled` prompt gets a supplement with the baseline
mission profile (climb/cruise/descent speeds, node count) because the
lane_c prompt delegates those to the `ocp_caravan_basic` example files,
which a blind MCP-only agent cannot read.

The agent's friction log (tool errors, confusing parameters,
workarounds) is printed with each case; feed recurring items into
`docs/FEATURE_BACKLOG.md`.
