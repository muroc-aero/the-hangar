# Hangar Workspace

## What this is
A monorepo for MCP servers and CLI tools that expose engineering analysis
capabilities to AI agents. Each tool gets its own package under `packages/`.
Shared infrastructure lives in `packages/sdk/`.

## Namespace convention
All packages use the `hangar.*` Python namespace (PEP 420 implicit namespace packages).
- `hangar.sdk` -- shared provenance, response envelopes, validation, session management,
  artifacts, telemetry, auth, visualization, CLI framework
- `hangar.oas` -- OpenAeroStruct aerostructural analysis server
- `hangar.omd` -- general-purpose OpenMDAO plan runner with factory-based components
- `hangar.range_safety` -- range safety validators and assertions
- PyPI names use hyphens: `hangar-sdk`, `hangar-oas`, `hangar-omd`, `hangar-range-safety`
- **Critical:** never place an `__init__.py` in `src/hangar/` -- only at the leaf
  level (e.g. `src/hangar/oas/__init__.py`). This is what makes the namespace work.

## Source layout

### packages/sdk/ -- hangar-sdk shared infrastructure
- `provenance/` -- SQLite DB, `@capture_tool` decorator, session graph export
- `envelope/` -- versioned response envelopes (`make_envelope`, `make_error_envelope`)
- `session/` -- session state management (surfaces, caching, pinning)
- `validation/` -- `ValidationFinding` framework + user requirements assertions
- `artifacts/` -- filesystem-backed artifact store for analysis runs
- `telemetry/` -- structured logging with per-run log capture
- `auth/` -- OIDC JWT authentication for MCP servers
- `viz/` -- plotting (matplotlib), widget (Plotly), viewer (Cytoscape.js DAG)
- `cli/` -- generic 3-mode CLI framework (interactive, one-shot, script)
- `errors.py` -- typed error taxonomy (`HangarError`, `UserInputError`, etc.)
- `state.py` -- module-level singletons (`sessions`, `artifacts`)
- `helpers.py` -- shared utilities (`_resolve_run_id`, `_suppress_output`, etc.)

### packages/oas/ -- hangar-oas OpenAeroStruct MCP server
- `server.py` -- FastMCP entry point, tool registration
- `config/defaults.py` -- flight conditions, mesh, material property defaults
- `mesh.py` -- mesh generation and geometric transforms (sweep, dihedral, taper)
- `builders.py` -- OpenMDAO problem assembly
- `results.py` -- result extraction from solved problems (reads optimized mesh from prob)
- `cli.py` -- OAS CLI registry builder (oas-cli)
- `tools/` -- MCP tool implementations (geometry, analysis, optimization, session)

### packages/omd/ -- hangar-omd general-purpose OpenMDAO plan runner
See `packages/omd/CLAUDE.md` for detailed omd architecture.
- `cli.py` -- omd-cli entry point (run, plot, results, assemble, validate, export, provenance)
- `server.py` -- FastMCP entry point, tool registration (full omd-cli parity)
- `tools/` -- MCP tool implementations (authoring, execution, results, plots)
- `run.py` -- plan execution pipeline (load, materialize, execute, record, N2)
- `materializer.py` -- converts plan YAML to OpenMDAO Problem with DVs/constraints/objective
- `registry.py` -- factory + plot provider registry
- `factories/` -- component builders (oas.py, oas_aero.py, paraboloid.py)
- `plotting/` -- factory-aware plot generation matching oas-cli style
- `db.py` -- SQLite analysis DB (provenance, run cases, metadata)
- `recorder.py` -- OpenMDAO CaseReader data import

### packages/range-safety/ -- range safety validators
### packages/ocp/ -- OpenConcept mission analysis server
### packages/pyc/ -- pyCycle gas turbine analysis server

- `skills/` -- cross-tool process skills (design study, trade study, convergence, multi-tool)
- `upstream/` -- local clones of upstream tool repos (read-only reference, git-ignored)

## When implementing or modifying OAS tools
Always read the relevant upstream source before writing tool code.
If `upstream/OpenAeroStruct` exists, the OAS source is there.
Otherwise, it's in the venv at `.venv/lib/python3.11/site-packages/openaerostruct/`.

Key OAS entry points:
- `openaerostruct/aerostruct_groups/` -- problem setup classes
- `openaerostruct/functionals/` -- objective/constraint functions
- `openaerostruct/structures/` -- structural analysis components
- `openaerostruct/aerodynamics/` -- VLM and aero components

