# Plan: hangar-evtol — evtolpy MCP server + CLI

Add `packages/evtol/` wrapping [starbelt/evtolpy](https://github.com/starbelt/evtolpy)
(eVTOL sizing and mission-energy analysis), patterned on the existing
`packages/ocp/` and `packages/pyc/` servers, and evaluated with three-lane
parity examples built from upstream's core mission-segment analyses.

## Upstream summary

evtolpy sizes electric VTOL aircraft (multirotor, lift+cruise, tilt-rotor,
vectored thrust) by iterating MTOW against subsystem masses, battery
requirements, and per-segment mission energy. Key facts that shape the
wrapper:

- **API**: one entry point — `evtol.aircraft.Aircraft(path_to_cfg.json)`.
  Construction parses the JSON config, composes `environ` / `mission` /
  `power` / `propulsion` sub-objects, and converges MTOW (`_iterate_mtow`,
  with divergence safeguards as of upstream #18/#19). Results are read off
  attributes/properties afterwards (e.g. `cruise_cl`, `wing_area_m2`,
  `total_mission_energy_kw_hr`, per-segment `*_energy_kw_hr` /
  `*_avg_electric_power_kw` across 18 mission phases including reserves).
- **Inputs**: a single JSON config with five sections (aircraft, mission,
  power, propulsion, environ). `sample-inputs/` has per-class test configs
  plus a combined `test-all.json`.
- **Core analyses ("lanes" upstream calls them analysis directories)**:
  `analysis/mission-segment-energy`, `analysis/mission-segment-power`,
  `analysis/mission-segment-weight` (plus the specialized
  `mission-segment-abu-analysis` and `sim-at` publication outputs). Each
  follows `log_*.py cfg.json -> CSV -> plt_*.py -> plot`.
- **Packaging**: none — no `setup.py`/`pyproject.toml`, not on PyPI. Only
  hard dependency is matplotlib. `evtol/` has an `__init__.py`, so it is a
  normal importable package once on the path. MIT license. Pure Python, no
  OpenMDAO — this will be the lightest hangar server.

## Phase 0 — upstream integration

1. **Pin** in `scripts/upstream-pins.env`:
   ```bash
   # evtolpy (main, post SciTech 2026 artifact; MTOW/EPU divergence safeguards)
   EVTOL_REF=63d86971300485bad1ee6dbfc3ab9a85ee7c4ce4
   ```
2. **Sync** in `scripts/setup-upstream.sh` (required group, since uv sync
   will need it):
   ```bash
   sync_repo evtolpy https://github.com/starbelt/evtolpy "$EVTOL_REF"
   ```
3. **Packaging shim**: evtolpy has no project metadata, so the
   `[tool.uv.sources]` editable-path pattern used for OAS/OCP/pyCycle won't
   work as-is. Use the managed-patch mechanism already proven for pyCycle's
   numpy2 patch: `scripts/evtolpy-packaging.patch` adds a minimal
   `pyproject.toml` to the clone (name `evtolpy`, version from the pinned
   ref, `packages = ["evtol"]`, dependency `matplotlib`). Apply/reverse-apply
   around `sync_repo` exactly like `pycycle_patch`/`pycycle_unpatch`
   (generalize those helpers to `apply_managed_patch <repo> <patch>` rather
   than duplicating). Open an upstream PR offering the pyproject so the
   patch can eventually be dropped.
4. Smoke test: `uv sync` then
   `python -c "from evtol.aircraft import Aircraft"`.
5. **Dockerfile** for `packages/evtol/` must clone+patch the pinned upstream
   the same way the ocp/pyc Dockerfiles handle theirs (ARG default from
   `upstream-pins.env`).

## Phase 1 — package skeleton

`packages/evtol/` mirroring ocp/pyc layout (namespace rule: `__init__.py`
only at `src/hangar/evtol/`, never `src/hangar/`):

```
packages/evtol/
├── CLAUDE.md                # constraints doc (see Phase 5)
├── Dockerfile
├── pyproject.toml
├── src/hangar/evtol/
│   ├── __init__.py
│   ├── __main__.py
│   ├── server.py            # FastMCP + tool registration
│   ├── cli.py               # registry builder + 3-mode CLI main
│   ├── state.py             # EvtolSession + SessionManager singletons
│   ├── builders.py          # config-dict assembly -> Aircraft construction
│   ├── results.py           # attribute harvest -> results payloads
│   ├── validation.py        # ValidationFinding checks on results
│   ├── validators.py        # input validators (raise ValueError)
│   ├── study_runner.py      # hangar.study_runners entry point
│   ├── reference.md         # MCP resource: parameter/units reference
│   ├── workflows.md         # MCP resource: workflow guide
│   ├── config/
│   │   ├── defaults.py      # default config sections + vehicle templates
│   │   └── limits.py        # sanity bounds for validators
│   ├── tools/
│   │   ├── _helpers.py      # _finalize_analysis (envelope+artifact+prune)
│   │   ├── vehicle.py       # define_vehicle, load_vehicle_template, ...
│   │   ├── mission.py       # configure_mission
│   │   ├── analysis.py      # run_sizing, run_mission_analysis
│   │   ├── sweep.py         # run_parameter_sweep
│   │   ├── session.py       # session/artifact/provenance tools (SDK glue)
│   │   ├── prompts.py
│   │   └── resources.py
│   └── viz/plotting.py      # segment-energy/power/weight plots
├── skills/evtol-cli-guide/  # SKILL.md, commands.md, modes.md,
│   └── ...                  # provenance.md, evals/, examples/
├── examples/                # Phase 3 (three-lane parity suite)
└── tests/
```

**pyproject.toml** (same template as ocp/pyc):

```toml
[project]
name = "hangar-evtol"
requires-python = ">=3.11"
dependencies = ["hangar-sdk[all]", "evtolpy", "numpy>=1.21", "matplotlib"]

[project.scripts]
evtol-server = "hangar.evtol.server:main"
evtol-cli    = "hangar.evtol.cli:main"

[project.entry-points."hangar.study_runners"]
evtol = "hangar.evtol.study_runner"

[tool.uv.sources]
hangar-sdk = { workspace = true }
evtolpy = { path = "../../upstream/evtolpy", editable = true }

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["slow: ...", "golden_physics: ...", "parity: parity tests vs direct evtolpy API"]
```

**Execution model** (`builders.py` / `results.py`): tools accumulate a
config dict in session state (defaults deep-merged with user overrides);
analyses serialize it to a temp JSON file (the `Aircraft` constructor takes
a path), construct `Aircraft` inside `asyncio.to_thread(_suppress_output, ...)`,
then `results.py` harvests attributes into the envelope payload. The
constructed `Aircraft` is cached on the session keyed by a config hash so
repeated result queries don't re-converge MTOW; any config-mutating tool
invalidates the cache.

## Phase 2 — tool surface (MCP server + CLI share one registry)

Session/provenance tools come from the SDK glue, identical to ocp/pyc:
`start_session`, `configure_session`, `set_requirements`, `log_decision`,
`record_conclusion`, `export_session_graph`, `reset`, `pin_run`/`unpin_run`,
`get_run`, `get_detailed_results`, `list_artifacts`/`get_artifact`/
`get_artifact_summary`/`delete_artifact`, `get_last_logs`,
`link_cross_tool_result`, `visualize`.

Domain tools (one per upstream config section keeps the workflow shape
identical to ocp's define/configure/run pattern):

| Tool | Purpose |
|------|---------|
| `list_vehicle_templates` | enumerate built-in templates |
| `load_vehicle_template` | seed session config from a template |
| `define_vehicle` | aircraft-section params (geometry, masses, aero coefficients) |
| `set_propulsion` | rotor counts/diameters, tip Mach, efficiencies |
| `set_power` | battery specific energy, pack params, efficiencies |
| `configure_mission` | segment speeds/durations/profiles (defaults if skipped) |
| `set_environment` | density/gravity/viscosity overrides (optional) |
| `run_sizing` | converge MTOW; returns mass breakdown + convergence diagnostics |
| `run_mission_analysis` | full run; returns per-segment **energy**, **power**, and **weight** tables (the three upstream lanes) + totals + geometry/aero summary |
| `run_parameter_sweep` | 1-D/2-D sweeps over any config key (e.g. battery Wh/kg vs range) |
| `visualize` | plot types `segment-energy`, `segment-power`, `segment-weight`, `mass-breakdown`, `sweep` |

Templates in `config/defaults.py`: start with `test_all` (upstream
`sample-inputs/test-all.json`, the parity baseline) plus one template per
supported architecture as defaults allow (multirotor, lift+cruise,
tilt-rotor, vectored thrust) — exact set depends on what upstream configs
exist; only ship templates we can validate.

Validation (`ValidationFinding`s on every analysis): MTOW iteration
converged (and not at the divergence safeguard), battery mass fraction in
plausible range, disk loading sanity, stall vs cruise speed ordering,
non-negative segment energies, energy totals consistent with segment sum.
Input validators reject unknown config keys (evtolpy silently ignores
unrecognized JSON keys — same class of failure mode as OAS DV names, so
validate against the known schema up front).

`server.py`: FastMCP with `instructions` block documenting the required
workflow order (`start_session -> load_vehicle_template/define_vehicle ->
set_propulsion/set_power -> configure_mission -> run_sizing /
run_mission_analysis -> log_decision -> export_session_graph`), tools
registered through `capture_tool`, resources `evtol://reference`,
`evtol://workflows`, `evtol://artifacts/{run_id}`, prompts for guided
workflows, `main()` via `run_server_main(mcp, tool="evtol",
env_prefix="EVTOL", default_port=8004)`.

`cli.py`: `build_evtol_registry()` + `main()` via
`hangar.sdk.cli.runner.set_registry_builder` /
`set_setup_tools(["load_vehicle_template", "define_vehicle",
"set_propulsion", "set_power", "configure_mission", "set_environment"])`,
giving interactive / one-shot / script modes for free.

## Phase 3 — evaluation: three-lane suite from upstream core examples

`packages/evtol/examples/mission_segments/` follows the ocp/pyc lane
pattern, with the upstream **mission-segment-energy / -power / -weight**
analyses as the subject:

```
examples/mission_segments/
├── README.md
├── shared.py            # config (from upstream test-all.json), the 18
│                        # segment names, tolerances
├── cfg/test-all.json    # vendored copy of the pinned upstream config
├── lane_a/              # direct evtolpy API (ground truth)
│   ├── segment_energy.py    # replicates log_mission_segment_energy.py
│   ├── segment_power.py     # replicates log_mission_segment_power.py
│   └── segment_weight.py    # replicates log_mission_segment_weight.py
├── lane_b/              # hangar-evtol MCP tools via JSON scripts
│   ├── mission_analysis.json   # define/set/configure + run_mission_analysis
│   └── run_all.py
└── tests/
    ├── conftest.py      # artifact/provenance/session isolation fixtures
    ├── test_parity.py   # lane A vs lane B, per segment, all three tables
    └── test_cli_script.py  # evtol-cli script mode runs lane_b JSON end-to-end
```

- Lane A constructs `Aircraft(cfg)` directly and harvests the exact
  attributes the upstream `log_*.py` scripts write to CSV (18 segments x
  {energy kW·hr, power kW, weight kg}).
- Lane B drives the same config through the tool registry (in-process for
  `test_parity.py`; through the `evtol-cli` subprocess in
  `test_cli_script.py`, which is the CLI evaluation).
- Tolerances are tight (`rtol=1e-9`-ish): both lanes run the same pure-
  Python algebra, so any drift indicates a wrapper bug (config translation,
  unit mangling, stale cache).
- A `golden_physics` test pins a handful of headline numbers (converged
  MTOW, total mission energy) from the pinned ref to catch upstream-pin
  bumps that silently change physics.
- Tests marked `@pytest.mark.slow` + `@pytest.mark.parity`; suite runs
  per-directory like the other example suites.

ABU analysis (`evaluate_abu_detach_candidates` etc.) is explicitly **out of
scope for v1** — it's the specialized fourth lane; add as a follow-up tool
(`run_abu_analysis`) once the three core lanes are at parity.

## Phase 4 — monorepo wiring

- Root `pyproject.toml`: `packages/*` workspace glob already picks the
  package up; add `hangar-evtol` to root dependencies + workspace source,
  and `packages/evtol/tests` to `testpaths`.
- `docker/docker-compose.yml`: `evtol` service, host port **8004** (next
  free after oas=8000, ocp=8001, pyc=8002, omd=8003), in-container 8000,
  `EVTOL_TRANSPORT/HOST/PORT` env, `./hangar_data/evtol:/data` volume.
- CI: nothing new beyond the pins file — `setup-upstream.sh --required`
  picks up the new entry.

## Phase 5 — docs, skills, guardrails

- `packages/evtol/CLAUDE.md`: constraints doc, ~30 lines, covering:
  - `Aircraft` computes everything at construction — no incremental
    recompute; config changes require a fresh build (the session cache
    handles this; never mutate a built Aircraft).
  - evtolpy silently ignores unknown JSON keys — always validate config
    keys against the schema before building.
  - Units conventions baked into attribute names (`_kg`, `_kw`, `_kw_hr`,
    `_m_p_s`, `_kts`) — never convert implicitly.
  - MTOW iteration can hit the divergence safeguard — surface it as a
    failed validation finding, never as silent success.
  - ABU analysis out of scope v1.
  - Ports: evtol=8004. Testing command.
- `packages/evtol/skills/evtol-cli-guide/`: SKILL.md + commands.md +
  modes.md + provenance.md + evals/evals.json + example workflows, same
  structure as `pyc-cli-guide`; synced to `.claude/skills/` per the skills
  convention.
- Root `.claude/CLAUDE.md`: add `hangar.evtol` to the namespace list,
  `packages/evtol/` to the source layout, run/test commands.

## Test inventory

- `packages/evtol/tests/`: `test_tools_vehicle.py`, `test_tools_mission.py`,
  `test_tools_analysis.py`, `test_tools_session.py`, `test_validators.py`,
  `test_viz.py`, `test_evtol_study_runner.py`, `test_golden.py` — fast,
  using the `test_all` template; fixtures copied from the pyc conftest
  pattern (artifact/provenance isolation, session reset).
- `packages/evtol/examples/mission_segments/tests/`: parity + CLI suite
  (Phase 3), run per-directory.

## Sequencing

| Phase | Deliverable | Gate |
|------|-------------|------|
| 0 | upstream pin + packaging patch + smoke import | `uv sync` green, `import evtol` works |
| 1 | skeleton + builders/results + `define_vehicle`/`run_mission_analysis`/`run_sizing` + CLI wired | one-shot CLI run of test-all config returns enveloped results |
| 2 | full tool surface, validation, viz, server resources/prompts | unit tests green; server starts; `evtol-cli list-tools` complete |
| 3 | three-lane example suite | parity + golden + CLI-script tests green |
| 4 | docker + root wiring | `docker compose up evtol` serves on 8004; root `uv run pytest` includes evtol |
| 5 | CLAUDE.md + skill + docs | skill synced; docs updated |

## Open questions

1. Which vehicle templates beyond `test_all` to ship in v1 (depends on
   which architecture configs upstream actually provides and validates).
2. Whether to include `run_abu_analysis` in v1 or defer (plan: defer).
3. Whether upstream will accept the packaging PR (determines how long the
   managed patch lives).
