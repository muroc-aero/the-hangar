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
| `omd-cli plan init <dir>` | Scaffold a new plan directory (metadata.yaml only) |
| `omd-cli plan add-component <dir>` | Add a component YAML (flag-driven or `--interactive`) |
| `omd-cli plan add-requirement <dir>` | Append a requirement to `requirements.yaml` |
| `omd-cli plan add-dv <dir>` | Add a design variable to `optimization.yaml` (validates short name) |
| `omd-cli plan set-objective <dir>` | Set the optimization objective |
| `omd-cli plan add-decision <dir>` | Append a hand-authored decision entry |
| `omd-cli plan set-operating-point <dir>` | Merge flight-condition fields into `operating_points.yaml` |
| `omd-cli plan set-solver <dir>` | Write `solvers.yaml` (nonlinear + linear) |
| `omd-cli plan set-analysis-strategy <dir>` | Scaffold `analysis_plan.yaml` with N phases |
| `omd-cli plan review <dir-or-yaml>` | Report completeness gaps (requirements, decisions, analysis_plan, graph) |

Full subcommand flags and behavior: `commands.md`.

## Companion Files

Load these on demand; `SKILL.md` is the index:

| Topic | File | When to load |
|-------|------|-------------|
| Command reference | `commands.md` | Need flags, options, or behavior for a specific subcommand |
| Plan authoring (builder, decisions, requirements, analysis_plan, review) | `plan-authoring.md` | Authoring a plan; logging decisions; writing requirements with acceptance criteria; scaffolding phased strategies; running completeness checks; `shared_vars` and `composition_policy: auto` |
| Replan workflow (diagnose, fix, re-assemble, compare) | `replan.md` | A run failed, didn't converge, hit infeasibility, returned NaN, or produced unphysical results; recording the replan decision and following the version chain |
| Factory contracts (produces/consumes for auto-shared vars) | `factory-contracts.md` | Adding a new factory, modifying `FactoryContract` declarations, or debugging auto-derivation under `composition_policy: auto` |
| Slots and fidelity (drag, propulsion, weight providers) | `slots-and-fidelity.md` | Composing OCP missions with VLM drag or pyCycle propulsion; choosing between surrogate and direct-coupled providers |
| OAS specifics (mesh, wingbox multipoint) | `oas-specifics.md` | Building any `oas/AeroPoint`, `oas/AerostructPoint`, or `oas/AerostructMultipoint` plan |
| OCP specifics (custom aircraft data, solver settings) | `ocp-specifics.md` | Defining inline `aircraft_data` instead of a template; tuning OCP mission solver settings |
| pyCycle specifics (operating points, plot types) | `pycycle-specifics.md` | Running any `pyc/*` design or multipoint plan |
| Example workflows | `examples/` | `oas_aero_workflow.md`, `oas_aerostruct_workflow.md`, `paraboloid_workflow.md` — end-to-end worked examples |

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
  requirements.yaml           # requirements with acceptance_criteria (optional)
  decisions.yaml              # agent decision log (optional but recommended)
  analysis_plan.yaml          # process: strategy, phases, checks (optional)
  rationale.yaml              # short high-level rationale list (optional)
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
| `pyc/TurbojetDesign` | Single-spool turbojet design point |
| `pyc/TurbojetMultipoint` | Turbojet design + off-design points |
| `pyc/HBTFDesign` | Dual-spool high-bypass turbofan design point |
| `pyc/ABTurbojetDesign` | Afterburning turbojet design point |
| `pyc/SingleTurboshaftDesign` | Single-spool turboshaft design point |
| `pyc/MultiTurboshaftDesign` | Multi-spool turboshaft design point |
| `pyc/MixedFlowDesign` | Mixed-flow turbofan design point |

## Unit Conventions

omd assumes SI units by default for operating points and results
unless a component type documents otherwise.

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

Design variables, constraints, and objectives support an optional
`units` field that is passed directly to OpenMDAO:

```yaml
design_variables:
- name: twist_cp
  lower: -10
  upper: 10
  units: deg
```

## Quick Start

**Initial plans MUST be built with Path A (the interactive builder).**
This is the only path that records decisions as the plan is assembled,
which the decision-logging contract in `plan-authoring.md` requires.
Path B exists for derived uses (sweep cells patched from a base plan,
copies of an existing fixture, regenerating an assembled plan from
hand-edited YAML); do not use it for a fresh plan.

