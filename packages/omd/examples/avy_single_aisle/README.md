# avy_single_aisle -- omd-level Aviary sizing parity case

The same engineering problem as
`packages/avy/examples/single_aisle_sizing/` (advanced single-aisle FLOPS
deck, default energy_state mission, 1906 nmi, SLSQP), solved through the
omd lanes:

- **Lane A** (`lane_a/sizing.py`): the per-tool raw-Aviary reference
  script, imported and run in-process -- one shared reference
  implementation for both example levels.
- **Lane B** (`lane_b/sizing/plan.yaml`): the native `avy/Sizing`
  factory through the omd plan pipeline.
- **Lane C** (`lane_c/`): closed/open agent prompts over the
  `mcp__omd__*` tools; the scripted stage lives in
  `tests/test_parity_lane_c.py`.

**Native factory:** Aviary's `AviaryGroup` is added to the omd problem as
subsystem `aviary` with `promotes=["*"]`, so its `aircraft:*` /
`mission:*` names are the component's namespace and its own design
variables, constraints and objective are collected by omd's driver. The
whole workspace runs in one venv (Aviary 1.0.1 / numpy 2), so the lanes
share a process; tests skip only when `aviary` is not installed
(`bash scripts/dev-setup.sh`). Lane B reproduces Lane A to ~1e-8 relative
in ~3 s.

Every Aviary run is a dymos+SLSQP optimization, so the plan runs with
`mode: optimize` (`mode: analysis` is refused) and needs no plan-level
DVs/objective for it. Check the `converged` summary field (Aviary
non-convergence does not raise).

Run:

```bash
uv run omd-cli run packages/omd/examples/avy_single_aisle/lane_b/sizing/plan.yaml --mode optimize
uv run pytest packages/omd/examples/tests/test_parity.py -k avy -v -s
uv run pytest packages/omd/examples/tests/test_parity_lane_c.py -k avy -v -s
```
