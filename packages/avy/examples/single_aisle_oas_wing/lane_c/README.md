# Lane C -- agent prompts for the OAS wing-mass case

Two prompt flavours for the blind-agent stage of Lane C (see
`docs/parity-lanes-and-agent-eval.md` §5):

- `coupled_sizing.prompt.md` -- **closed**: names the tools, template,
  subsystem, and call order. Certifies the tool surface computes the right
  numbers when driven correctly.
- `coupled_sizing_open.prompt.md` -- **open**: states only the engineering
  goal (physics-based wing mass replacing the empirical estimate); the
  agent must discover `add_external_subsystem` and the `oas_wing_mass`
  registry entry from the server's own affordances.

Scoring: the run the report names (`run_id`) is compared against Lane A
(`lane_a/coupled_sizing.py`) with the tolerances in `../shared.py`.

Both prompts ask for the task only, not for a comparison against a
subsystem-free baseline: a prompt that asks for a control run leaves that
run in the provenance too, and the grade then depends on which run gets
scored (the same defect main fixed in its omd open prompts). The
empirical-vs-physics contrast is still checked, by the scripted
`test_oas_wing_mass_differs_from_flops` (`MIN_WING_MASS_CONTRAST_REL`),
where the two runs are explicit.
