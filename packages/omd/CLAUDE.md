# hangar-omd -- General-Purpose OpenMDAO Plan Runner

## What this is
omd materializes YAML analysis plans into OpenMDAO problems, runs them, and
records results with PROV-Agent provenance tracking. It uses a factory registry
to support different component types (OAS aero, OAS aerostruct, paraboloid)
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
  - `paraboloid.py` -- `build_paraboloid()`: trivial test component
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
