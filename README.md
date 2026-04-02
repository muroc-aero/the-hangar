# the-hangar

Open-source MCP servers and CLI tools for aerospace design and MDO, built for AI agents.

**[mcp.lakesideai.dev](https://mcp.lakesideai.dev/)** -- hosted servers ready to connect.

## Hosted servers

Public instances are available at `mcp.lakesideai.dev`. Authentication uses Keycloak OIDC (browser login on first connection).

| Server | Endpoint | Description |
|--------|----------|-------------|
| OAS | `https://mcp.lakesideai.dev/oas/mcp` | Aerostructural analysis and optimization of lifting surfaces. Couples VLM aerodynamics with finite-element structures for wing design. |
| OCP | `https://mcp.lakesideai.dev/ocp/mcp` | Aircraft conceptual design and mission analysis. Fuel burn, takeoff performance, and battery SOC for conventional and hybrid-electric architectures. |
| PYC | `https://mcp.lakesideai.dev/pyc/mcp` | Gas turbine engine cycle analysis. Design-point sizing and off-design performance with full thermodynamic station modeling. |

### Connecting

**Claude Code:**

```bash
claude mcp add --transport http oas https://mcp.lakesideai.dev/oas/mcp
claude mcp add --transport http ocp https://mcp.lakesideai.dev/ocp/mcp
claude mcp add --transport http pyc https://mcp.lakesideai.dev/pyc/mcp
```

**claude.ai:** Settings > Integrations > Add MCP Server, then enter the endpoint URL.

## Local setup

Clone and install, then start Claude Code from the repo root. The `.mcp.json` already configures all three servers as local MCP connections.

```bash
git clone https://github.com/muroc-aero/the-hangar && cd the-hangar
uv sync
claude
```

Claude Code will automatically start the OAS, OCP, and PYC servers via the `.mcp.json` config.

To also enable the CLI-guide skills (so you can run analyses without MCP, using `oas-cli`, `ocp-cli`, `pyc-cli` directly), sync the skills into `.claude/`:

```bash
bash scripts/sync-skills.sh
```

This copies the CLI-guide skills from each package into `.claude/skills/` where Claude Code picks them up. Re-run after pulling new changes.

## Packages

| Package | Namespace | Description | CLI |
|-----------|-----------|-------------|-----|
| `hangar-sdk` | `hangar.sdk` | Shared infrastructure -- provenance, response envelopes, validation, session management | -- |
| `hangar-oas` | `hangar.oas` | OpenAeroStruct aerostructural analysis server | `oas-cli`, `oas-server` |
| `hangar-ocp` | `hangar.ocp` | OpenConcept aircraft conceptual design and mission analysis server | `ocp-cli`, `ocp-server` |
| `hangar-pyc` | `hangar.pyc` | pyCycle gas turbine cycle analysis server | `pyc-cli`, `pyc-server` |
| `hangar-viewer` | `hangar.viewer` | Unified provenance viewer for Hangar tool servers | `hangar-viewer` |

These packages are not on PyPI. Install from the repo:

```bash
cd the-hangar
uv sync
```

This installs all packages in development mode. To install a subset into another project:

```bash
uv pip install -e packages/sdk -e packages/oas
```

## Project layout

```
the-hangar/
├── packages/
│   ├── sdk/                    # hangar-sdk
│   │   └── src/hangar/sdk/
│   ├── oas/                    # hangar-oas (OpenAeroStruct)
│   │   └── src/hangar/oas/
│   ├── ocp/                    # hangar-ocp (OpenConcept)
│   │   └── src/hangar/ocp/
│   ├── pyc/                    # hangar-pyc (pyCycle)
│   │   └── src/hangar/pyc/
│   └── viewer/                 # hangar-viewer (provenance viewer)
│       └── src/hangar/viewer/
├── skills/                     # cross-tool workflow skills
├── upstream/                   # local clones of upstream repos (git-ignored)
├── docker/
└── scripts/
```

Every package shares the `hangar` Python namespace ([PEP 420](https://peps.python.org/pep-0420/) implicit namespace packages). Each is independently installable and pulls in `hangar-sdk` automatically.

**Important:** there must be no `__init__.py` in `src/hangar/` — only at the leaf level (e.g. `src/hangar/oas/__init__.py`). This is what makes the namespace work across separately installed packages.

## Development

```bash
# Clone and set up
git clone https://github.com/muroc-aero/the-hangar && cd the-hangar
uv sync

# Run an MCP server
uv run oas-server
uv run ocp-server
uv run pyc-server

# Run a CLI
uv run oas-cli interactive
uv run ocp-cli interactive
uv run pyc-cli interactive

# Run tests
uv run pytest packages/sdk/tests/
uv run pytest packages/oas/tests/
uv run pytest packages/ocp/tests/
uv run pytest packages/pyc/tests/

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

## Contributing

We welcome contributions of MCP server wrappers for other engineering tools. The SDK provides shared infrastructure for response envelopes, provenance tracking, validation, and artifact storage, so you can focus on the tool-specific logic.

Check the [issues](https://github.com/muroc-aero/the-hangar/issues) and [discussions](https://github.com/muroc-aero/the-hangar/discussions) on GitHub to see what tools are being considered, propose new ones, or pick up an existing request.

## References

This project wraps the following open-source tools. If you use them in published work, please cite the original papers.

**OpenAeroStruct** -- [mdolab/OpenAeroStruct](https://github.com/mdolab/OpenAeroStruct)

> Jasa, J. P., Hwang, J. T., and Martins, J. R. R. A., "Open-source coupled aerostructural optimization using Python," *Structural and Multidisciplinary Optimization*, Vol. 57, No. 4, 2018, pp. 1815--1827. [doi:10.1007/s00158-018-1912-8](https://doi.org/10.1007/s00158-018-1912-8)

**OpenConcept** -- [mdolab/openconcept](https://github.com/mdolab/openconcept)

> Brelje, B. J. and Martins, J. R. R. A., "Development of a Conceptual Design Model for Aircraft Electric Propulsion with Efficient Gradients," AIAA/IEEE Electric Aircraft Technologies Symposium, AIAA Paper 2018-4979, Cincinnati, OH, 2018. [doi:10.2514/6.2018-4979](https://doi.org/10.2514/6.2018-4979)

**pyCycle** -- [OpenMDAO/pyCycle](https://github.com/OpenMDAO/pyCycle)

> Hendricks, E. S. and Gray, J. S., "pyCycle: A Tool for Efficient Optimization of Gas Turbine Engine Cycles," *Aerospace*, Vol. 6, No. 87, 2019. [doi:10.3390/aerospace6080087](https://doi.org/10.3390/aerospace6080087)

## License

See [LICENSE](LICENSE).
