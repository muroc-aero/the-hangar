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

Unlike the omd examples, these target the **Aviary server's own MCP tools**
(`mcp__Aviary__*`) rather than omd plan tools -- the omd `avy` factory is
blocked on the numpy-2 venv split (see `docs/aviary-server-plan.md`). An
agent-eval harness akin to `packages/omd/examples/agent_eval/eval_lane_c.py`
pointed at `avy-server` (stdio, from `.venv-avy`) can consume these as-is.
