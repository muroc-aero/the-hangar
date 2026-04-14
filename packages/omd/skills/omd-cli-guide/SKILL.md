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

## Study Directory Convention

New plans go under `hangar_studies/<descriptive-name>/`. This directory is
gitignored (like `hangar_data/`) so working files stay local. Never write
plan files to `/tmp` or other locations outside the repo.

```bash
# Example: create a new study
mkdir -p hangar_studies/regional-28m-opt/components
```

## Plan Directory Structure

```
hangar_studies/my-plan/
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

## OAS Mesh Conventions

When using OAS components (`oas/AeroPoint`, `oas/AerostructPoint`,
`oas/AerostructMultipoint`) with `symmetry: true`:

- **`span`** is the **full** wingspan. OAS halves it internally to mesh
  the half-span. For a 28m wing, set `span: 28.0`, not `span: 14.0`.
- **`num_y`** is the **full-span** node count. OAS halves it for the
  half-span mesh. `num_y: 21` with symmetry gives 11 half-span nodes.
  Must be odd.
- **`num_x`** is the chordwise node count. Not affected by symmetry.

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

## Wingbox Multipoint Optimization

For `oas/AerostructMultipoint` wingbox problems (following the upstream
Q400 example pattern):

**Required design variables:**
- `twist_cp` (scaler=0.1)
- `spar_thickness_cp` (scaler=100)
- `skin_thickness_cp` (scaler=100)
- `t_over_c_cp` (scaler=10) -- controls wave drag vs fuel volume vs weight
- `fuel_mass` (scaler=1e-5) -- required to close the `fuel_diff=0` constraint
- `alpha_maneuver` -- trim angle at maneuver point

**Recommended constraint formulation:**
- `AS_point_0.CL` equals target (e.g., 0.5) -- cruise trim via CL target
- `AS_point_1.L_equals_W` equals 0.0 -- maneuver lift = weight
- `AS_point_1.wing_perf.failure` upper 0.0 -- structural failure at maneuver only (binding case)
- `fuel_vol_delta` lower 0.0 -- fuel fits in wingbox
- `fuel_diff` equals 0.0 -- fuel mass consistency

**Surface config keys for wingbox:**
```yaml
struct_weight_relief: true    # wing weight provides load relief
distributed_fuel_weight: true # fuel distributed along span
exact_failure_constraint: false
wing_weight_ratio: 1.25       # secondary structure factor
```

**Objective:** `fuelburn` with `scaler: 1.0e-5`

**Optimizer:** SLSQP with `ftol: 1.0e-4` typically converges in 10-15
iterations when the formulation follows this pattern.

## Unit Conventions

omd assumes SI units by default for operating points and results unless
a component type documents otherwise.

| Component Family | Assumed Units |
|-----------------|---------------|
| OAS (oas/*) | SI: velocity in m/s, density (rho) in kg/m^3, angles in deg, lengths in m |
| OCP (ocp/*) | Mixed: mission_params use suffixed names -- `cruise_altitude_ft` (feet), `mission_range_NM` (nautical miles), `climb_vs_ftmin` (ft/min), `climb_Ueas_kn` (knots). Results are returned in kg for mass, m for distance. |

Operating point values can optionally include units:

```yaml
operating_points:
  velocity: 248               # bare number, assumed m/s
  altitude:                    # explicit units
    value: 35000
    units: ft
```

Design variables, constraints, and objectives support an optional `units` field
that is passed directly to OpenMDAO:

```yaml
design_variables:
- name: twist_cp
  lower: -10
  upper: 10
  units: deg
```

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

Agents MUST record decisions at key points in every omd workflow. There are
two mechanisms depending on context:

### CLI vs MCP Decision Logging

| Context | Mechanism | Storage |
|---------|-----------|---------|
| **CLI workflow** (`omd-cli`) | Add entries to `decisions.yaml` in the plan directory, then re-assemble | Persisted in the assembled plan YAML and plan store |
| **MCP workflow** (interactive) | Call `log_decision()` tool | Recorded in the SDK provenance DB with session context |

Use `decisions.yaml` when building plans from files. Use `log_decision()` when
working interactively through MCP tool calls. Both produce provenance records,
but through different paths.

### Decision Types

| Type | When | What to Log |
|------|------|-------------|
| `formulation_decision` | After choosing mesh, fidelity, solver | Mesh resolution (num_y, num_x), solver type, why this fidelity level was chosen |
| `result_interpretation` | After each analysis run | Specific metric values (CL, CD, L/D, mass), whether they are physically reasonable, comparison to expectations |
| `dv_selection` | Before optimization | Which DVs were chosen and why, bound rationale, constraint selection |
| `convergence_assessment` | After optimization | Iteration count, constraint satisfaction, whether result is accepted or needs rerun |
| `replan_reasoning` | When changing approach | What failed, root cause diagnosis, what changed in the new plan version |

### CLI Workflow: Step by Step

1. Create the plan directory with component YAML files
2. **Log formulation decision** -- add an entry to `decisions.yaml` explaining
   mesh/solver choices
3. Run `omd-cli assemble my-plan/` to produce `plan.yaml`
4. Run `omd-cli run plan.yaml --mode analysis`
5. **Log result interpretation** -- add an entry to `decisions.yaml` with
   specific values from the run output
6. Run `omd-cli assemble my-plan/` again to capture the new decision
7. If optimizing: **log dv_selection** before, **log convergence_assessment** after
8. If replanning: **log replan_reasoning** explaining what changed and why

### Agent Checklist

Before running analysis:
- [ ] Log `formulation_decision` with mesh density, solver, and fidelity rationale

After running analysis:
- [ ] Log `result_interpretation` with specific numeric values and physics reasoning

Before running optimization:
- [ ] Log `dv_selection` with DV names, bounds, and constraint choices

After running optimization:
- [ ] Log `convergence_assessment` with iteration count and constraint status

On any replan:
- [ ] Log `replan_reasoning` with failure diagnosis and changes made

### decisions.yaml: Good vs Insufficient Examples

**Good entry** -- specific values, physics reasoning, actionable conclusion:
```yaml
- decision_type: result_interpretation
  agent: have-agent
  reasoning: >
    CL=0.45, CD=0.035, L/D=12.9 at M=0.84, alpha=5 deg.
    CD is consistent with a rectangular wing at this Mach number
    (wave drag onset near M=0.85). Structural mass 1,247 kg with
    failure=-0.12 (safe, 12% margin below yield). L/D of 12.9 is
    reasonable for an unswept rectangular planform.
  selected_action: "Accept baseline results; proceed to twist optimization"
```

**Insufficient entry** -- vague, no numbers, no physics reasoning:
```yaml
- decision_type: result_interpretation
  agent: have-agent
  reasoning: "Results look reasonable"
  selected_action: "Proceed"
```

The difference: a good entry lets someone (or a future agent) understand
*why* the results were accepted without re-running the analysis.

See `commands.md` for full parameter reference and `examples/` for workflows.
