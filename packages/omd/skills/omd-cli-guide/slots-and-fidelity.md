# Slots and Fidelity

Deep-dive companion to `SKILL.md` covering slot providers, the
trade-off between surrogate and direct-coupled providers, and the
`pyc/surrogate` propulsion deck configuration.

## Slot Providers

Slots allow substituting components inside a factory's model.
Currently supported for OCP mission components (drag, propulsion,
weight slots):

| Provider | Slot | Description |
|----------|------|-------------|
| `oas/vlm` | drag | VLMDragPolar (surrogate-trained VLM drag) |
| `oas/vlm-direct` | drag | Direct-coupled VLM drag (accurate, expensive) |
| `oas/aerostruct` | drag | AerostructDragPolar (surrogate aero+struct, outputs wing weight) |
| `pyc/turbojet` | propulsion | Direct-coupled pyCycle turbojet |
| `pyc/hbtf` | propulsion | Direct-coupled pyCycle HBTF turbofan |
| `pyc/surrogate` | propulsion | Kriging surrogate from pyCycle off-design sweep (fast, no convergence risk) |
| `ocp/parametric-weight` | weight | Parametric OEW = sum of component weights |

Slots are specified in the component config:

```yaml
components:
- id: mission
  type: ocp/BasicMission
  config:
    aircraft_template: caravan
    architecture: turboprop
    num_nodes: 11
    mission_params: { ... }
    slots:
      drag:
        provider: oas/vlm
        config:
          num_x: 2
          num_y: 7      # must be odd
          num_twist: 4
```

The slot provider replaces the default drag model (PolarDrag) inside
each flight phase. It also modifies the aircraft data dict: removes
parabolic polar fields and adds any fields the provider needs (e.g.,
CD_nonwing).

## Surrogate vs Direct-Coupled

Slot providers come in two flavors:

**Surrogate-coupled** (`oas/vlm`, `oas/aerostruct`, `pyc/surrogate`):
Build a response surface offline, then evaluate cheaply during mission
analysis. Fast (~1ms per node), no convergence risk. Use NLBGS solver
when combining two surrogate slots (dual-surrogate Jacobian is
ill-conditioned for Newton).

**Direct-coupled** (`oas/vlm-direct`, `pyc/turbojet`, `pyc/hbtf`):
Native OpenMDAO Group runs inside the OCP mission solver. Analytic
partials, higher fidelity, but slower (~2s per node for pyCycle) and
requires Newton convergence. Use at least one direct-coupled provider
when combining drag + propulsion slots to avoid singular Jacobians.

## Surrogate Propulsion Config (`pyc/surrogate`)

The `pyc/surrogate` provider generates an off-design deck before
mission analysis. Config keys:

```yaml
slots:
  propulsion:
    provider: pyc/surrogate
    config:
      archetype: hbtf          # hbtf, turbojet
      design_alt: 35000        # design altitude (ft)
      design_MN: 0.78          # design Mach number
      design_Fn: 5500          # design net thrust (lbf)
      design_T4: 2850          # design T4 (degR)
      engine_params:
        thermo_method: TABULAR  # TABULAR recommended for surrogate stability
```

Deck generation runs a grid of off-design points across altitude,
Mach, and throttle. This can take several minutes for HBTF (many
Newton solves). The resulting Kriging surrogate is cached for the
session.
