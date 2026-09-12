# hangar-avy -- NASA Aviary MCP Server

This package wraps Aviary (>=1.0) as an MCP tool server for coupled
aircraft sizing + mission trajectory optimization (legacy FLOPS/GASP
methods on OpenMDAO/dymos).

## The isolated venv (read this first)

Aviary >=1.0.1 requires openmdao>=3.43 (numpy>=2); the openconcept pin caps
numpy<2. So `aviary` is NOT a declared dependency and does NOT live in the
main workspace venv. The Aviary runtime lives in `.venv-avy` at the repo
root (`bash scripts/setup-avy-venv.sh`: hangar-sdk + hangar-avy + editable
`upstream/Aviary` at AVY_REF), and in this package's own Docker image.

- Server / CLI: `.venv-avy/bin/avy-server`, `.venv-avy/bin/avy-cli`
- Tests that touch aviary `importorskip("aviary")` -- in the main venv they
  skip; run them for real with `.venv-avy/bin/python -m pytest ...`
- `hangar.avy` imports aviary lazily; in the main venv every module still
  imports and analysis tools raise a clear install-instruction error.

## Key constraints

- EVERY Aviary run is an optimizer run (dymos collocation) -- there is no
  evaluate-only path. Hence the tool is `run_sizing`, not
  `run_mission_analysis`. ~20 s for the default 3-phase mission.
- `run_off_design` (max_range/min_fuel) and `run_payload_range` need a live
  sized problem; none is cached (pyc precedent), so they re-run the sizing
  internally -- ~2x / ~3x run_sizing wall-clock.
- Optimizer non-convergence does NOT raise; it returns the last iterate
  with `prob.result.success == False`. The `optimizer.success` validation
  finding is the load-bearing check.
- Default optimizer SLSQP (pip-installable). IPOPT/SNOPT need pyoptsparse
  and are rejected with instructions when absent.
- Aviary 1.0 renamed nearly everything from 0.9.x (`HEIGHT_ENERGY` ->
  `ENERGY_STATE`, `mission:summary:*` removed, `aviary/examples/` deleted).
  Target >=1.0 names exclusively; older docs/blogs are stale.
- Runs execute in a per-run scratch cwd (reports land cwd-relative) behind
  a process lock, with `_clear_problem_names()` before each run --
  problem names collide across runs in one process otherwise.
- Deck overrides are validated against aviary's variable metadata
  (`aircraft:wing:span` hierarchy) with close-match suggestions.
- Only energy_state missions run today; GASP 2DOF decks are listed by
  list_aircraft_templates but rejected by configure_mission/run_sizing.
- External subsystems (`hangar.avy.subsystems` registry, tools
  `list_external_subsystems`/`add_external_subsystem`): `oas_wing_mass`
  wraps upstream Aviary's own OpenAeroStruct integration -- a nested
  wingbox sub-optimization (~40 s) whose wing mass overrides the FLOPS
  estimate on Aircraft.Wing.MASS. Needs openaerostruct + ambiance in
  .venv-avy (setup-avy-venv.sh installs them). `run_sizing` couples it
  `coupled` (inside the Aviary problem) or `precompute` (sub-opt once ->
  deck override -> plain sizing) -- exactly equivalent here (feed-forward
  topology, measured bit-identical; docs/aviary-oas-integration-plan.md).
  Wing planform: upstream's hard-coded single-aisle mesh by default,
  `planform: "deck"` derives a simple trapezoid from the deck, or an
  explicit planform dict. The upstream import path is an example
  namespace -- packages/avy/tests/test_avy_oas_contract.py pins it;
  re-run in .venv-avy after any AVY_REF/OAS_REF bump.
- Session state is `hangar.avy.state.AvySession` (typed `aircraft`
  registry); the artifact store is the shared SDK singleton.

## Ports

oas=8000, ocp=8001, pyc=8002, omd=8003, evt=8004, avy=8005 (native
defaults; docker-compose maps the same host ports onto in-container 8000).

## Testing

```bash
# Aviary-free unit tests (main venv; aviary-dependent tests skip)
uv run pytest packages/avy/tests/ -m "not slow"

# Full suite incl. sizing runs + golden anchors (isolated venv)
.venv-avy/bin/python -m pytest packages/avy/tests/ -v

# OAS-in-Aviary drift contract tests (after AVY_REF/OAS_REF bumps)
.venv-avy/bin/python -m pytest packages/avy/tests/test_avy_oas_contract.py -v

# Lane A/B parity examples (run each directory separately)
.venv-avy/bin/python -m pytest packages/avy/examples/single_aisle_sizing/tests/ -v --rootdir=.
.venv-avy/bin/python -m pytest packages/avy/examples/large_single_aisle_sizing/tests/ -v --rootdir=.
.venv-avy/bin/python -m pytest packages/avy/examples/bwb_sizing/tests/ -v --rootdir=.
.venv-avy/bin/python -m pytest packages/avy/examples/single_aisle_oas_wing/tests/ -v --rootdir=.
```
