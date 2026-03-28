# the-hangar

Open-source MCP servers and CLI tools for aerospace design and MDO, built for AI agents.

## Packages

| PyPI name | Namespace | Description |
|-----------|-----------|-------------|
| `hangar-sdk` | `hangar.sdk` | Shared infrastructure — provenance, response envelopes, validation, session management |
| `hangar-oas` | `hangar.oas` | OpenAeroStruct aerostructural analysis server |

Install everything:

```bash
pip install hangar
```

Or just what you need:

```bash
pip install hangar-oas
```

## Project layout

```
the-hangar/
├── packages/
│   ├── sdk/                    # hangar-sdk
│   │   └── src/hangar/sdk/     # hangar.sdk namespace
│   ├── oas/                    # hangar-oas
│   │   └── src/hangar/oas/     # hangar.oas namespace
│   └── <tool>/                 # future tools follow the same pattern
│       └── src/hangar/<tool>/
├── skills/                     # cross-tool workflow skills
├── upstream/                   # local clones of upstream repos (git-ignored)
├── docker/
└── scripts/
```

Every package shares the `hangar` Python namespace ([PEP 420](https://peps.python.org/pep-0420/) implicit namespace packages). Each is independently installable — `pip install hangar-oas` pulls in `hangar-sdk` automatically but nothing else.

**Important:** there must be no `__init__.py` in `src/hangar/` — only at the leaf level (e.g. `src/hangar/oas/__init__.py`). This is what makes the namespace work across separately installed packages.

## Development

```bash
# Clone and set up
git clone https://github.com/<org>/the-hangar && cd the-hangar
uv sync

# Run the OAS server
uv run python -m hangar.oas.server

# Run tests
uv run pytest packages/oas/tests/
uv run pytest packages/sdk/tests/

# Docker
docker compose -f docker/docker-compose.yml up --build
```

## Adding a new tool

1. Create `packages/<tool>/` following the `oas/` structure
2. Add `src/hangar/<tool>/` with your server and tools — **no `__init__.py` in `src/hangar/`**
3. Set `name = "hangar-<tool>"` in your `pyproject.toml` with `hangar-sdk` as a dependency
4. Add tool-specific skills in `packages/<tool>/skills/`
5. Add upstream clone to `scripts/setup-upstream.sh`
6. Add to `docker/docker-compose.yml`

## License

See [LICENSE](LICENSE).
