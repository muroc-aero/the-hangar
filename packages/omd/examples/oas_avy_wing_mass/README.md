# oas_avy_wing_mass -- loose-coupled OAS -> Aviary wing mass (B2)

The native multitool composition: an OAS aerostructural wing computes a
structural wing mass that a plan connection feeds straight into the
Aviary sizing's `aircraft:wing:mass` -- one OpenMDAO problem, one driver.
Giving `aircraft:wing:mass` a deck value in the `avy/Sizing` `overrides`
config is Aviary's own override mechanism: the FLOPS wing-mass output is
renamed away and the variable becomes a boundary input that the
connection (`wingbox.wing.structural_mass -> sizing.aircraft:wing:mass`)
drives. The connection converts kg -> lbm (OpenMDAO units on both ends);
the parity test asserts the sizing's wing mass IS the OAS structural mass
to round-off.

Relation to the tight-coupled cases: `avy_oas_wing` runs OAS *inside*
Aviary's optimizer (upstream's own wingbox subsystem, physically grounded
on the real planform); this case couples the tools at the omd level with
a single-aisle-*scaled* rect tube wing -- it certifies the composition
plumbing, and its wing re-solves only if a plan-level input changes
(one-way coupling, no feedback).

- Lane A (compositional): raw OAS -> structural mass -> raw-Aviary
  override run (`lane_a/avy_override_sizing.py`), both in this process.
  No single upstream script does this composition, so the oracle is built
  from the two certified raw pieces.
- Lane B: the two-component plan with `overrides` + `connections`, run in
  `mode: optimize` (the Aviary sizing is the optimization; the wingbox
  solves once per evaluation).
- Lane C: closed prompt (`lane_c/`).

Follow-on (not built): a `run_study` trade sweeping the tube thickness or
span at the OAS end against gross mass at the Aviary end.

```bash
uv run omd-cli run packages/omd/examples/oas_avy_wing_mass/lane_b/coupled_wing_mass/plan.yaml --mode optimize
uv run pytest packages/omd/examples/tests/test_parity.py -k oas_avy -v -s
```
