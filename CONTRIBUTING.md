# Contributing to The Hangar

Thanks for considering a contribution. The Hangar is an open-source monorepo of MCP servers that wrap aerospace engineering analysis tools (OpenAeroStruct, OpenConcept, pyCycle, and a general-purpose OpenMDAO plan runner). We welcome contributions that extend the ecosystem, improve the existing servers, or document workflows.

## Ways to contribute

- **Report a bug** — open a [GitHub issue](https://github.com/muroc-aero/the-hangar/issues) with a minimal reproducer. Include the package (`oas`, `ocp`, `pyc`, `omd`, or `sdk`), the command or tool call that fails, and the version (`git rev-parse --short HEAD`).
- **Propose a feature** — start a [discussion](https://github.com/muroc-aero/the-hangar/discussions) before writing significant code. For new MCP tools, see [Adding a new tool](#adding-a-new-tool) below.
- **Improve docs** — the project README, package READMEs, and the skills under `skills/` and `packages/<pkg>/skills/` are all fair game.
- **Add a case study** — reproductions of published MDAO results are especially welcome. See `deploy/landing/studies/` for the format.
- **Wrap a new tool** — add a new MCP server for an engineering analysis tool. See [Adding a new tool](#adding-a-new-tool).

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct, version 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold this standard. Report unacceptable behavior through the [Security](#security) channel described below.

## Getting set up

```bash
git clone https://github.com/muroc-aero/the-hangar && cd the-hangar
bash scripts/dev-setup.sh   # installs all packages + CLI entry points
```

This installs every package (`hangar-sdk`, `hangar-oas`, `hangar-ocp`, `hangar-pyc`, `hangar-omd`, `hangar-viewer`) in editable mode and registers the CLIs (`oas-cli`, `ocp-cli`, `pyc-cli`, `omd-cli`).

Verify the setup:

```bash
uv run pytest packages/sdk/tests/ -q
uv run oas-cli --help
```

See the top-level `README.md` and `.claude/CLAUDE.md` for architecture notes and package-layout conventions.

## Development workflow

1. **Fork** the repo and create a topic branch off `main`:
   ```bash
   git checkout -b <your-username>/<short-description>
   ```
2. **Write code and tests.** Follow the conventions below.
3. **Run the test suite** for the packages you touched:
   ```bash
   uv run pytest packages/sdk/tests/ packages/oas/tests/ packages/omd/tests/
   uv run pytest -m "not slow"   # skip long integration tests while iterating
   ```
4. **Commit** with clear messages (see [Commit messages](#commit-messages)).
5. **Push** your branch and open a pull request against `main`.

## Code style

- Python 3.11+. `uv` manages the environment.
- `ruff` handles formatting and linting (config in `pyproject.toml`). Run `uv run ruff check .` and `uv run ruff format .` before pushing.
- Type hints are expected on new public APIs.
- Keep the SDK (`hangar-sdk`) dependency-free of tool packages. Tool packages depend on the SDK, not the other way around.
- Namespace rule: **never** add `__init__.py` inside `src/hangar/`. Leaf packages (`src/hangar/oas/__init__.py`, etc.) only. This is what keeps the `hangar.*` namespace working across separately-installable packages.

## Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/) for new contributions:

```
<type>(<scope>): <short summary>

<optional body explaining why>

<optional footer, e.g. Refs #42 or BREAKING CHANGE: ...>
```

- **Type** (required): `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, or `revert`.
- **Scope** (optional but encouraged): the package or area — `oas`, `ocp`, `pyc`, `omd`, `sdk`, `deploy`, `landing`, `docs`.
- **Summary**: imperative mood, under 72 characters, no trailing period.
- **Body**: explain *why*, not *what*. The diff already shows what.
- **Footer**: reference issues with `Fixes #123` or `Refs #123`. Breaking changes use `BREAKING CHANGE: <description>`.

Example:

```
feat(oas): add stability-derivative tool

Exposes Cmalpha, CLalpha, and sideslip response from the VLM
solver for agents that need stability feedback inline.

Refs #42
```

Do not mix unrelated changes in a single commit.

## Contribution licensing

No CLA or DCO sign-off is required. Apache License 2.0 Section 5 already grants the necessary contribution-licensing rights when you open a pull request against this repository.

## Testing

- Unit tests live in `packages/<pkg>/tests/`. Add tests for any new tool, factory, or SDK primitive.
- Integration tests that invoke full solver pipelines are marked `@pytest.mark.slow`. Run them before submitting a PR that touches a solver:
  ```bash
  uv run pytest packages/oas/tests/ -m slow
  ```
- New MCP tools need a round-trip test through the CLI (interactive, one-shot, and batch modes). The `oas-cli-guide` skill has examples.

## Pull request process

1. Ensure tests pass locally (`pytest` + `ruff`).
2. Update the relevant package `README.md` and any affected skill under `packages/<pkg>/skills/` or top-level `skills/`.
3. Open the PR against `main` with a clear description: what changed, why, how to verify.
4. PRs require one maintainer approval and all CI checks green before merge.
5. The maintainer will squash-merge once approved unless you request otherwise.

Maintainers: [@muroc-aero](https://github.com/muroc-aero).

## Adding a new tool

Wrapping a new engineering analysis tool is the most involved contribution type. The process is documented in the `/new-tool` skill at [`skills/new-tool/SKILL.md`](skills/new-tool/SKILL.md). High-level steps:

1. Open a discussion or issue describing the tool and what to expose.
2. Study the upstream source (`scripts/setup-upstream.sh` clones candidates into `upstream/`).
3. Scaffold the package under `packages/<tool>/` following the `oas/` structure.
4. Integrate with `hangar-sdk` (provenance, response envelopes, validation, artifacts).
5. Add a CLI (`<tool>-cli`) and server (`<tool>-server`) entry point.
6. Write full integration tests that exercise every tool through the CLI.
7. Add a `<tool>-cli-guide` skill under `packages/<tool>/skills/`.
8. Update `docker/docker-compose.yml`, `Caddyfile`, and `.mcp.json`.

Expect multiple review rounds. Open a draft PR early for feedback on tool surface and package layout.

## Security

If you find a security issue (auth bypass, credential leak, injection), please do **not** open a public issue. Use GitHub's private vulnerability reporting:

1. Go to the [Security tab](https://github.com/muroc-aero/the-hangar/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the advisory form; only repository maintainers will see it.

The maintainer will acknowledge receipt within 3 business days and coordinate a fix and disclosure timeline.

## Community

Discussion happens on GitHub [issues](https://github.com/muroc-aero/the-hangar/issues) and [discussions](https://github.com/muroc-aero/the-hangar/discussions). There is no Slack or Discord at this time.

## Attribution

All contributors appear in the repo's Git history and GitHub contributors page. Significant contributors may be added to the README's acknowledgments section.

## License

By contributing, you agree that your contributions will be licensed under the project's [Apache License 2.0](LICENSE).
