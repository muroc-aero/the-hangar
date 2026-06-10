# omd MCP Server -- Parameter Reference

omd materializes YAML analysis plans into OpenMDAO problems, runs them, and
records results with PROV-Agent provenance. Every MCP tool calls the same
implementation as the matching `omd-cli` command, so the omd-cli guide
(`skills/omd-cli-guide/`) remains the authoritative deep reference for plan
authoring patterns, factory specifics, and worked examples. This document
covers what an MCP agent needs: the tool surface, plan workspace, component
types, and plot types.

## Plan workspace

MCP-only agents have no filesystem access, so relative paths in tool
arguments resolve into a server-side workspace (`hangar_data/omd/workspace`).
Two authoring styles:

- **Builder tools**: `plan_init` -> `plan_add_component` ->
  `plan_set_operating_point` -> (`plan_add_dv` + `plan_set_objective`) ->
  `assemble_plan`. Each mutation validates the partial plan and records a
  rationale decision.
- **Direct YAML**: compose the full plan yourself and `write_plan` it, then
  `validate_plan` / `run_plan` the written path. `read_plan` reads any plan
  file (or lists a plan directory) back.

## Tool surface (CLI parity)

| MCP tool | omd-cli equivalent |
|----------|--------------------|
| `validate_plan(plan_path, semantic)` | `omd-cli validate` |
| `assemble_plan(plan_dir, output)` | `omd-cli assemble` |
| `run_plan(plan_path, mode, recording_level, timeout_seconds, stability)` | `omd-cli run` |
| `run_polar(plan_path, alpha_start, alpha_end, num_alpha)` | `omd-cli polar` |
| `get_results(run_id, variables, summary)` | `omd-cli results` |
| `get_run_summary(run_id, regenerate_plots)` | `omd-cli summary` |
| `record_conclusion(run_id, narrative, plan_path)` | `omd-cli conclude` |
| `get_provenance(plan_id, format, diff_from, diff_to)` | `omd-cli provenance` |
| `export_plan(plan_path, output)` | `omd-cli export` |
| `generate_plots(run_id, plot_type, surface)` | `omd-cli plot` |
| `list_plot_types(run_id)` | `omd-cli plot --list-types` |
| `get_view_urls(run_id, plan_id)` | `omd-cli viewer` (URLs instead of a local server) |
| `plan_init` / `plan_add_component` / `plan_add_requirement` / `plan_add_dv` / `plan_set_objective` / `plan_set_operating_point` / `plan_set_solver` / `plan_set_analysis_strategy` / `plan_add_shared_var` / `plan_set_composition_policy` / `plan_add_decision` / `review_plan` | `omd-cli plan <subcommand>` |
| `write_plan` / `read_plan` | (workspace file access for MCP-only agents) |

## run_plan parameters

- `mode`: `analysis` (run the model once) or `optimize` (run the driver).
- `recording_level`: `minimal` (final values), `driver` (DVs + objective +
  constraints per iteration, default), `solver` (adds solver iterations),
  `full` (everything; large).
- `timeout_seconds`: wallclock abort.
- `stability`: also compute stability derivatives (OAS aero plans).
- Schema + semantic preflight runs automatically; typos in component types
  or DV/constraint/objective names fail fast with suggestions.

`run_polar` is the sweep mode: it sweeps angle of attack on an OAS plan and
returns `alpha_deg` / `CL` / `CD` / `L_over_D` arrays plus `best_L_over_D`.

## Component types (plan `components[].type`)

| Type | Description |
|------|-------------|
| `oas/AeroPoint` | OAS aero-only VLM analysis point |
| `oas/AerostructPoint` | OAS coupled aero + structures |
| `oas/AerostructMultipoint` | OAS aerostruct, multiple flight points |
| `ocp/BasicMission` | OpenConcept climb/cruise/descent mission |
| `ocp/FullMission` | OpenConcept mission with balanced-field takeoff |
| `ocp/MissionWithReserve` | OpenConcept mission + reserve/loiter |
| `pyc/TurbojetDesign`, `pyc/TurbojetMultipoint`, `pyc/HBTFDesign`, `pyc/ABTurbojetDesign`, `pyc/SingleTurboshaftDesign`, `pyc/MultiTurboshaftDesign`, `pyc/MixedFlowDesign` | pyCycle gas turbine cycles |
| `paraboloid/Paraboloid` | Trivial test component |

OCP components accept `slots` (drag/propulsion/weight providers such as
`oas/vlm`, `pyc/surrogate`, `pyc/hbtf`, `ocp/parametric-weight`) for
multi-tool composition. The factory availability depends on which optional
packages are installed; unknown types are reported by `validate_plan` with
suggestions.

## Component config keys (plan `components[].config`)

### `ocp/*` missions (closed set, validated by preflight)

Top-level config keys:

