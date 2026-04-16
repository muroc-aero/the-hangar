# hangar-omd -- General-Purpose OpenMDAO Plan Runner

## What this is
omd materializes YAML analysis plans into OpenMDAO problems, runs them, and
records results with PROV-Agent provenance tracking. It uses a factory registry
to support different component types (OAS aero, OAS aerostruct, pyCycle, paraboloid)
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
- `cli.py` -- click-based CLI: run, plot, results, assemble, validate, export, provenance
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
  - `paraboloid.py` -- `build_paraboloid()`: trivial test component
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
  - `_common.py` -- shared helpers: CaseReader access, span extraction, mirroring, elliptical lift
  - `generic.py` -- convergence (with constraint traces), DV evolution (individual + mean)
  - `oas.py` -- OAS-specific: planform, lift, twist, struct, thickness, vonmises, skin_spar, t_over_c, mesh_3d
- `db.py` -- SQLite analysis DB: provenance tables, path helpers
- `recorder.py` -- imports OpenMDAO CaseReader data into analysis DB
- `plan_schema.py` -- JSON Schema for plan YAML validation
- `assemble.py` -- merges modular YAML files into canonical plan.yaml
- `export.py` -- generates standalone Python scripts from plans
- `provenance.py` -- provenance timeline and DAG visualization
- `results.py` -- query results from analysis DB
- `server.py` -- FastMCP server (thin wrapper over CLI functions)

## Component types
| Type | Factory | Plot Provider | Description |
|------|---------|---------------|-------------|
| `oas/AerostructPoint` | `build_oas_aerostruct` | `OAS_AEROSTRUCT_PLOTS` | Coupled aero+struct |
| `oas/AeroPoint` | `build_oas_aeropoint` | `OAS_AERO_PLOTS` | Aero-only VLM |
| `pyc/TurbojetDesign` | `build_pyc_turbojet_design` | (generic only) | Single-spool turbojet design point |
| `pyc/TurbojetMultipoint` | `build_pyc_turbojet_multipoint` | (generic only) | Turbojet design + off-design |
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
| `component_family` | str | run.py | Dispatch key for result extraction ("ocp" triggers OCP path) |
| `multipoint` | bool | run.py | Triggers per-point result extraction |
| `archetype_meta` | dict | (available) | pyCycle archetype metadata for rich result extraction |

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

# Run analysis or optimization
omd-cli run plan.yaml --mode analysis
omd-cli run plan.yaml --mode optimize

# Generate all plots for a run
omd-cli plot <run_id> --type all

# List available plot types
omd-cli plot <run_id> --list-types

# Query results
omd-cli results <run_id> --summary

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
