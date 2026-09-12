# avy tool reference

Parameter reference for the Aviary MCP tools. Aviary (NASA) couples aircraft
sizing (FLOPS/GASP legacy methods) with dymos mission trajectory optimization
on OpenMDAO. Every analysis run is a driver run.

## load_aircraft_template

| Parameter | Type | Default | Notes |
|---|---|---|---|
| template | str | required | See list_aircraft_templates. energy_state decks are runnable; 2DOF decks are listed but rejected by analysis. |
| name | str | "aircraft" | Registry name used by all subsequent calls |
| session_id | str | "default" | |

Templates (deck paths resolve inside the installed aviary package):

- `advanced_single_aisle` -- N3CC-like advanced single aisle, FLOPS, energy_state
- `large_single_aisle_FLOPS` -- 737-800 class, FLOPS, energy_state
- `large_single_aisle_2_FLOPS` -- second large single-aisle variant
- `bench_FwFm` / `bench_GwFm` -- upstream benchmark decks (energy_state)
- `large_single_aisle_GASP`, `small_single_aisle_GASP` -- 2DOF decks (not yet runnable)

## define_aircraft

Overrides accumulate; values apply to the deck's AviaryValues at run time.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| aircraft_name | str | "aircraft" | |
| overrides | dict | None | `{name: value}` or `{name: [value, units]}`. Names use the `aircraft:wing:span` hierarchy and are validated against Aviary's variable metadata with close-match suggestions. Bare values use the metadata default units. |

Common variables: `aircraft:wing:aspect_ratio`, `aircraft:wing:area` (ft**2),
`aircraft:crew_and_payload:num_passengers`, `aircraft:design:gross_mass` (lbm),
`aircraft:design:range` (nmi).

## configure_mission

Builds the phase_info from the mission-method default (energy_state:
climb/cruise/descent) plus overrides. Re-calling rebuilds from defaults.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| aircraft_name | str | "aircraft" | |
| mission_method | str | "energy_state" | Only energy_state currently |
| mission_template | str | "energy_state_default" | Upstream phase_info to start from (below) |
| target_range_nm | float | None | Sets constrain_range + target_range |
| include_takeoff | bool | None | Detailed takeoff phase in pre_mission |
| include_landing | bool | None | Detailed landing phase in post_mission |
| phase_options | dict | None | Per-phase user_options overrides, validated against the template |

Mission templates (phase_info sources; all energy_state):

| Template | Source | SLSQP? |
|---|---|---|
| `energy_state_default` | aviary default 3-phase mission | yes |
| `bwb_fixed` | BWB benchmark mission, fixed profile (hangar adaptation) | yes (~12 s) |
| `advanced_single_aisle` | the model's own mission (takeoff, mach-optimized) | NO -- IPOPT/SNOPT |
| `GwFm_bench` | upstream GwFm benchmark mission (GASP decks) | NO -- IPOPT/SNOPT |
| `bwb_bench` | upstream BWB benchmark mission (profile-optimized) | NO -- IPOPT/SNOPT |

phase_options example:

```json
{"cruise": {"num_segments": 3, "mach_final": 0.75},
 "climb": {"altitude_final": [35000, "ft"]}}
```

Options with (value, units) defaults accept a bare number (default units
kept) or a `[value, units]` pair. Unknown phase or option names error with
suggestions. Key per-phase options: `num_segments`, `order`,
`mach_initial/final/bounds/optimize`, `altitude_initial/final/bounds/optimize`,
`throttle_enforcement`, `time_duration_bounds`.

## run_sizing

| Parameter | Type | Default | Notes |
|---|---|---|---|
| aircraft_name | str | "aircraft" | |
| optimizer | str | "SLSQP" | IPOPT/SNOPT need pyoptsparse (clear error when absent) |
| max_iter | int | 50 | [1, 500] |
| run_name | str | None | Label |

Runtime: ~20 s for the default 3-phase mission with SLSQP; minutes for
missions with takeoff/landing or more segments.

Results envelope:

- `results.performance` -- `gross_mass_lbm`, `total_fuel_mass_lbm`,
  `fuel_burned_lbm`, `operating_mass_lbm`, `zero_fuel_mass_lbm`,
  `final_mass_lbm`, `range_nmi`, `final_time_min`
- `results.design` -- `design_gross_mass_lbm`, `wing_area_ft2`, `wing_span_ft`
- `results.optimizer.success` -- CHECK THIS (also surfaced as the
  `optimizer.success` validation finding); non-convergence does not raise
- `results.timeseries` -- downsampled per-phase mission history
  (`time_s`, `altitude_ft`, `mach`, `mass_lbm`, `distance_nmi`, `throttle`,
  `phase`)

## run_off_design

Flies a mission with the sized design held fixed (design gross mass and
empty mass from the sizing). Re-runs the sizing internally (~2x run_sizing
wall-clock; no live problem is cached in the session).

| Parameter | Type | Default | Notes |
|---|---|---|---|
| aircraft_name | str | "aircraft" | |
| mission_type | str | "max_range" | 'max_range' (fixed fuel, maximize range) or 'min_fuel' (fixed range, minimize fuel) |
| mission_range_nm | float | None | REQUIRED for 'min_fuel'; unused otherwise |
| mission_gross_mass_lbm | float | None | Mission TOGM; defaults to design gross mass |
| cargo_mass_lbm | float | None | Cargo override for this mission |
| num_pax | int | None | Passenger count override |
| optimizer / max_iter | | SLSQP / 50 | Same semantics as run_sizing |

Results describe the off-design mission; the sizing headline metrics are
attached under `results.design_point` (check its `optimizer_success` too).

## run_payload_range

Runs the sizing plus two extra off-design missions to produce the 4-point
payload-range diagram (max payload @ 0 range, design mission, max fuel +
payload, ferry range). ~3x run_sizing wall-clock; energy_state only;
reserve fuel not yet accounted for (upstream limitation). Errors if the
sizing did not converge.

Results: `results.payload_range.points` = `[{label, payload_lbm,
range_nmi}, ...]` plus the sizing performance block.

## visualize

| plot_type | Shows |
|---|---|
| mission_profile | altitude, Mach, mass, throttle vs range (2x2, phase-colored) |
| mass_breakdown | gross / zero-fuel / operating / fuel bars |
| performance_summary | table card of all key sizing metrics |
| payload_range | 4-point payload-range diagram (run_payload_range artifacts) |

## Requirements paths (set_requirements)

Dot paths into results, e.g. `performance.gross_mass_lbm`,
`performance.total_fuel_mass_lbm`, `performance.final_time_min`.
