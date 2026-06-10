# pyCycle MCP Server -- Parameter Reference

## Archetypes

| Archetype | Description | Elements |
|-----------|-------------|----------|
| `turbojet` | Single-spool turbojet | fc, inlet, comp, burner, turb, nozz, shaft, perf |

More archetypes (hbtf, mixedflow_turbofan, turboshaft) exist in the omd
plan runner (`hangar.omd.pyc`); this server currently exposes `turbojet`.

## create_engine

| Parameter | Default | Notes |
|-----------|---------|-------|
| archetype | (required) | See table above |
| name | "engine" | Referenced by analysis calls; must match exactly |
| comp_PR | archetype default (13.5) | Compressor pressure ratio |
| comp_eff | archetype default (0.83) | Compressor isentropic efficiency |
| turb_eff | archetype default (0.86) | Turbine isentropic efficiency |
| Nmech | archetype default | Shaft speed (rpm) |
| burner_dPqP | archetype default | Combustor fractional pressure loss |
| nozz_Cv | archetype default | Nozzle velocity coefficient |
| thermo_method | "TABULAR" | "TABULAR" (~10x faster) or "CEA" |
| overrides | None | Advanced: {OpenMDAO path: value} applied after setup |

## run_design_point

Sizes the engine (flow areas, map scalars). MUST precede run_off_design.

| Parameter | Default | Notes |
|-----------|---------|-------|
| engine_name | "engine" | From create_engine |
| alt | 0.0 | Design altitude (ft) |
| MN | 0.000001 | Design Mach (use near-zero, not exactly 0, for SLS) |
| Fn_target | 11800.0 | Design net thrust (lbf) |
| T4_target | 2370.0 | Turbine inlet temperature (degR); keep below ~3600 |

## run_off_design

Evaluates the sized engine at another operating point. The solver adjusts
FAR, shaft speed, and mass flow to hit the thrust target with fixed geometry.

| Parameter | Default | Notes |
|-----------|---------|-------|
| engine_name | "engine" | Must have a solved design point |
| alt | 0.0 | Off-design altitude (ft) |
| MN | 0.000001 | Off-design Mach |
| Fn_target | 11000.0 | Off-design thrust target (lbf) |

## Key outputs

* `TSFC` -- thrust-specific fuel consumption (lbm/hr/lbf); lower is better
* `Fn` -- net thrust (lbf)
* `OPR` -- overall pressure ratio (Pt3/Pt2)
* `flow_stations` -- total/static P, T, W, MN at each station
* `components` -- PR, efficiency, power, torque per element

## Artifact storage (automatic)

Every analysis saves a run_id.
Storage layout: `{HANGAR_DATA_DIR}/{user}/{project}/{session_id}/{run_id}.json`

* `list_artifacts(session_id?, analysis_type?, project?)` -- analysis_type: 'design', 'off_design'
* `get_artifact(run_id, session_id?)` -- full metadata + results
* `get_artifact_summary(run_id, session_id?)` -- metadata only
* `delete_artifact(run_id, session_id?)` -- remove permanently
* `pyc://artifacts/{run_id}` -- resource access by run_id
* `configure_session(project="name")` sets the project for subsequent runs

## Visualization

`visualize(run_id, plot_type)` with plot types:

* `station_properties` -- Pt, Tt, Mach, mass flow through the engine
* `ts_diagram` -- T-s diagram of the Brayton cycle
* `performance_summary` -- table card of key metrics
* `component_bars` -- component PR / efficiency / power comparison
* `design_vs_offdesign` -- paired design vs off-design bars (off-design runs)
