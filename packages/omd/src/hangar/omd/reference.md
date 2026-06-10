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
