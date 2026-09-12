# oas_avy_wing_mass -- loose-coupled OAS -> Aviary wing mass (B2)

The cross-venv multitool composition: an OAS aerostructural wing (main
venv, numpy<2) computes a structural wing mass that omd feeds into an
Aviary sizing (`avy/Sizing` subprocess into `.venv-avy`, numpy 2) as a
deck override on `aircraft:wing:mass`, through the factory's
`override_inputs` mechanism. The plan connection converts kg -> lbm
(OpenMDAO units on both ends); the parity test asserts the sizing's wing
mass IS the OAS structural mass to round-off.

Relation to the tight-coupled cases: `avy_oas_wing` runs OAS *inside*
Aviary's optimizer (upstream's own wingbox subsystem, physically grounded
on the real planform); this case couples the tools at the omd level with
a single-aisle-*scaled* rect tube wing -- it certifies the composition
plumbing, and its wing re-solves only if a plan-level input changes
(one-way coupling, no feedback).

- Lane A (compositional): raw OAS in this venv -> structural mass ->
  subprocess raw-Aviary override run in `.venv-avy`
  (`lane_a/avy_override_sizing.py`). No single upstream script does this
  composition, so the oracle is built from the two certified raw pieces.
- Lane B: the two-component plan with `connections` + `override_inputs`.
- Lane C: closed prompt (`lane_c/`).

Follow-on (not built): a `run_study` trade sweeping the tube thickness or
span at the OAS end against gross mass at the Aviary end.

```bash
uv run pytest packages/omd/examples/tests/test_parity.py -k oas_avy -v -s
```
