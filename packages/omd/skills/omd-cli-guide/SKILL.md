---
name: omd-cli-guide
description: >
  How to run MDAO analyses using the omd-cli command-line tool. Use this skill
  whenever the user asks you to assemble a plan, run an analysis or optimization,
  query results, view provenance, or export a standalone script via omd.
---

# omd CLI Guide

omd materializes YAML analysis plans into OpenMDAO problems, runs them, and
records results with PROV-Agent provenance tracking.

## Prerequisites

```bash
uv sync
uv run omd-cli --help
```

## Commands Overview

| Command | Purpose |
|---------|---------|
| `omd-cli assemble <plan_dir>` | Merge modular YAML files into canonical plan.yaml |
| `omd-cli validate <plan.yaml>` | Check plan against JSON Schema |
| `omd-cli run <plan.yaml>` | Materialize and execute (analysis or optimize) |
| `omd-cli results <run_id>` | Query results from analysis DB |
| `omd-cli export <plan.yaml>` | Generate standalone Python script |
| `omd-cli provenance <plan_id>` | View provenance timeline or DAG |
| `omd-cli viewer` | Start interactive Cytoscape.js provenance viewer |

## Plan Directory Structure

```
my-plan/
  metadata.yaml              # id, name (version auto-set)
  components/
    wing.yaml                 # id, type, config
  operating_points.yaml       # flight conditions
  solvers.yaml                # nonlinear + linear solver config (optional)
  optimization.yaml           # DVs, constraints, objective, optimizer (optional)
  decisions.yaml              # agent decision log (optional but recommended)
```

## Component Types

| Type | Description |
|------|-------------|
| `paraboloid/Paraboloid` | Trivial test component: f(x,y) |
| `oas/AeroPoint` | OAS aero-only VLM analysis |
| `oas/AerostructPoint` | OAS coupled aero+struct analysis |
| `oas/AerostructMultipoint` | OAS multipoint aerostruct (cruise + maneuver) |
| `ocp/BasicMission` | OpenConcept 3-phase mission (climb/cruise/descent) |
| `ocp/FullMission` | OpenConcept full mission with balanced-field takeoff |
| `ocp/MissionWithReserve` | OpenConcept mission with reserve + loiter phases |

## Slot Providers

Slots allow substituting components inside a factory's model. Currently
supported for OCP mission components (drag slot):

| Provider | Slot | Description |
|----------|------|-------------|
| `oas/vlm` | drag | VLMDragPolar (surrogate-trained VLM drag) |
| `oas/aerostruct` | drag | AerostructDragPolar (surrogate-trained aero+struct drag) |

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

The slot provider replaces the default drag model (PolarDrag) inside each
flight phase. It also modifies the aircraft data dict: removes parabolic
polar fields and adds any fields the provider needs (e.g., CD_nonwing).

## Quick Start

```bash
# 1. Create a plan directory with YAML files
# 2. Assemble
omd-cli assemble my-plan/

# 3. Run
omd-cli run my-plan/plan.yaml --mode analysis

# 4. View results
omd-cli results <run_id> --summary

# 5. Check provenance
omd-cli provenance <plan_id> --format text
```

## Data Artifacts

All runtime data is stored in `hangar_data/omd/` (configurable via `OMD_DATA_ROOT`).
**Do not delete this directory** -- it is the persistent archive of all runs and plans.

| Path | Contents | Created by |
|------|----------|------------|
| `analysis.db` | SQLite provenance + run case database | `run`, `assemble` |
| `plans/{plan-id}/v{N}.yaml` | Assembled plan versions (persistent archive) | `assemble`, `run` |
| `recordings/{run-id}.sql` | OpenMDAO recorder output files | `run` |
| `n2/{run-id}.html` | N2/DSM diagrams | `run` |
| `plots/{run-id}/*.png` | Visualization PNGs | `plot` |

Plans are automatically copied to the plan store on both `assemble` and `run`.
This ensures the plan artifact is preserved even if the original file is in a
temporary or working directory. The `storage_ref` in the provenance DB always
points to the store copy.

**Environment variables:**
| Variable | Default | Purpose |
|----------|---------|---------|
| `OMD_DATA_ROOT` | `hangar_data/omd` | Root for all omd runtime data |
| `OMD_DB_PATH` | `{OMD_DATA_ROOT}/analysis.db` | Analysis database path |
| `OMD_PLAN_STORE` | `{OMD_DATA_ROOT}/plans` | Plan archive directory |
| `OMD_RECORDINGS_DIR` | `{OMD_DATA_ROOT}/recordings` | Recorder files |

## Decision Logging (Required)

Agents MUST record decisions at these points in every omd workflow:

| When | Decision Type | What to Log |
|------|--------------|-------------|
| After choosing mesh/fidelity | `formulation_decision` | Mesh resolution, solver choice, why this fidelity |
| After each analysis run | `result_interpretation` | Key metrics, whether results are physically reasonable |
| Before optimization | `dv_selection` | Which DVs, bounds, and why; constraint rationale |
| After optimization | `convergence_assessment` | Iterations, constraint satisfaction, whether to accept |
| On replan | `replan_reasoning` | What failed, diagnosis, what changed in the new version |

For MCP workflows, use `log_decision()`. For CLI workflows, add entries to
`decisions.yaml` in the plan directory before re-assembling.

**decisions.yaml format:**
```yaml
- decision_type: formulation_decision
  agent: have-agent
  reasoning: "num_y=7 for quick iteration; tube FEM for weight estimation"
  selected_action: "Proceed with low-fidelity mesh"
- decision_type: result_interpretation
  agent: have-agent
  reasoning: "CL=0.45, CD=0.035, L/D=12.9 -- consistent with rectangular wing at M=0.84"
  selected_action: "Accept baseline; proceed to optimization"
```

See `commands.md` for full parameter reference and `examples/` for workflows.
