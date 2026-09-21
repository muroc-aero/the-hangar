# hangar-omd -- General-Purpose OpenMDAO Plan Runner

## What this is
omd materializes YAML analysis plans into OpenMDAO problems, runs them, and
records results with PROV-Agent provenance tracking. It uses a factory registry
to support different component types (OAS aero, OAS aerostruct, pyCycle, paraboloid,
and Aviary sizing via the native avy/Sizing factory)
and a plot provider registry so each factory brings its own visualization.

## Architecture

### Data flow: run
```
plan.yaml -> load_and_validate() -> materialize() -> prob.run_driver/run_model()
                                        |                    |
                                   factory builds      OpenMDAO writes to
                                   om.Problem          SqliteRecorder
                                        |                    |
                                   prob.setup()         recorder .sql file
                                        |
                                   _generate_n2()  ->  n2/{run_id}.html
```

### Data flow: plot
```
omd-cli plot <run_id>
    |
    +-- query analysis.db for component_type
    +-- get_plot_provider(component_type) from registry
    +-- for each plot type:
    |       open recorder .sql via CaseReader
    |       extract data with find_first_output() / get_span_eta()
    |       render matplotlib Figure
    |       savefig to plots/{run_id}/{type}.png
    +-- for n2: copy n2/{run_id}.html to plots/{run_id}/n2.html
```

### File persistence
All runtime data lives under `hangar_data/omd/` (configurable via `OMD_DATA_ROOT`):
- `analysis.db` -- SQLite provenance DB (entities, activities, prov_edges, run_cases)
- `plans/{plan-id}/v{N}.yaml` -- assembled plan versions
- `recordings/{run-id}.sql` -- OpenMDAO recorder output (iteration data)
- `n2/{run-id}.html` -- interactive N2/DSM diagram (generated at run time)
- `plots/{run-id}/*.png` -- visualization PNGs (generated on demand)

## Source layout
- `cli.py` -- click-based CLI: run, polar, plot, results, summary, conclude, assemble, validate, export, provenance, plan (init/add-*/set-*/review), viewer
- `run.py` -- plan execution pipeline: load, materialize, execute, record, N2 generation
- `materializer.py` -- converts plan YAML to OpenMDAO Problem
  - Factory lookup via registry
  - Solver/driver/DV/constraint/objective configuration
  - Recorder attachment
  - Variable path resolution (short names like CL, CD, S_ref to full OpenMDAO paths)
- `registry.py` -- factory + plot provider registry
  - `_FACTORIES` -- maps component types to builder functions
  - `_PLOT_PROVIDERS` -- maps component types to plot provider dicts
  - `_GENERIC_PLOTS` -- plots that work for any OpenMDAO problem (convergence, dv_evolution, n2)
- `factories/` -- component builders
  - `oas.py` -- `build_oas_aerostruct()`: coupled aero+struct with Newton solver
  - `oas_aero.py` -- `build_oas_aeropoint()`: aero-only VLM analysis
  - `pyc.py` -- `build_pyc_turbojet_design()`, `build_pyc_turbojet_multipoint()`: pyCycle gas turbine
  - `evt.py` -- `build_evt_sizing()`, `build_evt_mission()`: eVTOL sizing via the
    **native** OpenMDAO model in `hangar.omd.evt` (idiomatic components with
    complex-step partials + a real MTOW-closure solver, so sizing runs with
    analytic gradients). `build_evt_sizing_fd()` (`evt/SizingFD`) keeps the
    gradient-free `EvtolSizingComp` black box as a fallback/parity reference.
  - `avy.py` -- `build_avy_sizing()`: NASA Aviary sizing + mission optimization
    as a **native** composition -- Aviary's `AviaryGroup` is added to the omd
    problem as subsystem `aviary` with `promotes=["*"]`, so its DVs,
    constraints and objective are collected by omd's driver (see "Aviary in
    omd" below)
  - `paraboloid.py` -- `build_paraboloid()`: trivial test component
- `evt/` -- self-contained native OpenMDAO formulation of evtolpy (no runtime
  dependency on `evtolpy` or `hangar.evt` physics; the config-schema constants
  in `hangar.evt.config.defaults` are pure data and are the only allowed import)
  - `geometry.py`, `propulsion.py`, `aero.py`, `mission.py`, `mass.py` -- the
    five domain `ExplicitComponent`s; numpy math, `declare_partials(method="cs")`,
    evtolpy property names as variable names, real units from `units.py`
  - `physics.py` -- `EvtolPhysicsGroup`: the feed-forward chain at a fixed MTOW
  - `sizing.py` -- `EvtolSizingGroup`: two physics instances (as-configured
    `report` + balance-driven `sized`) reproducing the black box's dual-MTOW
    reporting, closed by `NonlinearBlockGS` (mirrors evtolpy's fixed-point
    substitution) or `NewtonSolver` over an implicit lower-bounded MTOW state
  - `builders.py` -- `build_problem(base_config, mode, solver)` -> problem +
    factory metadata (sets `force_alloc_complex` so CS partials allocate)
  - `config.py`, `units.py`, `labels.py` -- config flattening, unit registry,
    segment/mass ordering. Parity suite: `packages/evt/examples/native_parity`
