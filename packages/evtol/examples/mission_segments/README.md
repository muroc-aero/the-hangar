# mission_segments -- three-lane parity example

Evaluates hangar-evtol against the direct evtolpy API using the three core
upstream analysis lanes: **mission-segment energy**, **mission-segment power**,
and **mission-segment weight** (mass breakdown + MTOW iteration).

## Lanes

- **lane_a/** -- direct evtolpy API, the ground truth. Each script
  (`segment_energy.py`, `segment_power.py`, `mass_breakdown.py`,
  `mtow_iteration.py`) reproduces the corresponding upstream
  `analysis/.../log_*.py` script, returning a dict instead of writing CSV.
- **lane_b/** -- the hangar-evtol MCP tool layer. `run_all.py` builds the full
  config through the section setters and runs `run_mission_analysis` /
  `run_sizing` in-process; `mission_analysis.json` / `sizing.json` are the same
  workflows as `evtol-cli run-script` scripts.
- **cfg/test-all.json** -- the shared config (upstream `test-all.json` baseline),
  read by `shared.py`. Both lanes build from this exact data.

## Tests

- `tests/test_parity.py` -- Lane A vs Lane B for all three tables and the MTOW
  history, to floating-point round-off (`rtol=atol=1e-9`), plus `golden_physics`
  checks pinning headline numbers at the evtolpy reference.
- `tests/test_cli_script.py` -- runs the lane_b JSON workflows through the real
  `evtol-cli` in a subprocess (the CLI evaluation).

```bash
uv run pytest packages/evtol/examples/mission_segments/tests/
```