| Key | Meaning |
|-----|---------|
| `aircraft_template` | Built-in aircraft: `caravan`, `b738`, `kingair`, `tbm850` |
| `aircraft_data` | Inline aircraft data dict (alternative to a template) |
| `architecture` | `turboprop`, `twin_turboprop`, `series_hybrid`, `twin_series_hybrid`, `twin_turbofan` |
| `num_nodes` | Integration nodes per phase (must be odd; default 11) |
| `mission_params` | Mission profile dict, see below |
| `solver_settings` | Newton solver overrides (`maxiter`, `atol`, `rtol`, ...) |
| `propulsion_overrides` | Propulsion parameter overrides |
| `skip_fields` | Aircraft-data fields to omit |
| `include_cost_model` | Adds promoted `doc_per_nmi` trip cost |
| `slots` | Provider slots, see below |

`mission_params` keys carry units in their suffix (`_NM`, `_ft`,
`_ftmin`, `_kn`): `mission_range_NM`, `cruise_altitude_ft`,
`climb_vs_ftmin`, `climb_Ueas_kn`, `cruise_vs_ftmin`, `cruise_Ueas_kn`,
`descent_vs_ftmin`, `descent_Ueas_kn` (positive; negated internally),
`payload_lb`, `battery_specific_energy`, `<phase>_hybridization`;
`ocp/MissionWithReserve` adds `reserve_altitude_ft`,
`reserve_{climb,cruise,descent}_{vs_ftmin,Ueas_kn}`, `loiter_vs_ftmin`,
`loiter_Ueas_kn`; `ocp/FullMission` adds `v0v1_Utrue_kn`,
`v1vr_Utrue_kn`, `v1v0_Utrue_kn`, `rotate_Utrue_kn`.

Slot shape (per slot name `drag`, `propulsion`, `weight`, `maneuver`):

```yaml
config:
  slots:
    drag:
      provider: oas/vlm        # or oas/vlm-direct, pyc/surrogate, ...
      config:                  # provider-specific
        num_x: 2
        num_y: 7               # must be odd
        num_twist: 4
```

### Other factories

- `paraboloid/Paraboloid` takes **no config**; set run inputs (`x`, `y`)
  via `operating_points` (preflight rejects config keys here).
- `oas/*` config keys are forwarded to the OpenAeroStruct surface dict
  (`span`, `taper`, `sweep`, `dihedral`, `root_chord`, `num_x`, `num_y`,
  `num_twist_cp`, `wing_type`, `symmetry`, `fem_model_type`,
  `wing_weight_ratio`, `use_composite`, ... plus any valid OAS surface
  key); unknown keys are passed through, not validated.
- `pyc/*` config keys are the cycle parameters (`comp_PR`, `comp_eff`,
  `burner_FAR`, `turb_eff`, `nozz_Cv`, `initial_guesses`, ...); extras
  pass through to the cycle builder.

## DV / constraint / objective short names

The materializer resolves short names to full OpenMDAO paths per component
family, e.g. OAS: `twist_cp`, `chord_cp`, `alpha`, `CL`, `CD`, `S_ref`,
`failure`, `fuelburn`, `structural_mass`, `L_equals_W`; OCP:
pipe-separated `ac|geom|wing|S_ref` style paths plus `fuel_burn`, `MTOW`.
`plan_add_dv` and `plan_set_objective` validate names against the declared
components and list the allowed set on error.

## Plot types (`generate_plots`)

- Generic (all runs): `convergence`, `dv_evolution`, `n2` (HTML).
- OAS aero: `planform`, `lift`, `twist`, `mesh_3d`.
- OAS aerostruct adds: `struct`, `thickness`, `vonmises`, `skin_spar`,
  `t_over_c`.
- pyCycle: `station_properties`, `component_efficiency`.

`list_plot_types(run_id)` returns exactly what applies to a given run.

## Views and URLs

Tools that touch a run or plan return a `urls` block when a viewer is
reachable:

- `viewer` -- SDK provenance session viewer.
- `plan_provenance`, `plan_detail` -- plan DAG and plan knowledge graph.
- `problem_dag` -- interactive run view (discipline graph + plot links).
- `plots`, `n2` -- run plot gallery and N2 diagram.
- `range_safety_dashboard` -- study state-machine dashboard (requirements,
  plan diffs, reasoning, report); present when a dashboard instance is
  running (`RS_DASHBOARD_URL`).

## Response envelope

`run_plan` and `run_polar` return the versioned envelope
(`schema_version="1.0"`): `results`, `validation` (check `passed` before
trusting numbers), `telemetry`, `run_id`, and `error` with code
`USER_INPUT_ERROR` / `SOLVER_CONVERGENCE_ERROR` / `INTERNAL_ERROR` on
failure. An optimizer that converges in 1-2 iterations is flagged: it
usually means DV bounds are wrong or DVs are not being applied.
