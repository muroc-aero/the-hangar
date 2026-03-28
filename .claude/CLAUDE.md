# Hangar Workspace

## What this is
A monorepo for MCP servers that expose engineering analysis tools to AI agents.
Each tool gets its own package under `packages/`. Shared infrastructure lives
in `packages/sdk/`.

## Namespace convention
All packages use the `hangar.*` Python namespace (PEP 420 implicit namespace packages).
- `hangar.sdk` — shared provenance, response envelopes, validation, session management
- `hangar.oas` — OpenAeroStruct aerostructural analysis server
- PyPI names use hyphens: `hangar-sdk`, `hangar-oas`
- **Critical:** never place an `__init__.py` in `src/hangar/` — only at the leaf
  level (e.g. `src/hangar/oas/__init__.py`). This is what makes the namespace work.

## Source layout
- `packages/sdk/` — hangar-sdk: provenance, response envelopes, validation,
  session management, visualization
- `packages/oas/` — hangar-oas: OpenAeroStruct aerostructural analysis server
- `skills/` — cross-tool process skills (design study workflows, etc.)
- `upstream/` — local clones of upstream tool repos (read-only reference, git-ignored)

## When implementing or modifying OAS tools
Always read the relevant upstream source before writing tool code.
If `upstream/OpenAeroStruct` exists, the OAS source is there.
Otherwise, it's in the venv at `.venv/lib/python3.11/site-packages/openaerostruct/`.

Key OAS entry points:
- `openaerostruct/aerostruct_groups/` — problem setup classes
- `openaerostruct/functionals/` — objective/constraint functions
- `openaerostruct/structures/` — structural analysis components
- `openaerostruct/aerodynamics/` — VLM and aero components

## When implementing SDK infrastructure
Read `packages/sdk/src/hangar/sdk/provenance/` for the provenance model.
The middleware in `middleware.py` auto-captures every tool call — new tools
get provenance for free if they use the `@tracked_tool` decorator.

## Known OAS failure modes (critical context)
- OAS silently ignores unrecognized design variable names — always validate
  DV names against the known set before optimization
- load_factor has a caching bug — always set it explicitly per analysis
- OAS cannot model TTBW strut load relief — do not attempt strut-braced
  wing studies without documenting this limitation
- Optimizer converging in 1-2 iterations usually means DV bounds are wrong
  or DVs are not being applied

## Running the server
```bash
# Development (from workspace root)
uv sync
uv run python -m hangar.oas.server

# Docker
docker compose -f docker/docker-compose.yml up --build
```

## Testing
```bash
uv run pytest packages/oas/tests/
uv run pytest packages/sdk/tests/
uv run pytest tests/integration/
```

## Adding a new tool
1. Create `packages/<toolname>/` following the `oas/` structure
2. Add `src/hangar/<toolname>/` — no `__init__.py` in `src/hangar/`
3. Add tool-specific skills in `packages/<toolname>/skills/`
4. Import and use `hangar.sdk` for provenance, envelopes, validation
5. Add upstream clone to `scripts/setup-upstream.sh`
6. Add to `docker/docker-compose.yml`
