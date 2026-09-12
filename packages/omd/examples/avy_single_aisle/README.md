# avy_single_aisle -- omd-level Aviary sizing parity case

The same engineering problem as
`packages/avy/examples/single_aisle_sizing/` (advanced single-aisle FLOPS
deck, default energy_state mission, 1906 nmi, SLSQP), solved through the
omd lanes:

- **Lane A** (`lane_a/sizing.py`): the per-tool raw-Aviary reference
  script, executed as a subprocess in `.venv-avy` -- one shared reference
  implementation for both example levels.
- **Lane B** (`lane_b/sizing/plan.yaml`): the `avy/Sizing` subprocess
  factory through the omd plan pipeline.
- **Lane C** (`lane_c/`): closed/open agent prompts over the
  `mcp__omd__*` tools; the scripted stage lives in
  `tests/test_parity_lane_c.py`.

**Why a subprocess factory:** aviary needs numpy>=2 and cannot be imported
in the main workspace venv (the openconcept pin caps numpy<2), so the
component shells out to the isolated `.venv-avy`
(`scripts/setup-avy-venv.sh`) -- which also isolates Aviary's
process-global hazards (cwd-relative reports, problem-name collisions).
All lanes therefore **skip when `.venv-avy` is absent** (e.g. in CI).

The component is **self-driving**: every Aviary run is a dymos+SLSQP
optimization, so `mode: analysis` runs the embedded sizing; check the
`converged` summary output (Aviary non-convergence does not raise).

Run (needs `.venv-avy`):

```bash
uv run pytest packages/omd/examples/tests/test_parity.py -k avy -v -s
uv run pytest packages/omd/examples/tests/test_parity_lane_c.py -k avy -v -s
```
