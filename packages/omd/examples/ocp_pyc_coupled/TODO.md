# TODO: ocp_pyc_coupled has no Lane B parity plan (yet)

`TestOCPPyCycleCoupledParity` in `../tests/test_parity.py` reads
`lane_b/coupled_mission/plan.yaml`, but that file is intentionally **not**
committed. A faithful Lane B plan cannot reach parity with the current Lane A
reference, and the underlying example is non-physical. This note records why and
what a real fix requires.

## Why a faithful Lane B plan is currently impossible

Lane A (`lane_a/coupled_mission.py`) bolts a pyCycle **turbojet** onto the
Cessna Caravan airframe and keeps the **turboprop** empty-weight regression
(`SingleTurboPropEmptyWeight`), giving `OEW = 1986 kg`.

The omd OCP factory cannot reproduce that. Weight-model precedence in
`hangar/omd/factories/ocp/aircraft_model.py` (`_make_aircraft_model_class`) is:

1. weight slot provider (if `slots["weight"]`)
2. **OEW passthrough — forced whenever a propulsion slot is active**
3. architecture `WeightClass` (default)
4. CFM56 passthrough

Because any `slots["propulsion"]` short-circuits to step 2 (the pyCycle group
exposes no `component_weight` outputs for a weight model to consume), Lane B
passes through the caravan template's `ac|weights|OEW = 2145 kg`.

Result: OEW differs 1986 vs 2145 kg (~8%), which propagates to a ~4% fuel-burn
gap (5393 vs 5606 kg) — far outside the test's `rel=1e-3`. This is a structural
factory limitation, not a plan-authoring error. (The other 7 missing-lane_b
examples were given committed plans in this same change and pass at +0.0000%.)

The example is also explicitly non-physical: `shared.py` notes "a turbojet is
not realistic for a Caravan ... the absolute values are not physically
meaningful," and the direct-coupled Newton is ill-conditioned (the line search
visibly struggles).

## Recommended fix: build a physical case instead of patching the demo

Rather than force parity on a non-physical airframe/engine pairing, replace the
example with a physically consistent one and make both lanes use the same
weight treatment. This is essentially the single-slot version of the existing
`ocp_three_tool` example (b738 + pyc/surrogate hbtf).

Concrete changes:

1. **Airframe + engine match.** Switch `aircraft_template` to `b738`
   (`twin_turbofan`) and the propulsion slot to `pyc/hbtf` (or a turbojet sized
   to a jet's thrust), so the engine archetype suits the airframe. Update
   `shared.py` (PYC_CONFIG: design_alt ~35000 ft, design_MN ~0.8, design_Fn to
   the b738 per-engine thrust, design_T4 to a realistic core temp).

2. **Jet-appropriate mission.** Raise the mission profile to jet conditions
   (cruise ~35000 ft, cruise/climb EAS to b738 values, larger range). Reuse the
   `ocp_three_tool` mission_params as a starting point.

3. **Consistent empty weight (the actual parity blocker).** Pick ONE OEW
   source and use it on both lanes:
   - Simplest: have **Lane A also use OEW passthrough** (read
     `ac|weights|OEW` from the template instead of `SingleTurboPropEmptyWeight`).
     Then Lane B's passthrough matches by construction. This is the smallest
     change and is honest for a slot-mechanism demo.
   - Or, more work: teach the pyCycle propulsion slot provider
     (`_pyc_*_propulsion_provider` / `_DirectPyCyclePropGroup` in
     `hangar/omd/slots.py`) to emit a `component_weight` estimate (e.g. an
     engine-weight correlation from core size / thrust) and add a config flag so
     the architecture `WeightClass` runs alongside a propulsion slot. This makes
     Lane B compute OEW like Lane A, but requires a weight correlation and a new
     precedence branch in `_make_aircraft_model_class`.

4. **Engine sizing for robustness.** Size `design_Fn` to the airframe's cruise
   drag so throttle stays mid-range; this fixes the ill-conditioned Newton and
   removes the order-dependent convergence seen with the Caravan pairing. For
   direct-coupled HBTF use `thermo_method: TABULAR` (see omd CLAUDE.md).

5. **Tolerance.** Direct-coupled pyCycle parity realistically lands around
   `rel=1e-2`, not `1e-3`; relax the assertion accordingly even after the model
   is consistent.

6. **Commit the plan.** Once both lanes agree, author
   `lane_b/coupled_mission/plan.yaml` (component `ocp/BasicMission` with the
   `pyc/hbtf` propulsion slot) and `git add -f` it past the `**/plan.yaml`
   ignore rule, mirroring the other committed example plans.

## Until then

`ocp_pyc_coupled` is excluded from the green parity run. Deselect it alongside
`TestOCPThreeToolParity`, e.g.:

    uv run pytest packages/omd/examples/tests/ -k "not ThreeTool and not PyCycleCoupled"
