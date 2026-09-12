# avy_bwb -- omd-level Aviary BWB sizing parity case

The same engineering problem as `packages/avy/examples/bwb_sizing/` (the
upstream BWB benchmark deck on the fixed-profile M0.85 / 7750 nmi mission,
SLSQP) through the omd lanes: Lane A subprocess-runs the per-tool
raw-Aviary reference in `.venv-avy`; Lane B runs the `avy/Sizing`
subprocess factory with `phase_info_module=hangar.avy.config.
missions_bwb_fixed`. See `../avy_single_aisle/README.md` for the
subprocess-factory rationale (numpy-2 venv split); tests skip when
`.venv-avy` is absent.

```bash
uv run pytest packages/omd/examples/tests/test_parity.py -k avy -v -s
```