- `pyc/` -- self-contained pyCycle integration (no dependency on hangar.pyc)
  - `defaults.py` -- default parameters, initial guesses, archetype metadata
  - `archetypes.py` -- Turbojet, MPTurbojet, and archetype registry (6 engine types)
  - `builders.py` -- problem assembly (design-point and multipoint)
  - `results.py` -- result extraction (performance, flow stations, components)
  - `surrogate.py` -- deck generation, save/load, MetaModelUnStructuredComp integration
  - `hbtf.py` -- HBTF and MPHbtf dual-spool high-bypass turbofan
  - `ab_turbojet.py` -- afterburning turbojet
  - `turboshaft.py` -- single-spool and multi-spool turboshaft
  - `mixedflow_turbofan.py` -- mixed-flow turbofan with afterburner
- `slots.py` -- slot provider registry for composable OCP tool integration
  - `_DirectPyCyclePropGroup` -- native pyCycle turbojet in OCP solver chain
  - `_DirectPyCycleHBTFPropGroup` -- native pyCycle HBTF in OCP solver chain
  - `PyCycleSurrogateGroup` -- Kriging surrogate from pyCycle off-design sweeps
  - `_DirectVLMDragGroup` -- direct-coupled OAS VLM drag
  - `_ParametricWeightGroup` -- parametric OEW model (weight slot)
- `plotting/` -- factory-aware plot generation
  - `__init__.py` -- `generate_plots()` entry point, N2 HTML handling
  - `_common.py` -- shared helpers: CaseReader access, span extraction, mirroring, elliptical lift; study-grid renderer (`render_grid`, `PanelSpec`, `pivot_grid`, pandas-free)
  - `generic.py` -- convergence (with constraint traces), DV evolution (individual + mean)
  - `oas.py` -- OAS per-run plots (planform, lift, twist, struct, thickness, vonmises, skin_spar, t_over_c, mesh_3d) + `OAS_STUDY_PLOTS` (L/D, C_D, structural mass, failure trade grid)
  - `ocp.py` -- OCP per-run plots + `OCP_STUDY_PLOTS` (Brelje fig5/fig6 trade-grid panels + derived columns)
  - `pyc.py` -- pyc per-run plots (station properties, component efficiency) + `PYC_STUDY_PLOTS` (TSFC, thrust, OPR, fuel-flow trade grid)
- `study_plots.py` -- study-level 2-axis trade grids over a study's cases.csv (`plot_study`); dispatches to a study-plot provider by `component_type`, generic per-column fallback otherwise
- `db.py` -- SQLite analysis DB: provenance tables, path helpers
- `recorder.py` -- imports OpenMDAO CaseReader data into analysis DB
- `plan_schema.py` -- JSON Schema for plan YAML validation
- `assemble.py` -- merges modular YAML files into canonical plan.yaml
- `export.py` -- generates standalone Python scripts from plans
- `provenance.py` -- provenance timeline and DAG visualization
- `results.py` -- query results from analysis DB
- `server.py` -- FastMCP server entry point (full omd-cli parity, port 8003)
- `tools/` -- MCP tool implementations (authoring, execution, results_tools, plots,
  resources, prompts); each tool calls the same implementation as the CLI

## MCP server

`python -m hangar.omd.server` (or `omd-server`) exposes the full omd-cli
surface over MCP through the shared SDK envelope/provenance/auth stack:

- **Tool surface**: plan authoring (`plan_init`, `plan_add_component`,
  `plan_add_dv`, ..., `write_plan`/`read_plan` for direct YAML), validation
  (`validate_plan` runs schema + semantic preflight), execution (`run_plan`
  analysis/optimize, `run_polar` sweep), results (`get_results`,
  `get_run_summary`, `record_conclusion`, `get_provenance`, `export_plan`),
  plots (`generate_plots`, `list_plot_types`), URLs (`get_view_urls`), and
  the four shared provenance tools.
