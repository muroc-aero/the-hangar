# avy_oas_wing -- omd-level OAS-in-Aviary wing-mass parity case

The same engineering problem as
`packages/avy/examples/single_aisle_oas_wing/` (advanced single aisle,
fixed-profile 1800 nmi mission, FLOPS wing weight replaced by an
OpenAeroStruct wingbox sub-optimization) through the omd lanes: Lane A
imports and runs the per-tool raw-upstream reference in-process; Lane B
threads `external_subsystems: [{name: oas_wing_mass}]` through the native
`avy/Sizing` factory -- the hangar.avy registry builds the subsystem
inside the `AviaryGroup`, so the nested sub-opt runs inside Aviary's
mission phases, in the omd process. First omd case exercising nested tool
composition (a wrapped tool inside another tool's optimizer).

Runs ~90 s per lane (nested wingbox sub-opt + sizing); the plan raises
`optimizer.options.timeout_seconds` accordingly. Tests skip when `aviary`
is not installed (`bash scripts/dev-setup.sh`).

```bash
uv run omd-cli run packages/omd/examples/avy_oas_wing/lane_b/coupled_sizing/plan.yaml --mode optimize
uv run pytest packages/omd/examples/tests/test_parity.py -k avy_oas -v -s
```
