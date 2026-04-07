# OCP Caravan Mission with OAS VLM Drag (Surrogate-Coupled)

First example of multi-tool coupling via the slot system. A Cessna Caravan
basic mission runs with OpenAeroStruct's VLM-based drag replacing the
default parabolic polar drag inside each flight phase.

## What this demonstrates

The uncoupled `oas_ocp_combined` example runs OAS and OCP side-by-side
as independent subsystems in one Problem. They share no data. That
proves the materializer can compose components, but it does not do
anything a human could not do by running two analyses separately.

This example uses the **slot system** to inject an OAS-derived drag
model inside the OCP mission. The slot mechanism -- provider lookup,
component substitution, data dict field management -- is fully general
and works correctly. That is the architectural point of this example.

## Coupling level: surrogate, not direct

OpenConcept's `VLMDragPolar` does **not** run VLM at every Newton
iteration. Instead it:

1. At initialization, runs a batch of OAS VLM analyses across a grid
   of Mach numbers and altitudes to build training data (~6-8 seconds)
2. Fits a surrogate model (interpolant) to that training data
3. At runtime, the surrogate is evaluated at each node -- the full VLM
   never runs inside the Newton loop

This is a deliberate design choice by OpenConcept for performance:
running the full VLM per-node per-iteration would be too slow for
mission analysis with many nodes. The result is higher fidelity than a
parabolic polar (the surrogate captures wing geometry effects) but is
not true tight coupling in the MDO sense.

The slot system supports three coupling levels:

| Level | What happens | Example |
|-------|-------------|---------|
| **Surrogate-coupled** | Train at init, interpolate at runtime | This example (`oas/vlm` slot using VLMDragPolar) |
| **Direct-coupled** | Upstream solver runs every iteration | Future: raw OAS AeroPoint slot provider |
| **Loose-coupled** | Pass data between independent components | `oas_ocp_combined` example (composite materializer) |

A direct-coupled drag slot provider that wraps raw OAS aero groups
(running VLM at every iteration) is a future work item. See
`TODO_future.md` for details.

## Setup

The plan YAML specifies a single `ocp/BasicMission` component with a
`slots.drag` section:

```yaml
components:
- id: mission
  type: ocp/BasicMission
  config:
    aircraft_template: caravan
    architecture: turboprop
    num_nodes: 11
    mission_params:
      cruise_altitude_ft: 18000
      mission_range_NM: 250
      ...
    slots:
      drag:
        provider: oas/vlm
        config:
          num_x: 2
          num_y: 7
          num_twist: 4
```

The OCP factory reads `config.slots.drag`, calls `get_slot_provider("oas/vlm")`,
and substitutes VLMDragPolar for PolarDrag in the aircraft model. The VLM
mesh configuration (num_x, num_y, num_twist) passes through to the
VLMDragPolar constructor.

The slot provider also modifies the aircraft data dictionary: it removes
the parabolic polar fields (`e`, `CD0_TO`, `CD0_cruise`) and adds
`CD_nonwing = 0.0145` for non-wing parasitic drag that the VLM does not
capture.

## Running the lanes

### Lane A: direct OpenConcept (reference)

Builds the OpenMDAO problem manually with VLMDragPolar wired into the
Caravan aircraft model. No omd dependency.

```bash
uv run python packages/omd/examples/ocp_oas_coupled/lane_a/coupled_mission.py
```

### Lane B: omd plan pipeline

Runs through the full omd pipeline: plan validation, materialization with
slot substitution, execution, recording.

```bash
omd-cli run packages/omd/examples/ocp_oas_coupled/lane_b/coupled_mission/plan.yaml
```

### Lane C: agent prompt

A prompt an agent can use to reproduce this analysis.

### Parity test

Verifies lane A and lane B produce matching results. Run with `-s` to see
a comparison table:

```bash
uv run pytest packages/omd/examples/tests/test_parity.py::TestOCPOASCoupledParity -v -s
```

## Expected results

| Metric    | Value    |
|-----------|----------|
| Fuel burn | ~137 kg  |
| OEW       | ~2267 kg |
| MTOW      | 3970 kg  |

The fuel burn is lower than the uncoupled Caravan basic mission (~165 kg)
because VLMDragPolar computes drag from a VLM-trained surrogate rather
than a hand-tuned parabolic polar. The two drag models use different
assumptions, so the numbers are not directly comparable. The point of
this example is the slot integration pattern, not the absolute values.

Note: the "Generating OpenAeroStruct aerodynamic training data..." message
during execution is VLMDragPolar building its surrogate at initialization.
This is upstream OpenConcept behavior, not an omd operation.