**Path A: interactive builder** (required for new plans; see
`plan-authoring.md`)

Use one `omd-cli plan` subcommand per choice and pass `--rationale`
on every one so a `decisions.yaml` entry is auto-appended. Add hand-
authored decisions with `plan add-decision` for any choice that
isn't covered by an `add-*` / `set-*` primitive (mesh resolution,
formulation framing, replan reasoning). After the run, append a
`result_interpretation` decision and re-assemble before treating the
plan as final.

```bash
omd-cli plan init hangar_studies/my-plan --id my-plan --name "My study"
omd-cli plan add-component hangar_studies/my-plan \
    --id wing --type oas/AerostructPoint --config-file wing.yaml \
    --rationale "Baseline wing geometry"
omd-cli plan set-operating-point hangar_studies/my-plan \
    --mach 0.84 --alpha 5.0 --rationale "Cruise design point"
omd-cli plan add-dv hangar_studies/my-plan \
    --name twist_cp --lower -10 --upper 15 \
    --rationale "Conservative envelope"
omd-cli plan set-objective hangar_studies/my-plan \
    --name structural_mass --rationale "Primary goal"
omd-cli plan add-decision hangar_studies/my-plan \
    --stage mesh_selection --decision "num_y=7" \
    --rationale "Moderate fidelity for exploration"
omd-cli plan review hangar_studies/my-plan
omd-cli assemble hangar_studies/my-plan
omd-cli run hangar_studies/my-plan/plan.yaml --mode analysis
# Append a result_interpretation decision, then re-assemble.
```

**Path B: hand-authored YAML** (reserved for derived uses — sweep
cells patched from a base plan, copies of an existing fixture, or
regenerating an assembled plan from hand-edited modular YAML; not
for a brand-new plan)

```bash
# 1. Start from an existing plan directory or fixture
# 2. Assemble
omd-cli assemble my-plan/

# 3. Run
omd-cli run my-plan/plan.yaml --mode analysis

# 4. View results
omd-cli results <run_id> --summary

# 5. Check provenance
omd-cli provenance <plan_id> --format text
```

## Range-Safety Integration

`range-safety` is a separate CLI in this monorepo that enforces
catalog-level structural and traceability rules and post-run
constraint satisfaction. Use it as standard pre-flight and assertion
gates around `omd-cli run`:

```bash
# Pre-flight: validate the assembled plan against catalog and heuristics
range-safety validate hangar_studies/my-plan/plan.yaml

# Run
omd-cli run hangar_studies/my-plan/plan.yaml --mode optimize

# Post-run: assert convergence + constraint satisfaction
range-safety assert <run_id> --plan hangar_studies/my-plan/plan.yaml
```

`validate` errors must be fixed before running; warnings should be
addressed or justified in `decisions.yaml`. `assert` failure is a
trigger to enter the replan workflow (see `replan.md`).

## Data Artifacts

All runtime data is stored in `hangar_data/omd/` (configurable via
`OMD_DATA_ROOT`). **Do not delete this directory** -- it is the
persistent archive of all runs and plans.

| Path | Contents | Created by |
|------|----------|------------|
| `analysis.db` | SQLite provenance + run case database | `run`, `assemble` |
| `plans/{plan-id}/v{N}.yaml` | Assembled plan versions (persistent archive) | `assemble`, `run` |
| `recordings/{run-id}.sql` | OpenMDAO recorder output files | `run` |
| `n2/{run-id}.html` | N2/DSM diagrams | `run` |
| `plots/{run-id}/*.png` | Visualization PNGs | `plot` |

Plans are automatically copied to the plan store on both `assemble`
and `run`. This ensures the plan artifact is preserved even if the
original file is in a temporary or working directory. The
`storage_ref` in the provenance DB always points to the store copy.

**Environment variables:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `OMD_DATA_ROOT` | `hangar_data/omd` | Root for all omd runtime data |
| `OMD_DB_PATH` | `{OMD_DATA_ROOT}/analysis.db` | Analysis database path |
| `OMD_PLAN_STORE` | `{OMD_DATA_ROOT}/plans` | Plan archive directory |
| `OMD_RECORDINGS_DIR` | `{OMD_DATA_ROOT}/recordings` | Recorder files |
