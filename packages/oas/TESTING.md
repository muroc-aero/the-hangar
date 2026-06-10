# Testing the OAS MCP Server

This covers the full testing flow for the OpenAeroStruct MCP server, from unit
tests through deployed HTTP verification.

## 1. Pytest — unit and integration tests

### Quick feedback loop (no OAS computation)

```bash
uv run pytest -m "not slow" packages/sdk/tests/ packages/oas/tests/
```

Covers: SDK infrastructure (provenance, session, artifacts, validation, CLI
framework) and OAS validation checks. Runs in ~2s.

### Full suite

```bash
uv run pytest packages/sdk/tests/ packages/oas/tests/
```

Includes integration tests that run real OpenAeroStruct computations on small
meshes (num_y=5). Covers all 23 MCP tools end-to-end. Runs in ~20s.

### SDK tests only

```bash
uv run pytest packages/sdk/tests/
```

Tests shared infrastructure in isolation — no OpenAeroStruct dependency.

| Test file | What it covers |
|-----------|---------------|
| `test_artifacts.py` | Artifact store: save/load/list/delete, numpy serialization, path traversal, retention |
| `test_provenance.py` | Provenance DB, `@capture_tool` decorator, start_session/log_decision/export |
| `test_session.py` | SessionManager, surface fingerprinting, cache invalidation, pinning |
| `test_validation.py` | ValidationFinding framework, requirements checking |
| `test_cli.py` | CLI framework: arg parsing, mode dispatch, state persistence, JSON serialization |

### OAS tests only

```bash
uv run pytest packages/oas/tests/
```

| Test file | What it covers |
|-----------|---------------|
| `test_oas_tools.py` | All MCP tools: create_surface, analysis, optimization, drag polar, stability, reset |
| `test_golden_physics.py` | Physics invariants: CL/CD signs, monotonicity, structural mass, convergence |
| `test_oas_validation.py` | OAS-specific validation: validate_aero, validate_aerostruct, validate_drag_polar |
| `test_oas_cli.py` | OAS CLI: tool registry, one-shot mode, script mode, interactive mode |
| `test_cli_visualization.py` | CLI viz: save-to-file, dashboard HTML, viewer URLs, session output modes |

### Pytest markers

| Marker | Purpose | Usage |
|--------|---------|-------|
| `slow` | Integration tests with real OAS computation | `pytest -m "not slow"` to skip |
| `golden_physics` | Physics-invariant checks (Tier 1) | `pytest -m golden_physics` |
| `golden_numerics` | Platform-dependent numeric baselines (Tier 2) | `pytest -m golden_numerics` |
| `parity` | Parity vs direct OAS API | `pytest -m parity` |

### Reproducibility

For deterministic numerics across CI platforms:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 uv run pytest packages/oas/tests/
```

## 2. CLI smoke test

The CLI exercises the same code paths as MCP tools, without needing an MCP
client. Useful for quick manual verification.

```bash
# List all available tools
uv run oas-cli list-tools

# Create a surface and run analysis (one-shot mode, state persisted between calls)
uv run oas-cli --pretty create-surface --name wing --span 10 --num-y 7
uv run oas-cli --pretty run-aero-analysis --surfaces '["wing"]' --alpha 5
uv run oas-cli --pretty compute-drag-polar --surfaces '["wing"]' --alpha-start -2 --alpha-end 10

# Structural analysis (requires FEM properties)
uv run oas-cli --pretty create-surface --name sw --span 10 --num-y 7 \
  --fem-model-type tube --E 70e9 --G 30e9 --yield-stress 500e6 --mrho 3e3
uv run oas-cli --pretty run-aerostruct-analysis --surfaces '["sw"]' --alpha 5

# Optimization
uv run oas-cli --pretty run-optimization \
  --surfaces '["wing"]' --analysis-type aero --objective CD \
  --design-variables '[{"name":"twist_cp","lower":-10,"upper":10}]' \
  --constraints '[{"name":"CL","equals":0.5}]' --alpha 5

# Observability
uv run oas-cli list-runs
uv run oas-cli --pretty get-run --run-id latest
uv run oas-cli --pretty visualize --run-id latest --plot-type lift_distribution --output file

