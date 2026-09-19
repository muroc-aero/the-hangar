# Lane C -- agent prompts for the single-aisle sizing case

Two prompt flavours for the blind-agent stage of Lane C (see
`docs/parity-lanes-and-agent-eval.md` §5):

- `sizing.prompt.md` -- **closed**: names the tools, template, and call
  order. Certifies the tool surface computes the right numbers when driven
  correctly.
- `sizing_open.prompt.md` -- **open**: states only the engineering goal and
  physics; the agent must discover the template, config keys, and workflow
  from the server's own affordances. Certifies the surface is self-teaching.

Scoring: the reported metrics are compared against Lane A
(`lane_a/sizing.py`) with the tolerances in `../shared.py` (`TOL_PARITY` /
`TOL_RANGE`), exactly like the scripted Lane B tests.

These prompts target the **Aviary server's own MCP tools**
(`mcp__Aviary__*`); the `packages/omd/examples/avy_*` suites target the omd
plan tools instead, where the omd `avy/Sizing` factory is native (Aviary's
group inside the omd problem). An agent-eval harness akin to
`packages/omd/examples/agent_eval/eval_lane_c.py` pointed at `avy-server`
(stdio, `uv run avy-server`) can consume these as-is.
