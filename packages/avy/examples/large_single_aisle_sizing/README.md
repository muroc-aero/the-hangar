# large_single_aisle_sizing -- Aviary parity example (737-class)

A second airframe through the same lanes as `single_aisle_sizing`: the
`large_single_aisle_1` FLOPS deck (the aircraft behind the upstream FwFm
benchmark family) sized on the default 3-phase energy_state mission with a
2500 nmi range constraint, under SLSQP.

- **Lane A** (`lane_a/sizing.py`): raw Aviary Level 1, pinned to `GOLDEN`
  anchors from v1.0.1 (gross 162,888 lbm, fuel 28,602 lbm).
- **Lane B** (`lane_b/sizing.json`): the identical problem through the MCP
  tool script (`load_aircraft_template -> configure_mission -> run_sizing`).

Run (inside `.venv-avy`; see `scripts/setup-avy-venv.sh`):

```bash
.venv-avy/bin/python -m pytest packages/avy/examples/large_single_aisle_sizing/tests/ -v --rootdir=.
```