- **Workspace**: relative plan paths resolve to
  `hangar_data/omd/workspace/{user}` so MCP-only agents (claude.ai) can
  author and run plans without filesystem access. The per-user keying
  (OIDC username on HTTP, `HANGAR_USER`/OS login elsewhere) keeps two
  users' identically-named plans from clobbering each other.
- **Envelopes**: `run_plan`/`run_polar` return the versioned envelope;
  typed `HangarError`s become error envelopes via `capture_tool`.
- **Views**: the server registers the omd viewer routes
  (`/omd-provenance`, `/omd-problem-dag`, `/omd-plots`, `/omd-plot-img`,
  `/omd-n2`, `/omd-plan-detail`, `/omd-plan-diff`) on both transports; tool
  results carry a `urls` block built from `RESOURCE_SERVER_URL` (or the
  local daemon viewer port).
- **Per-user scoping**: analysis-DB entities carry a `user` column (stamped
  from `get_current_user()` by `record_entity`); the omd viewer routes
  accept the authenticated viewer user via the extended
  `register_viewer_route` contract and 404 foreign-owned plans/runs.
  Ownerless rows (pre-scoping data) stay visible to everyone. Admins, the
  local stdio daemon viewer, and Basic Auth mode (one shared credential —
  no per-user identity) see everything.
- **Range-safety dashboard**: deployments set `RS_DASHBOARD_URL`; locally
  the server autostarts the dashboard on `RS_DASHBOARD_PORT` (default 7655)
  when hangar-range-safety is installed. Disable with
  `RS_DASHBOARD_AUTOSTART=off`.
- **Resources/prompts**: `omd://reference` (parameter reference,
  `src/hangar/omd/reference.md`), `omd://plan-schema`,
  `omd://plans/{plan_id}`; prompts `author_plan_study`,
  `run_existing_plan`. The omd-cli guide skill stays the deep reference.

## Component types
| Type | Factory | Plot Provider | Description |
|------|---------|---------------|-------------|
| `oas/AerostructPoint` | `build_oas_aerostruct` | `OAS_AEROSTRUCT_PLOTS` | Coupled aero+struct |
| `oas/AeroPoint` | `build_oas_aeropoint` | `OAS_AERO_PLOTS` | Aero-only VLM |
| `pyc/TurbojetDesign` | `build_pyc_turbojet_design` | (generic only) | Single-spool turbojet design point |
| `pyc/TurbojetMultipoint` | `build_pyc_turbojet_multipoint` | (generic only) | Turbojet design + off-design |
| `evt/Sizing` | `build_evt_sizing` | `EVT_PLOTS` | eVTOL MTOW sizing loop (native OpenMDAO, analytic gradients) |
| `evt/Mission` | `build_evt_mission` | `EVT_PLOTS` | eVTOL as-configured mission energy (native, no sizing) |
| `evt/SizingFD` | `build_evt_sizing_fd` | `EVT_PLOTS` | eVTOL sizing via the gradient-free evtolpy black box (FD fallback) |
| `avy/Sizing` | `build_avy_sizing` | (generic only) | Aviary coupled sizing + mission, native `AviaryGroup` inside the omd problem (self-optimizing; every run is an optimization -- `mode: optimize`) |
| `paraboloid/Paraboloid` | `build_paraboloid` | (generic only) | Test component |

## Plot types
### Generic (all component types)
- `convergence` -- objective vs iteration with constraint traces on secondary axis
- `dv_evolution` -- DV values per iteration (individual elements + mean for vectors)
- `n2` -- interactive N2/DSM diagram (HTML, generated at run time)

### OAS Aero (oas/AeroPoint)
All generic plots plus:
- `planform` -- LE/TE outline with optional deformed overlay
- `lift` -- spanwise lift distribution with elliptical reference
- `twist` -- twist and chord on dual y-axes
- `mesh_3d` -- 3D wireframe with optional structural FEM

### OAS Aerostruct (oas/AerostructPoint)
All aero plots plus:
- `struct` -- vertical deflection profile
- `thickness` -- tube wall thickness distribution
- `vonmises` -- peak von Mises stress with yield/SF failure limit
- `skin_spar` -- skin and spar thickness (wingbox only)
- `t_over_c` -- thickness-to-chord ratio

### pyCycle (all pyc/* types)
All generic plots plus:
- `station_properties` -- grouped bar chart of total pressure and temperature at flow stations
- `component_efficiency` -- bar chart of compressor/turbine efficiency and pressure ratio

### evt (evt/Sizing, evt/Mission)
All generic plots plus:
- `segment_energy` -- per-segment mission energy (kWh) bar chart
- `segment_power` -- per-segment average electric power (kW) bar chart
- `mass_breakdown` -- component empty-mass breakdown (kg)
- `mtow_convergence` -- MTOW fixed-point sizing history (sizing mode; reads the
  padded `mtow_history_kg` / `n_iterations` outputs the component records)

