# single_aisle_oas_wing -- OAS-in-Aviary wing-mass parity case

The advanced single aisle sized on upstream's OAS-example mission
(3 fixed-profile phases, 1800 nmi) with the empirical FLOPS wing weight
replaced by an OpenAeroStruct wingbox sub-optimization -- upstream
Aviary's own external-subsystem integration, exposed through the hangar
tool surface. First case exercising nested tool composition (one wrapped
tool running *inside* another's optimization loop).

- Lane A: raw upstream `OASWingMassBuilder` + Level-3 sequence + the
  example's post-setup `set_val` block (values verbatim).
- Lane B: `add_external_subsystem` + `run_sizing`, in both
  `subsystem_mode="coupled"` and `"precompute"` -- the two are exactly
  equivalent for this feed-forward subsystem (measured bit-identical;
  docs/aviary-oas-integration-plan.md WP1) and both are asserted against
  Lane A.
- Lane C: closed + open agent prompts (`lane_c/`).
- A contrast test proves the integration moves the wing mass off the
  FLOPS estimate by >3%.

Each converged run costs ~50 s (nested wingbox sub-opt + sizing). Needs
aviary + openaerostruct + ambiance:

```bash
.venv-avy/bin/python -m pytest packages/avy/examples/single_aisle_oas_wing/tests/ -v --rootdir=.
```
