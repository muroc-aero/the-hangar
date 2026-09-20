# avy_bwb -- omd-level Aviary BWB sizing parity case

The same engineering problem as `packages/avy/examples/bwb_sizing/` (the
upstream BWB benchmark deck on the fixed-profile M0.85 / 7750 nmi mission,
SLSQP) through the omd lanes: Lane A imports and runs the per-tool
raw-Aviary reference in-process; Lane B runs the native `avy/Sizing`
factory with `phase_info_module=hangar.avy.config.missions_bwb_fixed` in
`mode: optimize`. See `../avy_single_aisle/README.md` for the
native-factory description; tests skip when `aviary` is not installed
(`bash scripts/dev-setup.sh`).

```bash
uv run omd-cli run packages/omd/examples/avy_bwb/lane_b/sizing/plan.yaml --mode optimize
uv run pytest packages/omd/examples/tests/test_parity.py -k avy -v -s
```
