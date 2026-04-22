# Plan: Three fixes for multi-tool shared-DV composition in omd

Motivated by the Adler 2022a reproduction study
(`hangar_studies/adler2022a-missionopt/RESULTS.md`). The paper's pattern
of "size the wing structure at a 2.5 g maneuver, operate it on a
mission, share one set of geometry DVs" falls outside omd's current
composition primitives (slots are per-phase; composites require
per-element `connections`; no shared-DV concept). This document lays
out three fixes that close that gap, ordered from smallest to largest.

## Summary

| # | Fix | Scope | Effort | Delivers |
|---|-----|-------|--------|----------|
| 1 | `maneuver` slot on OCP | 1 new slot provider + 1 factory hook | ~1 day | Closes Adler 2022a gap |
| 2 | `shared_vars` plan section | New plan primitive, factory opt-out | ~1 week | Generalizes to arbitrary multi-tool |
| 3 | `produces`/`consumes` factory contract | Materializer rewrite, all factories | ~2-3 weeks | Auto-detects shared DVs |

**Order**: 1 -> 2 -> 3. Each builds on the previous. Fix 1 ships value
immediately; Fix 2 generalizes; Fix 3 makes it declarative.

---

## Fix 1 -- `maneuver` slot on the OCP factory

**Goal**: Add a one-shot Aerostruct sibling to the mission that shares
geometry promoted up from the mission's aircraft model, reproducing
the pattern from `B738_aerostructural.py:263-318`.

**Key architectural decision**: Slots today are per-phase (applied
inside `DynamicAircraftModel` for each flight phase). The maneuver is
NOT per-phase -- it runs once. So the slot mechanism needs a second
tier.

**Steps**:
1. **Slot provider contract extension**
   (`packages/omd/src/hangar/omd/slots.py`):
   - Add a `slot_scope: "per_phase" | "top_level"` attribute on
     providers. Existing providers get `slot_scope="per_phase"`.
   - Document in `slots-and-fidelity.md`.
2. **New provider `oas/maneuver`** (`slots.py`):
   - Wraps `openconcept.aerodynamics.openaerostruct.Aerostruct`
   - Config keys: `load_factor`, `Mach`, `altitude_ft`, `num_x`,
     `num_y`, plus CP counts
   - Returns a Group containing: Aerostruct + dynamic pressure + lift
     balance + `kg_to_N` ExecComp + `BalanceComp` for alpha
   - `slot_scope="top_level"`
   - `result_paths = {"failure_maneuver": "failure"}`
   - `promotes_inputs`: `ac|geom|wing|*`, `ac|weights|MTOW`,
     `load_factor`
3. **Factory hook**
   (`packages/omd/src/hangar/omd/factories/ocp/builder.py`):
   - In `AnalysisGroup.setup()`, after the `analysis` subsystem is
     added, walk `slots` for providers with `slot_scope="top_level"`
   - Add each as a sibling subsystem with promoted inputs matching the
     provider's declared list
   - Connect `analysis.climb.ac|weights|W_wing` -> the provider's
     wing-weight input (if declared)
4. **Schema** (`packages/omd/src/hangar/omd/plan_schema.py`):
   - Add `maneuver` to the slots enum
5. **var_paths**:
   - `failure_maneuver` -> `maneuver.failure` (so plans can write
     `constraints: [{name: failure_maneuver, upper: 0}]`)
6. **Tests** (`packages/omd/tests/test_slot_maneuver.py`):
   - Analysis test: b738 + maneuver slot, check `failure_maneuver`
     output computed
   - Optimization test: minimal 2-DV case with maneuver failure
     constraint, verify constraint becomes active
   - Regression: existing non-maneuver plans unchanged
7. **Docs**: update `slots-and-fidelity.md` with the slot, including a
   note that top-level slots are one-shot and should NOT be declared
   per-phase
8. **Validate against Adler**: modify
   `hangar_studies/adler2022a-missionopt/components/mission.yaml` to
   add the maneuver slot, re-run optimization, confirm stress
   constraint becomes binding, re-match paper's t/c and spar/skin
   distributions more closely

**Out of scope for Fix 1**: sharing geometry across arbitrary
component pairs (still a single-OCP-component plan).

---

## Fix 2 -- `shared_vars` top-level plan section

**Goal**: Make any two components in a composite plan share a set of
design variables without explicit `connections:` wiring per DV element.

