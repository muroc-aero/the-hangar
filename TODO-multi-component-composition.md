# Multi-Component Composition in omd

## The Problem

The omd factory pattern requires a hand-written factory for each upstream tool
(OAS, OCP, pyCycle) AND for each combination of tools (OAS+OCP, pyCycle+OCP,
OAS+OCP+pyCycle). With N tools:

- N factories for single-tool wrapping
- N*(N-1)/2 factories for pairwise combinations
- Even more for three-way compositions

Concrete example: integrating OAS wing aerodynamics into an OCP mission
requires `factories/ocp_vlm.py` that manually wires `VLMDragPolar` into
the OCP aircraft model class. Adding pyCycle engine performance feeding
into that same mission would need yet another factory. This doesn't scale.

## Current State

- `materialize()` has a single-component path that delegates to a factory
  and a multi-component path that raises `NotImplementedError`
- The plan YAML schema already supports `connections:` between components
- Each factory returns `(om.Problem, metadata)` -- a full Problem, not a
  composable Group
- OCP factories need `_setup_done=True` because OpenConcept requires
  `setup()` before `set_val()` on phase-prefixed paths

## Proposed Solution

### Step 1: Factory interface change

Factories return `(om.Group, metadata)` instead of `(om.Problem, metadata)`.
The materializer creates the Problem and calls setup(). Existing factories
can be adapted with a wrapper that extracts `prob.model` for backwards compat.

For OCP, the `_setup_done` issue means the factory either:
- (a) Returns a Group and puts phase initial values into
  `metadata["initial_values_with_units"]` for the materializer to apply
  post-setup. This already works -- the materializer handles it.
- (b) Declares `metadata["_needs_early_setup"] = True` and the materializer
  calls setup() on that subsystem before composing.

Option (a) is cleaner and already partially implemented.

### Step 2: Multi-component materializer

The materializer's multi-component path:

1. Creates a top-level `om.Group`
2. For each component in the plan, calls its factory to get a Group
3. Adds each Group as a subsystem: `model.add_subsystem(comp_id, group, promotes=...)`
4. Wires explicit connections from the plan's `connections:` list
5. Configures solvers, driver, DVs, constraints, objective
6. Calls `prob.setup()`
7. Applies all `initial_values` and `initial_values_with_units` from each
   component's metadata

### Step 3: Component interface descriptors (optional, further out)

YAML descriptors in a `catalog/` directory that declare each component
type's inputs, outputs, and promoted variables. This lets the materializer
validate connections at plan-assembly time (before setup) and enables
tooling to suggest valid connections.

```yaml
# catalog/ocp/BasicMission.yaml
type: ocp/BasicMission
factory: hangar.omd.factories.ocp:build_ocp_basic_mission
inputs:
  - name: "drag"
    description: "Aerodynamic drag force"
    units: "N"
    default_source: "internal"  # PolarDrag, can be overridden
outputs:
  - name: "fuel_burn"
    path: "descent.fuel_used_final"
    units: "kg"
  - name: "OEW"
    path: "climb.OEW"
    units: "kg"
```

This is the longer-term goal. Steps 1-2 are sufficient for arbitrary
tool composition without per-combination factories.

## What This Enables

A plan YAML like this would work without a dedicated factory:

```yaml
components:
- id: wing-aero
  type: oas/AeroPoint
  config:
    surfaces:
    - name: wing
      num_y: 7
      span: 10
      ...
- id: mission
  type: ocp/BasicMission
  config:
    aircraft_template: caravan
    drag_source: external  # tells factory to skip internal PolarDrag

connections:
- src: wing-aero.wing_perf.CD
  tgt: mission.CD0
```

## Open Questions

- How to handle the OCP `drag_source: external` pattern -- the OCP aircraft
  model class always adds PolarDrag internally. Replacing it requires either
  a config flag that the factory respects, or post-setup connection overrides.
- Solver scoping: when two tools are composed, which Group gets the Newton
  solver? The plan YAML's `solvers:` section would need to support targeting
  specific subsystems.
- Variable promotion conflicts: OAS and OCP both promote `fltcond|*` at
  different levels. The materializer would need to namespace or selectively
  promote.
