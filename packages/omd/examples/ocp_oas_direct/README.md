# OCP Caravan Mission with OAS VLM Drag (Direct-Coupled)

Second coupled multi-tool example. Like `ocp_oas_coupled`, this injects
OAS-derived drag inside the OCP mission via the slot system. The
difference is the coupling level: here the full VLM solver runs at every
Newton iteration rather than a pre-trained surrogate.

## What this demonstrates

The `ocp_oas_coupled` example uses `oas/vlm` (VLMDragPolar), which
pre-trains a surrogate at initialization and interpolates at runtime.
The VLM never runs inside the Newton loop.

This example uses `oas/vlm-direct` (DirectVLMDragGroup), which wraps
raw OAS `VLM` groups. Each of the `nn` flight-condition nodes gets its
own OAS atmosphere + AeroPoint instance, and a BalanceComp drives alpha
to match the requested CL. The parent Newton solves everything
simultaneously.

| Property | `oas/vlm` (surrogate) | `oas/vlm-direct` (this example) |
|----------|----------------------|---------------------------------|
| VLM runs | At init only (training grid) | Every Newton iteration |
| Accuracy | Interpolation error from surrogate | Exact VLM result |
| Partials | Through surrogate (approximate) | Through VLM (analytic) |
| Runtime  | Seconds (after ~6s training) | Minutes (VLM per node per iter) |
| Best for | Mission analysis | Optimization with aero DVs |

## Coupling level: direct

The slot provider creates `nn` independent VLM instances sharing a
single twisted mesh. A CL-alpha BalanceComp with `nn` residuals is
solved by the parent Newton. This is true tight coupling: changing wing
twist or flight conditions propagates through the VLM within the same
Newton convergence loop.

## Setup

The plan YAML specifies `oas/vlm-direct` instead of `oas/vlm`:

```yaml
slots:
  drag:
    provider: oas/vlm-direct
    config:
      num_x: 2
      num_y: 5
      num_twist: 4
```

The mesh is coarser than the surrogate example (num_y=5 vs 7) to keep
per-iteration cost manageable.

## Running the lanes

### Lane A: direct reference

Builds the OpenMDAO problem manually with DirectVLMDragGroup wired into
the Caravan aircraft model. No omd dependency beyond the slot group.

```bash
uv run python packages/omd/examples/ocp_oas_direct/lane_a/direct_coupled_mission.py
```

### Lane B: omd plan pipeline

Runs through the full omd pipeline with the `oas/vlm-direct` slot.

```bash
omd-cli run packages/omd/examples/ocp_oas_direct/lane_b/direct_coupled_mission/plan.yaml
```

### Lane C: agent prompt

A prompt an agent can use to reproduce this analysis.

### Parity test

Verifies lane A and lane B produce matching results:

```bash
uv run pytest packages/omd/tests/test_eval_direct_coupled.py -v -s
```
