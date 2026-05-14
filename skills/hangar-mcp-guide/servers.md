# Servers - Startup, Transport, Tool Catalogue

Each Hangar MCP server is a separate FastMCP process registered under
its own name. Tool names include the server name as a prefix when
surfaced to an agent (e.g. `mcp__OpenAeroStruct__create_surface`).

## OpenAeroStruct (`oas`)

Module: `hangar.oas.server`. Aerostructural analysis and optimisation.

```bash
uv run python -m hangar.oas.server                            # stdio (default)
uv run python -m hangar.oas.server --transport http --port 8000
```

Environment variables:
- `OAS_HOST`, `OAS_PORT` - HTTP transport host/port
- `OAS_TRANSPORT=stdio|http`
- `HANGAR_PROV_DB` - override provenance DB path

Tools (current set; run `oas-cli list-tools` for the live list):

| Group | Tools |
|-------|-------|
| Geometry | `create_surface` |
| Analysis | `run_aero_analysis`, `run_aerostruct_analysis`, `compute_drag_polar`, `compute_stability_derivatives` |
| Optimisation | `run_optimization` |
| Session | `reset`, `configure_session`, `set_requirements`, `pin_run`, `unpin_run` |
| Observability | `get_run`, `get_detailed_results`, `get_n2_html`, `get_last_logs` |
| Artifacts | `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact` |
| Visualisation | `visualize` |
| Provenance | `start_session`, `log_decision`, `link_cross_tool_result`, `export_session_graph` |

OAS-specific gotchas (also see `oas-cli-guide/commands.md`):
- `num_y` must be ODD.
- Aerostruct tools require `fem_model_type` plus material props on the surface.
- `load_factor` has a cache bug; always set it explicitly per call.
- `omega != None` rebuilds the OpenMDAO topology on first use.
- `groundplane=True` requires `symmetry=True` and `beta=0`.

## OpenConcept (`ocp`)

Module: `hangar.ocp.server`. Aircraft conceptual design and mission analysis.

```bash
uv run python -m hangar.ocp.server                            # stdio
uv run python -m hangar.ocp.server --transport http --port 8001
```

Environment variables:
- `OCP_HOST`, `OCP_PORT`, `OCP_TRANSPORT`
- `HANGAR_PROV_DB` (shared)

Tools:

| Group | Tools |
|-------|-------|
| Aircraft | `list_aircraft_templates`, `load_aircraft_template`, `define_aircraft` |
| Propulsion | `set_propulsion_architecture` |
| Mission | `configure_mission`, `run_mission_analysis`, `run_parameter_sweep` |
| Optimisation | `run_optimization` |
| Session | `reset`, `configure_session`, `set_requirements`, `pin_run`, `unpin_run` |
| Observability | `get_run`, `get_detailed_results`, `get_last_logs` |
| Artifacts | `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact` |
| Visualisation | `visualize` |
| Provenance | `start_session`, `log_decision`, `link_cross_tool_result`, `export_session_graph` |

OCP-specific gotchas:
- Order matters: `load_aircraft_template` (or `define_aircraft`) ->
  `set_propulsion_architecture` -> `run_mission_analysis`. Skipping the
  architecture step produces a `USER_INPUT_ERROR`.
- `num_nodes` must be ODD (Simpson's rule).
- Hybrid architectures require `battery_weight`, motor, and generator
  ratings on the aircraft. `kingair` template is hybrid-ready.
- Architecture changes invalidate the cached problem.
- `descent_vs` is passed as a positive number; the tool negates it.

Templates: `caravan`, `b738`, `kingair`, `tbm850`.
Architectures: `turboprop`, `twin_turboprop`, `series_hybrid`,
`twin_series_hybrid`, `twin_turbofan`.

## pyCycle (`pyc`)

Module: `hangar.pyc.server`. Gas turbine thermodynamic cycle analysis.

```bash
uv run python -m hangar.pyc.server                            # stdio
uv run python -m hangar.pyc.server --transport http --port 8002
```

Environment variables:
- `PYC_HOST`, `PYC_PORT`, `PYC_TRANSPORT`
- `HANGAR_PROV_DB` (shared)

Tools:

| Group | Tools |
|-------|-------|
| Engine | `create_engine` |
| Analysis | `run_design_point`, `run_off_design`, `reset` |
| Session | `configure_session`, `set_requirements`, `pin_run`, `unpin_run` |
| Observability | `get_run`, `get_detailed_results`, `get_last_logs` |
| Artifacts | `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact` |
| Visualisation | `visualize` |
| Provenance | `start_session`, `log_decision`, `link_cross_tool_result`, `export_session_graph` |

pyc-specific gotchas:
- `run_design_point` MUST be called before `run_off_design` - the design
  point sizes the engine; off-design uses fixed geometry.
- `T4_target` should not exceed ~3600 degR (material limits).
- Newton solver requires good initial guesses; defaults are reasonable
  but extreme operating conditions may need tuning.
- Available archetypes: `turbojet` (more in the pipeline).
- See [[pyc-direct-od-squawk]] and [[pyc-surrogate-extrapolation]] memory
  notes for known modelling pitfalls on optimisation loops.

## Running multiple servers at once

Each server is independent. For a typical multi-tool agent session you
will have OAS + OCP (and sometimes pyc) all running. With stdio they are
launched by Claude Code from `.mcp.json`; with HTTP each binds its own
port. Only one process per port and only one viewer per port (7654 by
default; subsequent servers fall back if it's taken).

## Provenance DB layout

Single SQLite DB shared across all servers (per the
`HANGAR_PROV_DB` env var, default `hangar_data/.provenance/sessions.db`):

| Table | Contents |
|-------|----------|
| `sessions` | Named provenance sessions, one row per `start_session()` |
| `tool_calls` | Every captured tool call (auto-recorded by `@capture_tool`) |
| `decisions` | `log_decision` records |
| `cross_references` | `link_cross_tool_result` records - cross-tool handoffs |

The viewer queries this DB directly. Both OAS and OCP can write to the
same DB; that is what makes cross-tool provenance work.