**Prerequisite**: Fix 1 (validates the pattern for single-tool; Fix 2
generalizes).

**Plan schema addition**:
```yaml
shared_vars:
  - name: ac|geom|wing|AR
    value: 9.45
    consumers: [mission, maneuver_standalone]
  - name: ac|geom|wing|skin_thickness
    value: [0.005, 0.01, 0.015]
    units: m
    consumers: [mission, structural_certification]
```

**Steps**:
1. **Schema** (`plan_schema.py`): add `shared_vars` block with
   name/value/units/consumers.
2. **Factory contract extension**: all factories accept a
   `skip_fields: list[str]` config key. When present, the factory's
   internal IVC (e.g., `dv_comp` for OCP, surface IVC for OAS) omits
   those fields and leaves them as unconnected promoted inputs.
   - Touch: `factories/ocp/builder.py`, `factories/oas.py`,
     `factories/oas_aero.py`, `factories/pyc.py`
3. **Materializer update** (`materializer.py`):
   - After each component is materialized, inject `skip_fields`
     matching the shared_vars list for that consumer
   - Build a root `_shared_ivc` IndepVarComp with all shared_vars as
     outputs
   - Auto-generate connections from `_shared_ivc.{name}` ->
     `{comp_id}.{name}` for each consumer
   - DV path resolution: if a DV name appears in shared_vars, resolve
     it to `_shared_ivc.{name}`
4. **`connections:` backward-compat**: leave existing explicit
   `connections:` untouched; shared_vars is additive.
5. **Plan builder support** (`plan_mutate.py`):
   - `omd-cli plan add-shared-var <dir> --name ac|geom|wing|AR
     --value 9.45 --consumers mission,maneuver`
6. **Tests**:
   - Composite plan: `ocp/BasicMission` + `oas/AerostructPoint` with
     shared wing geometry; verify both consumers receive identical
     values under optimization
   - Shared-DV registration: confirm DVs registered at the shared
     IVC, not component-local
   - Validation: reject `shared_vars` if a listed consumer doesn't
     promote the field
7. **Docs**: new section in `plan-authoring.md` covering when to use
   shared_vars vs connections
8. **Migration note**: the Adler plan from Fix 1 can be refactored
   from single-component-with-maneuver-slot to composite (mission +
   separate Aerostruct component) sharing geometry via shared_vars --
   proving the two paths are equivalent

**Risks**:
- Factories that don't currently expose `ac|geom|wing|*` as promoted
  inputs will need updating; audit which ones do
- Conflict resolution: what if two components both produce the same
  field? Schema must require exactly one producer per shared_var,
  with the shared IVC taking that role.

---

## Fix 3 -- `produces`/`consumes` factory contract

**Goal**: Factories declare their data dependencies; the materializer
auto-derives shared_vars without the user specifying them.

**Prerequisite**: Fix 2 (provides the shared-IVC machinery; Fix 3 is
the auto-detection layer on top).

**Factory metadata schema** (in `factory_metadata.py`):
```python
@dataclass
class FactoryContract:
    produces: dict[str, VarSpec]   # IVCs this factory owns by default
    consumes: dict[str, VarSpec]   # promoted inputs this factory expects
```

**Steps**:
1. **Contract dataclass** (`factory_metadata.py`): define
   `FactoryContract`, `VarSpec` (shape, units, default, semantic tag
   like "geometry" / "flight_condition" / "material")
2. **Audit every factory** and write its contract:
   - `oas/AeroPoint`: produces `wing.twist_cp`, `wing.chord_cp`,
     `wing.sweep_cp`, etc.; consumes `velocity`, `alpha`,
     `Mach_number`, `rho`
   - `oas/AerostructPoint`: produces all wing geometry; consumes
     flight condition; has material properties
   - `ocp/BasicMission`: produces `ac|*` (full aircraft dict);
     consumes per-phase flight conditions
   - `pyc/TurbojetDesign`: produces engine parameters; consumes
     design-point flight condition
3. **Auto-materialization logic** (`materializer.py` rewrite):
   - Collect `consumes` across all components; find names consumed by
     >=2 components
   - For each, pick exactly one producer (preference: a factory that
     declares `produces` with semantic tag matching; else error)
   - Suppress internal IVCs via `skip_fields` on non-canonical
     producers
   - Insert root shared_ivc outputs for shared paths (reusing Fix 2's
     machinery)
