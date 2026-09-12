# Commands Reference

All tools, one-shot subcommand names, and key parameters. Every tool is
also callable in interactive/script mode by its Python name. Invoke via
`.venv-avy/bin/avy-cli` (see SKILL.md).

## Aircraft definition

| Tool | Subcommand | Key parameters |
|------|------------|----------------|
| `list_aircraft_templates` | `list-aircraft-templates` | -- |
| `load_aircraft_template` | `load-aircraft-template` | `--template`, `--name` (default "aircraft") |
| `define_aircraft` | `define-aircraft` | `--aircraft-name`, `--overrides` (JSON dict: `{name: value}` or `{name: [value, units]}`) |
| `configure_mission` | `configure-mission` | `--aircraft-name`, `--target-range-nm`, `--include-takeoff/--include-landing`, `--phase-options` (JSON dict) |
| `list_external_subsystems` | `list-external-subsystems` | -- |
| `add_external_subsystem` | `add-external-subsystem` | `--aircraft-name`, `--subsystem` (`oas_wing_mass`), `--config` (JSON dict) |

Templates: `advanced_single_aisle`, `large_single_aisle_FLOPS`,
`large_single_aisle_2_FLOPS`, `bench_FwFm`, `bench_GwFm` (runnable,
energy_state) plus `large_single_aisle_GASP`, `small_single_aisle_GASP`
(2DOF -- listed but rejected by analysis).

Override names use the `aircraft:wing:span` hierarchy and are validated
against Aviary's metadata (typos error with close matches). Common ones:
`aircraft:wing:aspect_ratio`, `aircraft:wing:area` (ft**2),
`aircraft:design:gross_mass` (lbm), `aircraft:design:range` (nmi).

## Analysis

| Tool | Subcommand | Key parameters |
|------|------------|----------------|
| `run_sizing` | `run-sizing` | `--aircraft-name`, `--optimizer` (SLSQP), `--max-iter` (50), `--subsystem-mode` (`coupled`/`precompute`; only matters with a subsystem attached), `--run-name` |
| `run_off_design` | `run-off-design` | + `--mission-type` (`max_range`/`min_fuel`), `--mission-range-nm` (REQUIRED for min_fuel), `--mission-gross-mass-lbm`, `--cargo-mass-lbm`, `--num-pax` |
| `run_payload_range` | `run-payload-range` | `--aircraft-name`, `--optimizer`, `--max-iter`, `--run-name` |

All three return the versioned envelope. ALWAYS check
`result.validation.passed` -- optimizer non-convergence does not raise.

External subsystems: `add_external_subsystem` attaches `oas_wing_mass`
(upstream Aviary's OpenAeroStruct wingbox integration -- a nested ~40 s
sub-optimization whose wing mass replaces the FLOPS estimate on
`Aircraft.Wing.MASS`). It then joins every analysis run for that
aircraft. `run_sizing --subsystem-mode precompute` runs the sub-opt once
up front and applies the result as a deck override (equivalent for this
feed-forward subsystem, cheaper across repeat runs). Config highlights:
`cruise_mach`, `fuel_lbm` (null = deck-driven), `num_box_cp`/`sub_opt_*`
(smoke knobs), `planform` (null = upstream single-aisle mesh, `"deck"` =
derive a simple trapezoid from the deck's span/area/taper/sweep, or an
explicit planform dict). Check the `subsystem.deck_scope` and
`subsystem.wing_mass_applied` findings; the OAS wing mass lands in
`results.design.wing_mass_lbm`.

Key result paths:

- `results.performance.{gross_mass_lbm, total_fuel_mass_lbm, fuel_burned_lbm,`
  `range_nmi, final_time_min, operating_mass_lbm, zero_fuel_mass_lbm}`
- `results.design.{design_gross_mass_lbm, wing_area_ft2, wing_span_ft}`
- `results.optimizer.success`
- `results.timeseries.{time_s, altitude_ft, mach, mass_lbm, distance_nmi, throttle, phase}`
- run_off_design only: `results.design_point` (the sizing headline metrics)
- run_payload_range only: `results.payload_range.points`

## Visualization

| Tool | Subcommand | Key parameters |
|------|------------|----------------|
| `visualize` | `visualize` | `--run-id`, `--plot-type`, `--output` (`inline`/`file`/`url`), `--case-name` |

Plot types: `mission_profile`, `mass_breakdown`, `performance_summary`,
`payload_range` (payload-range artifacts only). Use `--output file` from
the CLI (inline base64 is for MCP clients).

## Session, artifacts, observability

| Tool | Subcommand |
|------|------------|
| `configure_session` | `configure-session` |
| `set_requirements` | `set-requirements` |
| `record_conclusion` | `record-conclusion` |
| `reset` | `reset` |
| `list_artifacts` / `get_artifact` / `get_artifact_summary` / `delete_artifact` | `list-artifacts` / `get-artifact` / `get-artifact-summary` / `delete-artifact` |
| `get_run` / `get_detailed_results` / `get_last_logs` | `get-run` / `get-detailed-results` / `get-last-logs` |
| `pin_run` / `unpin_run` | `pin-run` / `unpin-run` |

Requirements paths are dot paths into results, e.g.
`performance.gross_mass_lbm`.

## Provenance

| Tool | Subcommand |
|------|------------|
| `start_session` | `start-session` |
| `log_decision` | `log-decision` |
| `link_cross_tool_result` | `link-cross-tool-result` |
| `export_session_graph` | `export-session-graph` |

See `provenance.md` for the decision-logging contract.