## Study plots (2-axis trade grids)

Distinct from the per-run plots above: study plots render across a whole
study's `cases.csv` instead of one recorder file. `plot_study(study_id)`
(`omd-cli study plot`, MCP `plot_study`) requires a study with exactly two
numeric axes, pivots each output column over them, masks non-converged
cells, and renders pcolormesh (`style="paper"`) or contourf
(`style="contour"`) panels.

Dispatch mirrors the per-run provider pattern but uses a separate registry
(`_STUDY_PLOT_PROVIDERS`, keyed by `component_type`):

- `register_study_plots(component_type, provider)` in `registry.py`;
  providers map a plot name to `(study_table, x_axis, y_axis, **kwargs) -> Figure`.
- Per-tool providers: `OCP_STUDY_PLOTS` (`plotting/ocp.py`, Brelje fig5/fig6
  four-panel grid + mission derived columns), `OAS_STUDY_PLOTS`
  (`plotting/oas.py`, L/D + C_D + structural mass + failure, L/D derived from
  CL/CD), `PYC_STUDY_PLOTS` (`plotting/pyc.py`, TSFC + thrust + OPR + fuel
  flow). Panel lists are a superset; panels whose column is absent are
  skipped, so an aero-only OAS study renders a subset. Demos:
  `demos/oas_trade/`, `demos/pyc_trade/`.
- Study-plot providers register **outside** the solver-import guards in
  `_register_builtins()` (they read cases.csv, not a live problem), so a study
  plots even where openaerostruct/openconcept/pycycle is not installed (e.g.
  the dashboard env). Keep the study-plot code in these modules solver-free.
- Component types with no provider fall back to a generic grid: one panel
  per numeric output column.
- The generic mechanism is pandas-free: a columnar `Table`
  (`dict[str, Sequence]`) + numpy, so omd core gains no pandas dependency.

Surfacing (parity with the per-run plot gallery):

- `study_plot_types(study_id)` lists the renderable grid names without
  rendering (`[]` when the study is not 2-axis numeric), so a UI can list
  before it renders.
- The omd viewer serves a rendered grid at
  `/omd-study-plot-img?study_id=&name=&style=` (registered in
  `cli/server_routes.py`); the `plot_study` MCP tool returns matching
  `study_plot_urls` so the grid is web-addressable, not just on disk.
- The range-safety dashboard study view embeds a lazy trade-grid gallery
  (`/api/study-plots/{study_key}[/{plot_type}]`, paper/contour toggle),
  delegating to `study_plot_types` / `plot_study` through its studyfs
  source. It renders on first view and caches to `studies/{id}/plots/`.

## How to add a new factory

1. **Create the factory function** in `factories/<tool>.py` matching the signature:
   `(component_config: dict, operating_points: dict) -> (om.Problem, metadata: dict)`
   - Build an `om.Problem` but do NOT call `setup()` (the materializer does that)
   - Return metadata with at least `point_name` and `output_names`
   - Use `initial_values` for post-setup value assignment (Newton guesses, etc.)
   - Use `initial_values_with_units` for values that need unit conversion
