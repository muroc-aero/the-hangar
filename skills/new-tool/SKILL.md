---
name: new-tool
description: >
  Scaffold a new MCP tool server in the Hangar workspace. Covers the full
  process from scoping the upstream tool through deployment and CLI guide
  creation. Use this skill when adding a new engineering analysis tool to
  the monorepo.
---

# Adding a New Tool

Follow these steps in order. Each step should be completed and verified before
moving to the next.

## 1. Scope the tool

Before writing any code, study the upstream tool to determine:

- Which analyses, solvers, and workflows to expose as MCP tools
- The golden tests and demonstration examples that are critical for validation
- The key input parameters, output quantities, and failure modes
- Any upstream constraints or gotchas that need documenting

Read the upstream source (clone to `upstream/` via `scripts/setup-upstream.sh`)
and identify the core entry points. The goal is a focused tool surface, not a
1:1 wrapping of every function.

## 2. Scaffold the MCP server

Create the package directory structure:

```
packages/<pkg>/
  pyproject.toml
  Dockerfile
  CLAUDE.md
  skills/
  tests/
  src/
    hangar/
      <pkg>/
        __init__.py
        server.py
        config/
          defaults.py
        tools/
          __init__.py
          analysis.py
          session.py
        cli.py
```

**Critical:** do NOT create `__init__.py` in `src/hangar/` -- only at the leaf
level (e.g. `src/hangar/<pkg>/__init__.py`). This is required for PEP 420
implicit namespace packages.

Use the SDK infrastructure throughout:

- `@capture_tool` decorator for provenance tracking on every tool
  (it also converts typed `HangarError`s into the error envelope)
- `make_envelope()` for response wrapping
- `ValidationFinding` for physics and numerics checks, plus
  `requirements_findings()` from `hangar.sdk.validation.requirements`
  inside your `_finalize_analysis` (do not re-implement the
  requirements-to-findings loop)
- `ArtifactStore` for run result persistence
- `SessionManager` for in-memory state and caching; pass a
  `session_factory` (a `Session` subclass) if the tool needs typed
  per-session state (see `hangar.pyc.state.PycSession`)

The shared server plumbing lives in the SDK -- do NOT copy it from
another package:

- `main()` is a thin wrapper over
  `hangar.sdk.server_main.run_server_main(mcp, tool=..., env_prefix=...,
  default_port=..., description=...)`, which handles argparse, provenance
  seeding, the stdio viewer banner, the HTTP transport + authenticated
  viewer routes, the no-auth warning, and `/healthz`. Pick the next free
  default port (8000=oas, 8001=ocp, 8002=pyc).
- The four provenance tools come from
  `hangar.sdk.provenance.tools.build_provenance_tools(_sessions)`;
  assign `start_session` / `log_decision` / `link_cross_tool_result` /
  `export_session_graph` from the returned namespace in `tools/session.py`.

Follow the patterns in `packages/oas/` and `packages/ocp/` for:

- `pyproject.toml` -- set `name = "hangar-<pkg>"`, depend on `hangar-sdk`
- `server.py` -- FastMCP construction, tool/resource/prompt registration
- `tools/session.py` -- session/artifact/observability tools
- `config/defaults.py` -- default parameter values

Add the package to the root `pyproject.toml` workspace members.
Add the upstream clone to `scripts/setup-upstream.sh`.

## 3. Integrate the viewer

The stdio daemon-thread viewer and the authenticated HTTP viewer routes are
already wired by `run_server_main`; just verify:

- `HANGAR_PROV_DB` and `HANGAR_DATA_DIR` env vars reach the server
- The viewer Cytoscape DAG shows tool calls after a test session
- `register_plot_types()` / `register_plot_generator()` are called at
  import time in `server.py` for the package's plot types

## 4. Set up the CLI

Create a CLI interface that exposes all MCP tools through the command line:

- Create `cli.py` with a registry builder following the OAS/OCP pattern
- Register console_scripts in `pyproject.toml`: `<pkg>-cli` and `<pkg>-server`
- Support all three CLI modes: interactive, one-shot, and script
- The CLI should use the exact same tool functions as the MCP server

## 5. Verify auth and access

Confirm the server's auth and user access setup matches the other packages:

- OIDC JWT authentication via `hangar.sdk.auth`
- Transport selection (stdio for local, http for deployed)
- `<PKG>_TRANSPORT`, `<PKG>_HOST`, `<PKG>_PORT` env var naming convention
- The `.well-known/oauth-protected-resource` endpoint works correctly

## 6. Run full integration tests

Run a complete CLI test covering all tools and visualization:

```bash
# Unit and golden physics tests
uv run pytest packages/<pkg>/tests/

# Interactive CLI smoke test -- exercise every tool
uv run <pkg>-cli interactive

# Verify visualization artifacts are generated
# Verify provenance DAG builds correctly
```

All tools should produce valid response envelopes, pass validation checks,
and generate artifacts. Check that visualization plots render without errors.

## 7. Set up deployment

Add deployment configuration following the existing patterns:

**docker-compose.yml** -- add a service entry:

```yaml
  <pkg>:
    build:
      context: ..
      dockerfile: packages/<pkg>/Dockerfile
    ports:
      - "<next_port>:8000"
    volumes:
      - ./hangar_data/<pkg>:/data
    env_file:
      - path: .env
        required: false
    environment:
      <PKG>_TRANSPORT: http
      <PKG>_HOST: 0.0.0.0
      HANGAR_DATA_DIR: /data
      HANGAR_PROV_DB: /data/provenance.db
```

Also add a read-only volume mount in the `viewer` service for the new package.

**Caddyfile** -- add routing rules:

```
  # --- <PKG> ---
  handle /.well-known/oauth-protected-resource/<pkg> {
      reverse_proxy <pkg>:8000
  }
  handle_path /<pkg>/* {
      reverse_proxy <pkg>:8000
  }
```

**Keycloak** -- document in `packages/<pkg>/DEPLOY.md`:

- The OIDC client setup (client ID, redirect URIs, scopes)
- Required environment variables for the `.env` file
- Any tool-specific deploy considerations

## 8. Update project config

- Add the server to `.mcp.json` for local Claude Code usage
- Update the `viewer` service's `HANGAR_VIEWER_DBS` env var
- Run `uv sync` to verify the workspace resolves cleanly

## 9. Create the CLI guide skill

Create a `<pkg>-cli-guide` skill in `packages/<pkg>/skills/<pkg>-cli-guide/`:

- `SKILL.md` -- main guide covering prerequisites, all three CLI modes,
  and tool-specific usage
- `commands.md` -- all tools with parameters and example invocations
- `modes.md` -- interactive, one-shot, and script mode protocols
- `provenance.md` -- session tracking and decision logging
- `examples/` -- complete workflow recipes

Follow the structure of `packages/oas/skills/oas-cli-guide/` exactly.

After creating, run `bash scripts/sync-skills.sh` to populate `.claude/skills/`.

## Namespace checklist

- [ ] `src/hangar/` has NO `__init__.py`
- [ ] `src/hangar/<pkg>/__init__.py` exists
- [ ] Package name uses hyphens: `hangar-<pkg>`
- [ ] Python import uses dots: `hangar.<pkg>`
- [ ] Package is in root `pyproject.toml` workspace members
- [ ] `.mcp.json` includes the new server
- [ ] `docker-compose.yml` includes the new service
- [ ] `Caddyfile` includes routing rules
- [ ] Viewer service has read-only volume mount for new package data
- [ ] CLI guide skill exists and syncs correctly
