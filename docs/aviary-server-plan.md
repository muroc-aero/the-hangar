# Plan: hangar-avy — NASA Aviary MCP server + CLI

Add `packages/avy/` wrapping [Aviary](https://github.com/OpenMDAO/Aviary)
(NASA's OpenMDAO/dymos aircraft design and mission-optimization tool,
incorporating the legacy FLOPS and GASP methods), patterned on the existing
`packages/ocp/`, `packages/pyc/`, and `packages/evt/` servers.

Status: **Phases 0-3 implemented, plus the Phase-2 off-design tools, the
avy-cli-guide skill, DEPLOY.md, and two parity example suites** (five
Lane-A/B cases total; `packages/avy/`, PR #99). Remaining: the omd factory
and omd-level Lane B/C (blocked, see Phase 4) and live deployment. Phase 0
passed decisively: SLSQP converges the advanced-single-aisle sizing on the
default energy_state mission in ~20 s, so the parity suite is CI-viable.
One planning assumption did not survive contact -- see the **numpy-2
isolation** note under "Impact on the-hangar": Aviary cannot share the
workspace venv, so it runs from an isolated `.venv-avy`
(`scripts/setup-avy-venv.sh`) and its own Docker image.

## Why this tool

Aviary fills the gap between OpenConcept's fast integrator missions and a
real sizing loop:

- **Coupled aircraft-sizing + trajectory optimization** with analytic
  gradients: gross mass, fuel, and the flight path are optimized together
  (dymos collocation), vs OCP's fixed-profile mission integration.
- **FLOPS and GASP legacy methods** for mass, aero, and mission — the
  workhorse empirical methods of NASA conceptual design, selectable
  independently (`settings:mass_method`, `settings:aerodynamics_method`,
  `settings:equations_of_motion`).
- **Off-design and payload–range analysis** from a saved sizing
  (`run_off_design_mission`, `run_payload_range`,
  `ProblemType.OFF_DESIGN_MIN_FUEL / OFF_DESIGN_MAX_RANGE`).
- **A first-class external-subsystem interface** (`SubsystemBuilder`) that
  is the *inverse* of our usual composition direction: Aviary consumes
  other tools. Upstream already ships an OpenAeroStruct wingbox-mass
  subsystem example (`aviary/models/external_subsystems/open_aero_struct/`),
  so an OAS-in-Aviary coupling — and later a pyCycle engine-deck path — is
  nearly free and is strong paper-lane material.
- **Benchmark validation decks** with published expected values (the
  single-aisle `aircraft_for_bench_*` family), giving us golden physics
  anchors for free.

Positioning vs hangar-ocp: OCP stays the fast conceptual-mission tool
(seconds per run, integrator-based, hybrid-electric architectures); Aviary
is the sizing-fidelity tool (minutes per run, collocation optimization,
FLOPS/GASP mass buildups). They answer different questions and an
OCP-vs-Aviary cross-check on a common mission is itself a good study.

## Upstream summary

Key facts that shape the wrapper (verified against Aviary main @ 1.0.2-dev
and the v1.0.1 release, 2026-07-02):

- **Distribution**: pure Python on PyPI as `aviary` (the old `om-aviary`
  name is a deprecated placeholder — do not use it). Apache-2.0.
  `requires-python >= 3.10`; needs `openmdao >= 3.43`, `dymos >= 1.14`.
  Our OpenMDAO pin (3.43.0+31) already satisfies the floor.
- **Aviary 1.0 (2026-04-29) was a breaking reorganization.** Target ≥1.0
  names exclusively: `HEIGHT_ENERGY` → `ENERGY_STATE` (`'energy_state'`),
  `mission:summary:*` / `mission:design:gross_mass` removed (results are
  now flat `mission:*` + `aircraft:design:gross_mass`),
  `methods_for_level2` → `aviary/core/aviary_problem.py`,
  `SubsystemBuilderBase` → `SubsystemBuilder`, `aviary/examples/` removed
  (shipped models now live in `aviary/models/aircraft/`), phase_info
  format revamped. Most blog posts and older docs describe 0.9.x.
- **Three API levels.** Level 1: `run_aviary(aircraft_data, phase_info,
  optimizer=..., ...)` / `aviary run_mission <deck.csv>` CLI. Level 2:
  the `AviaryProblem` method sequence (`load_inputs → ... → add_driver →
  ... → run_aviary_problem`). Level 3: raw OpenMDAO/dymos with Aviary
  components. The MCP tools wrap **Level 2** (control over driver,
  reports, and result extraction); Lane A references use **Level 1**
  (fewest moving parts).
- **Inputs**: an aircraft deck CSV of `name,value,units` rows using the
  `aircraft:wing:span`-style variable hierarchy
  (`aviary/variable_info/variables.py` — `Aircraft.*`, `Mission.*`,
  `Settings.*`), plus a `phase_info` Python dict (per-phase
  `user_options`: `num_segments`, `order`, `mach_*`, `altitude_*`,
  `throttle_enforcement`, ...). Phase options are OpenMDAO options
  dictionaries, so unknown keys error — good for us. Defaults live in
  `aviary/models/missions/{energy_state_default,two_dof_default}.py`.
- **Every run is a driver run.** Even "analysis" solves the collocation
  problem with an optimizer; there is no cheap evaluate-only path like
  OCP's. The CLI/`add_driver` default optimizer is **IPOPT via
  pyoptsparse, which is not pip-installable** — the wrapper defaults to
  scipy **SLSQP** (fine for the simple docs mission and the parity case)
  and treats IPOPT/SNOPT as opt-in where pyoptsparse is present
  (upstream benchmark tests skip without it, via `@require_pyoptsparse`).
- **Outputs**: `prob.get_val(...)` on `mission:gross_mass`,
  `mission:total_fuel_mass`, `mission:fuel_mass`, `mission:range`,
  `mission:final_time`, `aircraft:design:gross_mass`, ...; success flag
  `prob.result.success`. OpenMDAO reports land in a cwd-relative
  `reports/<problem_name>/` (n2, opt_report, traj_results, Aviary's
  `mission_summary.md` + `mission_timeseries_data.csv`);
  `prob.save_results()` writes `sizing_results.json`, which seeds
  off-design and payload–range runs.
- **Long-lived-process hazards**: problem names collide across repeated
  runs in one process (`_clear_problem_names()` between runs), and the
  reports dir is cwd-relative — the server must run each case in a
  per-run scratch dir under `HANGAR_DATA_DIR`.
- **Runtime**: benchmark cases run minutes each (full upstream suite
  ~30 min); parity tests will be `@pytest.mark.slow`.

## Impact on the-hangar (what actually changes)

Nothing in the SDK, envelope, provenance, or session architecture needs to
change. The deltas:

1. **`upstream-pins.env` / dev-setup**: add `AVY_REF` (full SHA at the
   v1.0.1 tag) and clone into `upstream/Aviary` via
   `scripts/setup-upstream.sh`. Pure `git clone` — no patch, no compiled
   step.
2. **numpy-2 isolation (found in implementation, supersedes the original
   "editable install like OpenConcept" plan)**: Aviary >=1.0.1 requires
   `openmdao>=3.43`, which requires `numpy>=2`, while the openconcept pin
   caps `numpy<2` (still capped on upstream main as of 2026-07). The two
   cannot share one venv/lock, so `hangar-avy` does **not** declare
   `aviary` as a dependency (lazy import + install-instruction error,
   exactly how the vsp plan handles openvsp). The Aviary runtime lives in
   `.venv-avy` at the repo root (`scripts/setup-avy-venv.sh`: hangar-sdk +
   hangar-avy + editable `upstream/Aviary`), and in the package's own
   Docker image (which installs only sdk + avy + aviary, so no conflict
   in containers). Aviary-dependent tests `importorskip("aviary")` and
   run for real via `.venv-avy/bin/python -m pytest`. Revisit if/when
   openconcept relaxes its numpy cap — then Aviary can fold into the
   main workspace as originally planned.
3. **pyoptsparse is optional everywhere**: pyproject depends only on
   scipy-backed SLSQP; the `create_*`/`run_*` tools accept
   `optimizer="SLSQP"|"IPOPT"|"SNOPT"` and return a typed
   `USER_INPUT_ERROR` naming the install path when pyoptsparse is absent.
4. **Run-scratch-dir management** (minor): per-run cwd under
   `HANGAR_DATA_DIR` so `reports/<name>/` and `sizing_results.json` land
   in the artifact area; register the useful report files alongside plots
   the way OAS handles run artifacts.

## Phase 0 — API spike (go/no-go gate)

1. Pin Aviary ≥1.0.1, install into the workspace venv next to the
   existing pins (watch for OpenMDAO/dymos resolution conflicts).
2. Script end-to-end without hangar code: Level 1 `run_aviary` on
   `models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv`
   with the `energy_state_default` phase_info under SLSQP; confirm
   convergence, runtime, and extraction of the headline metrics.
3. Repeat via Level 2 with an explicit method sequence and a custom
   phase_info dict; verify two runs in one process work with
   `_clear_problem_names()` and a managed cwd.
4. Exit criteria: SLSQP converges the docs-level sizing case in
   acceptable wall-clock; benchmark deck `aircraft_for_bench_GwGm.csv`
   reproduces the published anchors (gross mass 171,414 lbm, total fuel
   40,452 lbm, range 3675 NM) under whichever optimizer converges it —
   if that requires IPOPT, the golden-anchor test is conditional on
   pyoptsparse and the parity lanes run a SLSQP-friendly case instead.

## Phase 1 — packaging

- `AVY_REF` in `scripts/upstream-pins.env`; clone + editable install in
  `scripts/setup-upstream.sh` / `dev-setup.sh`.
- `packages/avy/pyproject.toml`: `name = "hangar-avy"`, depends on
  `hangar-sdk[all]`, `aviary>=1.0.1,<2`, `openmdao`, `dymos`; workspace
  member; console scripts `avy-cli` / `avy-server`.
- `packages/avy/Dockerfile` mirroring ocp/pyc (pip upstream at the pin).

## Phase 2 — package skeleton + core tools

`packages/avy/` mirroring ocp/pyc layout (namespace rule: `__init__.py`
only at `src/hangar/avy/`, never `src/hangar/`): `server.py` (plumbing
from `hangar.sdk.server_main.run_server_main`, **default port 8005** —
next free after 8004=evt), `state.py` (`AvySession` holding deck values,
phase_info, saved `sizing_results.json` handles, per-run scratch dirs),
`config/defaults.py`, `tools/`, `cli.py`, tests. Provenance four-pack
from `build_provenance_tools`.

Tool surface (~15 tools, deliberately NOT a 1:1 wrap of the variable
hierarchy):

| Group | Tools |
|---|---|
| Definition | `list_aircraft_templates` (shipped `aviary/models/aircraft/*` decks + the `aircraft_for_bench_*` validation decks), `load_aircraft_template`, `define_aircraft` (strict-key overrides onto the deck, `aircraft:wing:span`-style names validated against Aviary's `_MetaData` with typo suggestions, evt-style), `configure_mission` (declarative phase_info: EOM choice, phase list, per-phase user_options; validated before it ever reaches dymos) |
| Analysis | `run_sizing` (ProblemType.SIZING; Level 2 sequence; `optimizer=`, `max_iter=`), `run_off_design` (min-fuel / max-range from a pinned sizing run's `sizing_results.json`), `run_payload_range` |
| Cross-tool | `export_mission_summary` (timeseries CSV + headline dict for OCP/omd cross-checks), later `add_external_subsystem` (Phase 4) |
| SDK standard | provenance four-pack, `get_run`, `get_detailed_results`, `get_artifact*`, `pin_run`, `visualize`, `get_last_logs`, `configure_session`, `reset` |

Naming note: `run_sizing` / `run_off_design` deliberately match the evt/pyc
vocabulary rather than Aviary's "run_mission", because in Aviary the
mission IS the sizing optimization; a separate `run_mission_analysis` name
would wrongly suggest an OCP-style cheap evaluation.

`ValidationFinding` squawks to encode from day one:

- Optimizer exit status ≠ success (`prob.result.success`) — the primary
  upstream failure mode; surface `opt_report` highlights in the finding.
- `max_iter` hit (default 50 is sometimes insufficient upstream).
- Throttle bounds active / `throttle_enforcement` violations.
- Phase-linkage defect heuristics (mach/altitude discontinuities between
  phases in the timeseries).
- Empirical-method domain: FLOPS/GASP correlations are transport-category
  calibrations — squawk when the deck is far outside (MTOW, pax count).
- pyoptsparse absent but IPOPT/SNOPT requested (typed error, not finding).

## Phase 3 — visualization + CLI guide

- `visualize`: mission profile (altitude/Mach/thrust/mass vs time or
  range, from `mission_timeseries_data.csv`), payload–range diagram,
  mass buildup bar (FLOPS/GASP groups) — matplotlib, oas-cli plot style.
  N2 via the standard `get_n2_html`-style route (report file already
  generated per run).
- `avy-cli` with the three SDK modes; `avy-cli-guide` skill in
  `packages/avy/skills/` (structure of `oas-cli-guide`), synced via
  `scripts/sync-skills.sh`.

## Phase 4 — parity lanes + omd factory + cross-tool

### The three-lane parity example (paper-lane material)

One problem, solved three ways, per `docs/parity-lanes-and-agent-eval.md`.
**Case: single-aisle transport sizing** — the canonical upstream benchmark
family. Primary CI case uses the FLOPS-mass + energy-state deck
(`advanced_single_aisle_FLOPS.csv` or `aircraft_for_bench_FwFm.csv`) with
the default 3-phase energy_state mission under SLSQP, because all three
lanes must run the same pip-installable optimizer in CI. The GwGm deck's
published values serve as golden anchors (conditional on the Phase 0
optimizer finding).

Two suites, matching the existing two-level pattern:

**Per-tool suite** — `packages/avy/examples/single_aisle_sizing/`:

```
single_aisle_sizing/
  shared.py                  # deck path, phase_info params, tolerances, GOLDEN anchors
  lane_a/sizing.py           # Level 1: av.run_aviary(deck, default phase_info,
                             #   optimizer="SLSQP") -> {"gross_mass_lbm",
                             #   "total_fuel_lbm", "range_nm", "final_time_s"}
  lane_b/sizing.json         # MCP tool-call script replayed in process via
                             #   hangar.sdk.cli.runner.run_tool:
                             #   start_session -> load_aircraft_template ->
                             #   configure_mission -> run_sizing
  tests/test_parity.py       # Lane A vs Lane B vs golden anchors (all @slow)
```

**omd cross-tool case** — `packages/omd/examples/avy_single_aisle/`:

```
avy_single_aisle/
  shared.py                  # same contract module pattern
  lane_a/sizing.py           # raw Aviary Level 1 (no hangar imports beyond shared)
  lane_b/sizing/             # modular omd plan YAML: component type avy/Sizing,
                             #   deck ref + phase_info config, driver=SLSQP
  lane_c/
    sizing.prompt.md         # closed prompt: names tools and steps
    sizing_open.prompt.md    # open prompt: goal + deck + mission only; withholds
                             #   component type, config keys, tool sequence
```

wired into `tests/test_parity.py` (A vs B), `tests/test_parity_lane_c.py`
(scripted tool surface: `plan_init → plan_add_component → ... → run_plan →
get_results`), and `agent_eval/eval_lane_c.py` (blind agent), plus a
`CASE_INFO` row in `paper/make_tables.py`.

Headline metrics and tolerance tiers (values from `shared.py`, consumed by
`pytest.approx` as elsewhere):

| Metric | Aviary variable | Tolerance | Rationale |
|---|---|---|---|
| gross mass | `mission:gross_mass` | `rel=1e-3` | optimizer-converged quantity |
| total fuel | `mission:total_fuel_mass` | `rel=1e-3` | optimizer-converged |
| range | `mission:range` | `rel=1e-6` | target echoed through constraint |
| final time | `mission:final_time` | `rel=1e-3` | trajectory-dependent |
| GOLDEN anchors | GwGm published values | `rel=1e-3` | pins Lane A vs upstream regression |

Parity here is optimizer-path-sensitive (every lane run is an
optimization), so the `rel=1e-3` tier applies to converged outputs — the
same slack tier the existing suites grant optimizer objectives — while
anything echoed from the inputs must match to `1e-6`. All lanes fix the
optimizer, `max_iter`, `num_segments`, and transcription order in
`shared.py` so they solve the *same* problem, not merely a similar one.

### omd factory + cross-tool

- omd `avy/Sizing` factory (`packages/omd/src/hangar/omd/factories/avy.py`)
  — **implemented as a subprocess black box**, dissolving the numpy-2
  blocker: the component's `compute` writes a JSON spec and executes
  `avy_worker.py` with the isolated `.venv-avy` interpreter (the same
  external-solver pattern the vsp plan uses for VSPAERO), so omd's main
  venv never imports aviary. Subprocess isolation also removes the
  cwd/problem-name hazards the in-process server locks around. As
  designed, the component is **self-driving** (plan `mode: analysis` runs
  the embedded dymos+SLSQP optimization; `converged` output mirrors the
  evt black box) with `target_range_nm` as the one sweepable input
  (FD partials, ~20 s per evaluation — sweeps/DOE, not gradient opt).
  omd-level parity cases `packages/omd/examples/avy_single_aisle/` and
  `avy_bwb/` (Lane A = the per-tool raw-Aviary reference scripts run in
  `.venv-avy`; Lane B = the plan pipeline; Lane C = scripted tool-surface
  test + closed/open agent prompts) are wired into the omd parity suites,
  **skip-gated on `.venv-avy` existing** — they run locally, not in CI,
  and are therefore not in the paper's 13-case table. An *in-process*
  factory (analytic derivatives through Aviary) still waits on the
  openconcept numpy cap. The per-tool parity coverage (all implemented):
  `packages/avy/examples/single_aisle_sizing/` (three cases -- default
  sizing, deck-override via define_aircraft, mission-override via
  configure_mission -- plus closed/open Lane C agent prompts targeting the
  avy server's own MCP tools),
  `packages/avy/examples/large_single_aisle_sizing/` (second airframe,
  737-class deck at 2500 nmi), and
  `packages/avy/examples/bwb_sizing/` (the upstream BWB benchmark brought
  into the lanes: fixed-profile adaptation of its M0.85/7750 nmi mission
  via the `bwb_fixed` mission template, cross-anchored to the published
  SNOPT benchmark masses at 2%).
  **Upstream benchmark coverage note:** the raw upstream benchmark
  missions (FwFm/GwFm/GwGm bench tests, model phase_infos with detailed
  takeoff and mach/altitude-optimized profiles) all require IPOPT/SNOPT --
  verified to not converge under SLSQP -- and the 2DOF (Gm) family needs
  mission wiring this server doesn't have. They are exposed as mission
  templates (`GwFm_bench`, `advanced_single_aisle`, `bwb_bench`) for
  pyoptsparse users, with parity examples to follow if a CI leg gains
  IPOPT.
- `add_external_subsystem` (stretch): register upstream's OAS wingbox
  mass builder inside an Aviary run — an Aviary+OAS lane case that tests
  the composition direction none of the current 13 cases cover
  (upstream tool consuming a hangar-wrapped tool's library). Now planned
  in detail (feasibility spike verified: OAS v2.12.0 installs and runs
  under numpy 2 in `.venv-avy`) — see
  `docs/aviary-oas-integration-plan.md`.
- OCP-vs-Aviary cross-check study (omd study YAML): same
  payload/range/cruise on `large_single_aisle_1` vs OCP `b738` — a
  documented methods-comparison demo, not a parity case (different
  physics, no tolerance claim).

## Phase 5 — deploy

Per the `new-tool` skill: docker-compose service (+ viewer read-only
mount), Caddyfile routes, `AVY_TRANSPORT`/`AVY_HOST`/`AVY_PORT` env vars,
OIDC via `hangar.sdk.auth`, `DEPLOY.md`, `.mcp.json` entry,
`HANGAR_VIEWER_DBS` update.

## Difficulty estimate

Roughly 1–1.5× ocp effort. Packaging is trivial (pure Python, PyPI) and
the server/CLI/provenance scaffold is mechanical given the SDK (~40%);
the genuinely design-sensitive pieces are the declarative
`configure_mission` phase_info surface (~25%), run-lifecycle management
in a long-lived server (problem names, cwd-relative reports, minutes-long
runs; ~15%), and the self-driving omd factory + parity case (~20%).
The main schedule risk is optimizer behavior: if SLSQP won't converge any
representative sizing case in CI-acceptable time, the parity lanes need a
reduced case (fewer segments, lower order) designed in Phase 0.

## References

- [Aviary GitHub](https://github.com/OpenMDAO/Aviary) (Apache-2.0;
  PyPI `aviary`, v1.0.1 2026-07-02)
- [Aviary docs](https://openmdao.github.io/Aviary/) (Jupyter Book; source
  of truth is `aviary/docs/` in-repo — the 1.0 reorg outdated much of the
  web-indexed material)
- UI levels: `aviary/docs/user_guide_unreviewed/UI_levels.md`;
  Level 1 entry `aviary/interface/run_aviary.py`; Level 2
  `aviary/core/aviary_problem.py`
- Benchmarks: `aviary/validation_cases/validation_data/test_models/
  aircraft_for_bench_{FwFm,FwGm,GwFm,GwGm}.csv`,
  `aviary/validation_cases/benchmark_tests/test_bench_*.py`
- External subsystems: `aviary/subsystems/subsystem_builder.py`
  (`SubsystemBuilder`), OAS example
  `aviary/models/external_subsystems/open_aero_struct/`
- Lane design: [`parity-lanes-and-agent-eval.md`](parity-lanes-and-agent-eval.md)