2. **Register** in `registry.py` `_register_builtins()` with a `try/except ImportError`
3. **Add a test fixture** in `tests/fixtures/<name>/` (metadata.yaml, operating_points.yaml, components/*.yaml)
4. **Add a parity test** in `tests/test_eval_multilane.py` (Lane A: direct API, Lane B: omd pipeline)

### Factory patterns

**Subsystem pattern** (OAS, paraboloid): `prob.model.add_subsystem("name", Component())`
**Model-is-root pattern** (pyCycle): `prob.model = CycleClass(params=...)`
Both work. The materializer calls `setup()` after all factories return. For composition
(`_materialize_composite`), the model is extracted via `inner_prob.model` and added as a
named subsystem -- internal connections use relative paths and still work.

## Factory metadata keys

| Key | Type | Used by | Description |
|-----|------|---------|-------------|
| `point_name` | str | materializer, run.py | Analysis point subsystem name |
| `point_names` | list[str] | materializer | Multiple points (multipoint) |
| `surface_names` | list[str] | materializer | OAS surface identifiers |
| `output_names` | list[str] | run.py | Full OpenMDAO paths for summary extraction |
| `var_paths` | dict[str,str] | materializer | Short name -> full path for DVs/constraints/objectives |
| `initial_values` | dict[str,float] | materializer | Values set via `prob.set_val(name, val)` after setup |
| `initial_values_with_units` | dict[str,dict] | materializer | Values with units: `{"val": 1.0, "units": "ft"}` |
| `_setup_done` | bool | materializer | True if factory already called setup (skip materializer setup) |
| `_composite` | bool | materializer | Set by materializer for multi-component plans |
| `component_family` | str | run.py | Dispatch key for result extraction ("ocp" / "evt" trigger tool-specific paths) |
| `evt_mode` | str | run.py | evt factory mode: "sizing" (MTOW loop) or "mission" (as-configured) |
| `multipoint` | bool | run.py | Triggers per-point result extraction |
| `archetype_meta` | dict | (available) | pyCycle archetype metadata for rich result extraction |
| `self_optimizing` | bool | materializer, run.py | Factory declared its own DVs/constraints/objective inside the model (Aviary); the driver is configured even when the plan declares no `design_variables`/`objective` |
| `requires_driver` | bool | run.py | Results are only meaningful under `run_driver` (every Aviary run is an optimization); `mode: analysis` is refused |
| `driver_defaults` | dict | materializer | `{"type": "SLSQP", "options": {...}}` applied under the plan's `optimizer` section (plan keys win) |
| `driver_coloring` | bool | materializer | Call `driver.declare_coloring(show_summary=False)` (total coloring) |
| `model_options` | dict[str,dict] | materializer | OpenMDAO `prob.model_options` entries keyed by path glob relative to the factory's model root; a composite re-keys them under the comp id |
| `post_setup` | list[callable] | materializer | Callables `f(prob)` run right after `prob.setup()`, before initial values (e.g. dymos initial guesses) |
| `setup_warning_filters` | list[type] | materializer | Warning classes ignored around `prob.setup()` |
| `avy_outputs` | dict[str,tuple] | run.py | Aviary: summary key -> (promoted name, units) |

## Aviary in omd (avy/Sizing)

Native composition (`factories/avy.py`). Aviary's model is an ordinary
OpenMDAO Group (`AviaryGroup`); upstream's `AviaryProblem` is a thin
`om.Problem` wrapper whose level-2 API delegates every model-building step
to that group. The factory runs the same sequence (`load_inputs` ->
`load_external_subsystems` -> `check_and_preprocess_inputs` ->
`add_pre_mission_systems` -> `add_phases` -> `add_post_mission_systems` ->
`link_phases` -> `add_design_variables` -> objective) on a bare
`AviaryGroup` and adds it to the omd problem as subsystem `aviary` with
`promotes=["*"]`, so Aviary's promoted names (`aircraft:*`, `mission:*`,
`traj.*`) ARE the component's namespace (`<comp_id>.aircraft:wing:mass` in
a composite). Other plan components connect to them directly, with
analytic derivatives flowing through one driver. The whole workspace runs
in one venv (numpy 2 / OpenMDAO 3.45 / Aviary 1.0.1; OpenConcept patched
via `scripts/openconcept-numpy2.patch`), so there is no worker process or
second interpreter. The single-aisle case reproduces the Lane A goldens
to ~1e-8 relative in ~3 s.

**Every run is an optimization.** Aviary's own DVs, constraints and
objective are declared inside the group and collected by omd's driver
(OpenMDAO re-keys them under the component path), and the mission is a
dymos collocation problem with no evaluate-only path. Plans with
`avy/Sizing` run with `mode: optimize`; `mode: analysis` is refused with a
clear error (`requires_driver`). The plan needs no plan-level
`design_variables`/`objective` for that (the component is
self-optimizing); the factory supplies Aviary's SLSQP driver defaults
(tol 1e-9, `max_iter`, total coloring -- the same driver `run_aviary`
builds), which the plan's `optimizer:` section can override (e.g.
`options.timeout_seconds`).

Config keys:
- `deck` (required) -- aviary-relative CSV path (e.g.
  `models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv`)
  or absolute.
- `phase_info_module` -- importable module exposing `phase_info` (default
  `aviary.models.missions.energy_state_default`; the
  `hangar.avy.config.missions_*` modules work too).
- `target_range_nm` -- sets `post_mission.constrain_range`/`target_range`;
  an operating-point `target_range_nm` overrides it.
- `overrides` -- `{aviary name: value | [value, units]}` deck overrides,
  validated by `hangar.avy.validators.validate_deck_overrides`. **This is
  also the coupling seam**: a deck value for a variable Aviary would
  otherwise COMPUTE (e.g. `aircraft:wing:mass` from the FLOPS mass
  build-up) makes it a plain boundary input -- Aviary's own override
  mechanism -- which a plan `connections:` entry can then drive.
- `external_subsystems` -- `[{name: ..., config: {...}}]` Aviary
  SubsystemBuilders from the hangar.avy registry (e.g. `oas_wing_mass`,
  upstream's OAS wingbox wing-mass sub-optimization, ~40 s), materialized
  INSIDE the group -- the seam for components that must live inside the
  mission phases.
- `engine_deck` -- `{provider: pyc/hbtf | pyc/turbojet, config: {...},
  cache: true | false | dir}`: replace the aircraft deck's file engine
  (`aircraft:engine:data_file`) with a pyCycle one. A hangar pyCycle
  off-design sweep (`hangar.omd.pyc.surrogate.generate_deck`) is
  tabulated as an in-memory Aviary `EngineDeck`
  (`hangar.omd.pyc.aviary_deck`) and handed to
  `load_external_subsystems`, which routes any `EngineModel` into
  `engine_models`. pyCycle sets the engine's lapse and SFC; Aviary reads
  the reference SLS thrust off the table (the grid must include
  alt 0 / Mach 0 / throttle 1) and scales the deck to the aircraft's
  `scaled_sls_thrust` like any file deck. `config` keys: `design_alt_ft`,
  `design_MN`, `design_Fn_lbf`, `design_T4_degR`, `engine_params`, `grid`
  (`{alt_ft, MN, throttle}`; default = a transport envelope the HBTF
  converges on). The sweep (~3 s/point) is cached at
  `<HANGAR_DATA_DIR>/pyc_decks/<archetype>_<sha>.npz`, keyed on the
  resolved spec + pyCycle version. Points whose cycle Newton fails are
  dropped, and a deck whose thrust is not monotone in throttle at any
  flight condition is refused before it reaches Aviary. Third tool in
  `examples/avy_three_tool/` (Aviary + OAS + pyCycle).
- `optimizer` -- SLSQP only under omd (ScipyOptimizeDriver); use
  avy-cli / avy-server for IPOPT or SNOPT.
- `max_iter` -- driver maxiter (default 50).
- `objective` -- `fuel` (default; `run_aviary`'s regularized
  fuel + ascent-duration objective) | `fuel_burned` | `mass` | `time` |
  `none` (leave the objective to the plan, for composite objectives).

Removed keys (the factory rejects them with a pointer): `override_inputs`
(use `overrides` + `connections`), `avy_python` (Aviary runs in-process),
`run_timeout_s` (use plan-level `optimizer.options.timeout_seconds`).

Loose-coupling example (`examples/oas_avy_wing_mass/`, OAS structural
mass -> `aircraft:wing:mass`):

```yaml
components:
- id: wingbox
  type: oas/AerostructPoint
  config: {surfaces: [...]}
- id: sizing
  type: avy/Sizing
  config:
    deck: models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv
    overrides:
      aircraft:wing:mass: [15000.0, lbm]   # deck value -> boundary input
connections:
- src: wingbox.wing.structural_mass        # kg
  tgt: sizing.aircraft:wing:mass           # lbm; OpenMDAO converts
```

Results: the run summary carries `gross_mass_lbm`, `total_fuel_mass_lbm`,
`operating_mass_lbm`, `wing_mass_lbm`, `range_nmi`, `final_time_min`
(metadata `avy_outputs`: short name -> (promoted name, units); the same
short names resolve through `var_paths` for plan DVs/constraints/
objectives) and a boolean `converged` taken from the driver result --
Aviary optimizer non-convergence does not raise, so check it. `converged`
is a summary field, not an OpenMDAO output. With `engine_deck`, the
summary also carries `engine_deck` (`provider`, `sha`, `cache_hit`,
`n_points`/`n_converged`/`n_used`, `reference_sls_thrust_lbf`,
`scale_factor`, `scaled_sls_thrust_lbf`) and a top-level
`engine_scale_factor` copy of `scale_factor` (the assessment snapshot
keeps top-level scalars only). The deck cache directory is
`$HANGAR_PYC_DECK_CACHE` when set, else `<HANGAR_DATA_DIR>/pyc_decks/`.

Generic materializer hooks the factory uses (all documented in
`factory_metadata.py`; nothing Aviary-specific lives in the materializer):
`self_optimizing`, `requires_driver`, `driver_defaults`, `driver_coloring`,
`model_options` (Aviary options travel by OpenMDAO `model_options`,
path-prefixed under the comp id in composites), `post_setup` (dymos
initial guesses must be set after `setup()`), `setup_warning_filters`
(the promotion warnings `AviaryProblem.setup` suppresses). Plot provider:
generic only.

## pyCycle in omd

The `pyc/` subpackage provides self-contained pyCycle support with no dependency on
`hangar.pyc`. It uses upstream `pycycle` directly.

Key differences from OAS factories:
- **Model IS the root**: `prob.model = Turbojet(params=...)` -- the Cycle class IS the model
- **No solver section needed**: Newton + DirectSolver are configured inside `Turbojet.setup()`
- **Newton guesses are critical**: must be set after `setup()` via `initial_values`
- **guess_nonlinear**: Turbojet and HBTF override `guess_nonlinear()` to apply balance
  variable guesses at the start of every Newton solve. Critical when embedded in an outer
  Newton (e.g. OCP mission solver) where one-time `set_val` guesses get overwritten.
- **CEA thermo sub-solvers print output**: these are internal to pyCycle elements and not
  controlled by the top-level solver iprint setting
- **CEA thermo may not converge in direct-coupled mode**: when pyCycle HBTF is embedded
  inside an OCP mission solver (direct-coupled via `pyc/hbtf`), CEA thermo can fail to
  converge. Use `thermo_method: TABULAR` for direct-coupled HBTF configurations.

Available archetypes: turbojet, hbtf, ab_turbojet, single_spool_turboshaft,
multi_spool_turboshaft, mixedflow_turbofan. Each defines element topology,
flow connections, balance equations, and solver configuration.

## pyCycle-OCP slot providers

Three propulsion slot providers for coupling pyCycle into OCP missions:

| Provider | Class | Approach |
|----------|-------|----------|
| `pyc/turbojet` | `_DirectPyCyclePropGroup` | Native MPTurbojet in solver chain |
| `pyc/hbtf` | `_DirectPyCycleHBTFPropGroup` | Native MPHbtf with T4 throttle |
| `pyc/surrogate` | `PyCycleSurrogateGroup` | Kriging surrogate from off-design sweep |

**Direct-coupled** (Path 2): pyCycle runs as native OpenMDAO Group inside OCP.
Analytic partials flow through the solver chain. Execution order matters: slicers
must be added before the cycle subsystem (RunOnce executes in add order).

**Surrogate-coupled** (Path 1): `generate_deck()` runs pyCycle off-design across
a grid, then `PyCycleSurrogateGroup` wraps the results in a Kriging surrogate.
No convergence risk, much faster (~1ms vs ~2s per node), but approximate.

Key lessons from integration:
- Subsystem execution order in Groups with RunOnce matters -- inputs must compute first
- `guess_nonlinear` on Cycle classes is essential for embedded convergence
- ExecComp unit passthrough: use same units on input/output, let connections convert
- `apply_initial_guesses` must handle both promoted and non-promoted paths
- Direct-coupled pyCycle converges in a full OCP mission (Newton-in-Newton works)
- Dual-surrogate coupling (VLM + pyCycle surrogates) produces singular Jacobians;
  use at least one direct-coupled provider when combining both slots

## Slot provider design variables

Slot providers declare a `design_variables` attribute mapping short names to
internal OpenMDAO paths. The OCP factory collects these into `var_paths` so the
materializer can resolve them for optimization.

| Provider | DVs |
|----------|-----|
| `pyc/turbojet` | comp_PR, comp_eff, turb_eff |
| `pyc/hbtf` | fan_PR, fan_eff, hpc_PR, hpc_eff |
| `pyc/surrogate` | (none -- baked into deck) |
| `oas/vlm` | twist_cp |
| `oas/vlm-direct` | twist_cp |
| `oas/aerostruct` | twist_cp, toverc_cp |

Pipe-separated paths (e.g., `ac|geom|wing|twist`) are promoted to top level.
Dot-separated paths (e.g., `cycle.DESIGN.comp.PR`) are prefixed with
`{first_phase}.{subsystem}.` (e.g., `climb.propmodel.cycle.DESIGN.comp.PR`).

## Slot provider result paths

Slot providers declare a `result_paths` attribute mapping short variable
names to internal OpenMDAO paths. The composite result extractor uses
these to pull per-slot metrics into `summary["slots"]`.

| Provider | Result paths |
|----------|-------------|
| `pyc/turbojet` | thrust, fuel_flow, TSFC, Fn |
| `pyc/hbtf` | thrust, fuel_flow, TSFC, Fn |
| `pyc/surrogate` | thrust, fuel_flow |
| `oas/vlm` | drag |
| `oas/vlm-direct` | drag |
| `oas/aerostruct` | drag |
| `ocp/parametric-weight` | OEW |

Full paths are constructed as `{comp_id}.{phase}.acmodel.{subsys}.{path}`
where `subsys` maps from slot name (propulsion -> propmodel, drag -> drag).

## Weight slot

OCP declares three slots: drag, propulsion, and weight. The weight slot
replaces the default `WeightClass` empty-weight model.

| Provider | Class | Description |
|----------|-------|-------------|
| `ocp/parametric-weight` | `_ParametricWeightGroup` | OEW = sum of component weights |

Weight model precedence in `_make_aircraft_model_class()`:
1. Weight slot provider (if `slots["weight"]` provided)
2. OEW passthrough (if propulsion slot is active -- no component weights available)
3. Architecture-specific WeightClass (default)
4. CFM56 passthrough (OEW from input)

The parametric weight provider supports `use_wing_weight: true` to read
`ac|weights|W_wing` from an aerostruct drag slot.

## OCP per-phase profile extraction

`_extract_ocp_summary()` extracts per-phase arrays stored in
`summary["profiles"][phase]`. Variables: altitude_m, velocity_ms, mach,
thrust_kN, drag_N, fuel_flow_kgs, weight_kg. Each is a list of length
num_nodes.

## Key conventions
- Plot functions match oas-cli style: 6x3.6 in figures, suptitle with run_id,
  normalized span axis (eta 0=root, 1=tip), half-span default
- All plot functions accept `**kwargs` and extract `run_id` from kwargs
- The recorder .sql is the single source of truth for plot data --
  plot functions read it via CaseReader, not from the analysis DB
- Factories must forward all surface config keys to OAS (chord_cp, num_twist_cp, etc.)
- The materializer resolves short variable names to full OpenMDAO paths:
  - DVs: twist_cp -> wing.twist_cp, chord_cp -> wing.chord_cp
  - Perf outputs: CL -> aero_point_0.wing_perf.CL
  - Surface outputs: S_ref -> aero_point_0.wing.S_ref
  - Aerostruct: failure, fuelburn, structural_mass, L_equals_W
- N2 diagrams must be generated at run time (requires live Problem object)

## Testing
```bash
uv run pytest packages/omd/tests/ -v

# Specific test files
uv run pytest packages/omd/tests/test_plotting.py -v
uv run pytest packages/omd/tests/test_run.py -v
uv run pytest packages/omd/tests/test_assemble.py -v
```

## CLI quick reference
```bash
# Assemble modular YAML into plan.yaml
omd-cli assemble my-plan/

# Author a plan directory incrementally (instead of hand-writing YAML)
omd-cli plan init my-plan/ --id my-plan --name "My Plan"
omd-cli plan add-component my-plan/ --id wing --type oas/AeroPoint --config-file wing.yaml
omd-cli plan add-requirement my-plan/ --id R1 --text "CD below 0.04 at cruise" --type performance
omd-cli plan review my-plan/

# Run analysis or optimization
omd-cli run plan.yaml --mode analysis
omd-cli run plan.yaml --mode optimize

# Drag polar sweep (OAS plans)
omd-cli polar plan.yaml --alpha-start -2 --alpha-end 10 --num 7

# Generate all plots for a run
omd-cli plot <run_id> --type all

# List available plot types
omd-cli plot <run_id> --list-types

# Query results
omd-cli results <run_id> --summary

# One-page HTML run summary (also rendered eagerly at the end of each run)
omd-cli summary <run_id>

# Record the study conclusion (auto-derived verdicts vs plan requirements)
omd-cli conclude <run_id> --narrative "what these results mean"

# View provenance
omd-cli provenance <plan_id> --format text
omd-cli provenance <plan_id> --format html -o dag.html

# Start interactive Cytoscape.js provenance viewer
omd-cli viewer

# Export static provenance DAG HTML
omd-cli provenance <plan_id> --format html -o dag.html
# On WSL, open in Windows browser:
explorer.exe "$(wslpath -w dag.html)"

# Export standalone Python script
omd-cli export plan.yaml --output script.py
```

## Agent-facing discoverability (2026-09-21)

- `plan_add_component` rejects an unregistered `comp_type` at call time
  (`UserInputError`), and every unknown-type message -- there and in
  `validate_plan` / `run_plan` semantic validation -- lists the registered
  types (`unknown_component_type_message` in `plan_validate.py`). A close
  match adds "Did you mean"; the list is there regardless, because an
  invented name has no close match and a bare "unknown" just restarts the
  guessing (every gemma seed on the 2026-09-21 eval arm).
- The server's MCP `instructions` block lives in `hangar/omd/instructions.py`
  (`INSTRUCTIONS`), importable without building the server. hangar-evals
  reads it plus `tools/resources.py` to hand OpenCode agents the same texts
  Claude Code gets over MCP (OpenCode 1.17.5 forwards neither instructions
  nor resources). Edit the text there, not in `server.py`.