## When implementing SDK infrastructure
- `@capture_tool` decorator in `provenance/middleware.py` -- auto-records every tool call
- `make_envelope()` in `envelope/response.py` -- wraps tool results in versioned schema
- `ValidationFinding` in `validation/checks.py` -- self-contained check framework
- `ArtifactStore` in `artifacts/store.py` -- JSON artifact persistence
- `SessionManager` in `session/manager.py` -- in-memory state + caching

## When implementing or modifying omd
See `packages/omd/CLAUDE.md` for the full guide. Key points:
- Plot functions must match oas-cli style (figure size, axis labels, suptitle with run_id)
- Plot functions read from the OpenMDAO recorder .sql via CaseReader, not from the analysis DB
- Factories must forward all surface config keys to OAS (e.g. `chord_cp`, `num_twist_cp`)
- The materializer resolves short DV/constraint names (CL, CD, S_ref, twist_cp) to full OpenMDAO paths
- N2 diagrams are generated at run time while the Problem is live

## Known OAS failure modes (critical context)
- OAS silently ignores unrecognized design variable names -- always validate
  DV names against the known set before optimization
- load_factor has a caching bug -- always set it explicitly per analysis
- OAS cannot model TTBW strut load relief -- do not attempt strut-braced
  wing studies without documenting this limitation
- Optimizer converging in 1-2 iterations usually means DV bounds are wrong
  or DVs are not being applied

## Running

```bash
# Dev environment setup (clones pinned upstreams if missing, installs all
# packages + CLI entry points; pins live in scripts/upstream-pins.env)
bash scripts/dev-setup.sh

# OAS MCP server
uv run python -m hangar.oas.server

# OAS CLI
oas-cli run-script workflow.json
oas-cli visualize --run-id <id> --plot-type planform --output file

# OMD CLI
omd-cli run plan.yaml --mode optimize
omd-cli plot <run_id> --type all
omd-cli results <run_id> --summary
omd-cli provenance <plan_id> --format text

# Docker
docker compose -f docker/docker-compose.yml up --build
```

## Testing
```bash
# All package tests (testpaths in the root pyproject scope collection to
# packages/*/tests; upstream/, demos, and example parity suites excluded)
uv run pytest

# Skip slow integration tests
uv run pytest -m "not slow"

# By package
uv run pytest packages/sdk/tests/
uv run pytest packages/oas/tests/
uv run pytest packages/omd/tests/

# Example parity suites run per-directory (each sets up its own sys.path)
uv run pytest packages/oas/examples/rectangular_wing/tests/
```

## Skills

Skills live in two places and must be kept in sync:

1. **`.claude/skills/<skill-name>/`** -- active location that Claude Code loads
   at runtime. This directory is gitignored.
2. **`packages/<pkg>/skills/<skill-name>/`** -- git-tracked source of truth.
   Cross-tool skills go in `skills/` at the repo root.

When creating or updating a skill:
1. Edit the files in `.claude/skills/<skill-name>/`
2. Copy the changed files to `packages/<pkg>/skills/<skill-name>/`
3. Commit the `packages/` copies so changes are tracked in git

A sync script populates `.claude/skills/` from the git-tracked copies.

## Adding a new tool
Use the `/new-tool` skill for the full guided process, or see
`skills/new-tool/SKILL.md`.

## Deployment

Deployment configuration and static sites live in two **private** sibling
repos (not in this repo):

- `lakesideai-sites` -- static landing pages (lakesideai.dev,
  mcp.lakesideai.dev) and case studies. Tarballs land here too.
- `lakesideai-infra` -- docker-compose, Caddyfile, .env template, ops
  docs, deploy scripts (package-case-study.sh, unpack-case-study.sh,
  patch-dag-static.py).

Expected local layout when working on deployment:

```
~/coding/the-hangar/        (this repo, public)
~/coding/lakesideai-sites/  (private)
~/coding/lakesideai-infra/  (private)
```

The packaging script (`lakesideai-infra/scripts/package-case-study.sh`)
finds `the-hangar` via the `HANGAR_REPO` env var (default: sibling
`../the-hangar`) and writes tarballs into
`lakesideai-sites/mcp.lakesideai.dev/studies/`. See
`lakesideai-infra/README.md` for the full workflow.

Case-study HTML templates and tarballs are committed in
`lakesideai-sites/mcp.lakesideai.dev/studies/<study-id>/`. The omd plan
that produces a study still lives here, under
`packages/omd/demos/<study-id>/`.

## Design system
Use the `lakesideai-design` skill for any UI work. Brand non-negotiables:
real mono numbers, no emoji, small mechanical radii, flat panels (ink rules on
paper, not shadow), green #1F9D55 + blueprint blue #15487A, IBM Plex throughout.
Product UIs use the App/Instrument surface; marketing & decks use class="surface-paper".