# Batch script mode
uv run oas-cli --pretty run-script workflow.json

# Clean up
uv run oas-cli reset
```

### What the CLI tests

- Tool argument parsing and JSON coercion
- One-shot state persistence across invocations (`~/.hangar/state/`)
- Script mode with `$prev.run_id` interpolation
- Interactive JSON-lines protocol
- All 23 tools callable by name

## 3. Local MCP server (stdio)

Test the server as Claude Code sees it.

### Start the server

```bash
uv run python -m hangar.oas.server
```

Or via the console script:

```bash
uv run oas-server
```

Both start in stdio mode. The provenance viewer daemon starts automatically on
a random port (printed to stderr).

### Configure Claude Code

`.mcp.json` at the project root:

```json
{
  "mcpServers": {
    "OpenAeroStruct": {
      "command": "uv",
      "args": ["run", "--directory", "<path-to-the-hangar>", "python", "-m", "hangar.oas.server"],
      "env": {
        "OAS_DATA_DIR": "<path-to-the-hangar>/oas_data"
      }
    }
  }
}
```

### Smoke test workflow

In a Claude Code session with the MCP server connected:

1. `start_session(notes="test")`
2. `create_surface(name="wing", span=10, num_y=7)`
3. `run_aero_analysis(surfaces=["wing"], alpha=5)`
4. `compute_drag_polar(surfaces=["wing"])`
5. `run_optimization(surfaces=["wing"], analysis_type="aero", objective="CD", design_variables=[{"name":"twist_cp","lower":-10,"upper":10}], constraints=[{"name":"CL","equals":0.5}])`
6. `get_run(run_id="latest")`
7. `visualize(run_id="latest", plot_type="lift_distribution")`
8. `export_session_graph(session_id=<from step 1>)`

### What to verify

- All 23 tools appear in the MCP tool list
- Response envelopes have `schema_version`, `run_id`, `validation`, `telemetry`
- Validation block shows `passed: true` for normal cases
- Provenance graph captures the full workflow
- Artifacts persist to `oas_data/`

## 4. Deployed HTTP server (Docker)

### Build and start

```bash
docker compose -f docker/docker-compose.yml up --build
```

Exposes:
- Port **8000** — MCP HTTP transport (`/mcp` endpoint)
- Port **7654** — Provenance viewer/dashboard

### Verify endpoints

```bash
# Health check (MCP streamable HTTP)
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{}}}'

# Provenance viewer
open http://localhost:7654/viewer

# Session list
curl http://localhost:7654/sessions
```

### Configure Claude Code for HTTP

```json
{
  "mcpServers": {
    "OpenAeroStruct": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OAS_TRANSPORT` | `stdio` | Transport protocol (`stdio` or `http`) |
| `OAS_HOST` | `127.0.0.1` | HTTP bind address |
| `OAS_PORT` | `8000` | HTTP bind port |
| `OAS_DATA_DIR` | `./oas_data` | Artifact storage root |
| `OAS_PROV_DB` | `~/.oas_provenance/sessions.db` | Provenance SQLite path |
| `OAS_LOG_LEVEL` | `INFO` | Log verbosity |

### With OIDC authentication

For production HTTP deployments, set these env vars to enable JWT validation:

```bash
OIDC_ISSUER_URL=https://your-provider/.well-known/openid-configuration
OIDC_CLIENT_ID=your-client-id
OIDC_CLIENT_SECRET=your-client-secret
```

The server validates RS256 JWTs from the configured OIDC provider on every
request. Without these vars, HTTP mode runs unauthenticated (a warning is
printed to stderr).

## 5. Adding a new tool server

When adding a new tool (e.g., OpenConcept), its test structure should mirror
the OAS pattern:

```
packages/<tool>/tests/
├── conftest.py              # Shared fixtures, session isolation
├── test_oas_tools.py        # Integration tests for all MCP tools
├── test_golden_physics.py   # Physics invariant checks
└── test_<tool>_validation.py  # Tool-specific validation
```

Note: test file names must be unique across `packages/*/tests/` because pytest
collects them without `__init__.py` packages. Prefix with the tool name
(e.g., `test_oas_cli.py` not `test_cli.py`) when there's a collision risk with
SDK tests.