4. **Opt-out**: a plan-level `no_auto_share: [...]` escape hatch when
   the auto-detection picks the wrong producer
5. **Deprecate `shared_vars`**: keep it working (user override wins
   over auto-detect), but the common case needs no user declaration
6. **Tests**:
   - All existing composite fixtures still work without modification
   - New test: mission + multipoint OAS + pyCycle with NO explicit
     shared_vars or connections; materializer wires everything via
     contracts
7. **Docs**:
   - New guide `factory-contracts.md` for factory authors
   - Migration guide: how to add contracts to existing/third-party
     factories
8. **Rollout**:
   - Phase 3a: add contracts without changing materialization
     behavior; log what WOULD be auto-shared
   - Phase 3b: flip a feature flag to enable auto-sharing
   - Phase 3c: remove flag, make default

**Risks**:
- Contract drift: factories diverge from their declared contracts;
  need a validator that runs at factory-registration time checking
  declared produces/consumes against actual OpenMDAO problem after
  setup
- Third-party factories: lack contracts, fall back to explicit
  `shared_vars` / `connections`

---

## Validation gates between fixes

- **After Fix 1**: Adler plan with maneuver slot matches paper's
  mission-based fuel burn within 1% and the 2.5g failure constraint
  becomes active.
- **After Fix 2**: The Adler plan can be expressed two ways
  (maneuver-slot monolithic; composite with shared_vars) and produces
  identical results -- confirming the primitive works.
- **After Fix 3**: A brand-new plan combining mission + maneuver +
  propulsion sizing can be authored with no `shared_vars` or
  `connections` block at all.

## What this plan does NOT cover

- Frontend / UI changes (plan builder, omd-cli review): each fix
  grows the schema, so `plan review` will flag missing/contradictory
  sections but won't auto-fix.
- Performance: shared IVCs at the plan root may change derivative
  paths; need a perf check on a non-trivial composite after Fix 2.
- Backend for the omd viewer / provenance DAG: shared_vars change the
  graph structure; the viewer will need to represent shared DVs as
  fan-out edges (Fix 2 follow-up).

---

## Phase 3a follow-ups

After the first-pass review of the three-fix rollout, the items
below were acknowledged as Phase 3a scope but deferred to separate
work:

- **Multipoint OAS contract.** `oas/AerostructMultipoint` declares an
  empty `FactoryContract`; its vectorized `prob_vars` IVC has a
  shape that depends on `flight_points`, so it does not fit the
  single-shape contract model. Plans with multipoint OAS + OCP
  still need explicit `shared_vars:` to share wing geometry. A
  per-flight-point contract shape (or a `consumes`-only contract
  with promotion rules) should close this gap in a later phase.
- **pyc/\* contracts.** All pyCycle archetypes declare empty
  contracts. Cycle groups are the OpenMDAO model root, not a
  composable subsystem with an IVC to skip against, so auto-share
  would need a different mechanism (e.g., wrapper IVCs for
  parameters shared across design and off-design points).
- **Cross-tool semantic-tag translation.** Fix 3 matches names
  literally; OCP calls wing aspect ratio `ac|geom|wing|AR` while OAS
  factories do not expose it at all. A cross-tool translator keyed
  on `VarSpec.semantic_tag` is the intended Phase 3b+ step toward
  auto-sharing across tool boundaries.
- **Phase 3b: flip the `composition_policy` default to `auto`.**
  Gated on Phase 3a green tests on a real Adler composite run and
  the cross-tool translation above. Keep the `explicit` setting
  available as an opt-out.
- **Adler monolithic-vs-composite parity.** The Fix 2 validation
  gate calls for an end-to-end run proving the Adler plan can be
  expressed either as a single OCP mission with an `oas/maneuver`
  slot, or as two components (mission + standalone Aerostruct
  sizing case) sharing geometry via `shared_vars`. `tests/
  test_shared_vars.py::TestFormulationEquivalence` covers the
  primitive on paraboloid; the full Adler parity run requires a
  new `oas/aerostruct-sizing` standalone component factory and is
  tracked as a separate follow-up.
- **Viewer/DAG fan-out edges.** The provenance viewer still renders
  shared DVs as a single node; Fix 2 did not extend the DAG
  layout. Adding a fan-out representation is follow-up work.
