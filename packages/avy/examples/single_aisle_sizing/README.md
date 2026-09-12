# single_aisle_sizing -- Aviary parity example

The same engineering problems solved through each lane (see
`docs/parity-lanes-and-agent-eval.md`): the advanced single-aisle transport
(FLOPS mass + aero) on energy_state missions under SLSQP.

Three cases, each exercising a different wrapper path:

| Case | Wrapper path certified | Lane A | Lane B |
|---|---|---|---|
| `sizing` | template + default mission | `lane_a/sizing.py` | `lane_b/sizing.json` |
| `override_sizing` | `define_aircraft` deck overrides (AR 11.56 -> 13.0) | `lane_a/override_sizing.py` | `lane_b/override_sizing.json` |
| `short_mission` | `configure_mission` phase_info merge (1200 nmi, coarse cruise) | `lane_a/short_mission.py` | `lane_b/short_mission.json` |

- **Lane A**: raw Aviary Level 1 (`run_aviary`), no hangar code. The
  reference, pinned to `GOLDEN*` anchors from Aviary v1.0.1.
- **Lane B**: the identical problem as an MCP tool-call script replayed in
  process through `hangar.sdk.cli.runner.run_tool`. Fast contract tests
  assert the JSON scripts carry the exact values from `shared.py`.
- **Lane C** (`lane_c/`): closed and open agent prompts targeting the
  Aviary server's MCP tools, scored against Lane A with the same
  tolerances. See `lane_c/README.md` (the omd-level Lane C is blocked on
  the numpy-2 venv split; see `docs/aviary-server-plan.md`).

Parameters and tolerances live in `shared.py` (the contract). Headline
metrics: `gross_mass_lbm`, `total_fuel_mass_lbm`, `range_nmi`,
`final_time_min`.

Sibling examples run the same lanes on other airframes:
`../large_single_aisle_sizing/` (737-class deck, 2500 nmi) and
`../bwb_sizing/` (the upstream BWB benchmark, cross-anchored to its
published SNOPT values).

Run (inside the isolated Aviary venv; see `scripts/setup-avy-venv.sh`):

```bash
.venv-avy/bin/python -m pytest packages/avy/examples/single_aisle_sizing/tests/ -v --rootdir=.
```

Each lane run takes ~15-20 s; the full suite is ~4 min.
