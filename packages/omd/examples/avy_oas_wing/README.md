# avy_oas_wing -- omd-level OAS-in-Aviary wing-mass parity case

The same engineering problem as
`packages/avy/examples/single_aisle_oas_wing/` (advanced single aisle,
fixed-profile 1800 nmi mission, FLOPS wing weight replaced by an
OpenAeroStruct wingbox sub-optimization) through the omd lanes: Lane A
subprocess-runs the per-tool raw-upstream reference in `.venv-avy`;
Lane B threads `external_subsystems: [{name: oas_wing_mass}]` through the
`avy/Sizing` subprocess factory -- the nested sub-opt runs inside the
worker, where openaerostruct is installed. First omd case exercising
nested tool composition (a wrapped tool inside another tool's optimizer).

Runs ~90 s per lane (nested wingbox sub-opt + sizing). Tests skip when
`.venv-avy` is absent.

```bash
uv run pytest packages/omd/examples/tests/test_parity.py -k avy_oas -v -s
```
