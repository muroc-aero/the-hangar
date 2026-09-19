# hangar-avy -- NASA Aviary MCP Server

This package wraps Aviary (>=1.0) as an MCP tool server for coupled
aircraft sizing + mission trajectory optimization (legacy FLOPS/GASP
methods on OpenMDAO/dymos).

## Runtime

`aviary` is an ordinary dependency of this package, installed into the
single workspace venv by `bash scripts/dev-setup.sh` (editable
`upstream/Aviary` at AVY_REF; numpy 2 / OpenMDAO >=3.43 / dymos). There is
no separate Aviary venv: OpenConcept runs in the same venv via the managed
`scripts/openconcept-numpy2.patch` applied by `scripts/setup-upstream.sh`.

- Server / CLI: `uv run avy-server`, `uv run avy-cli`
- Tests that touch aviary `importorskip("aviary")` so an install without it
  skips them; in the workspace venv they run for real.
- `hangar.avy` still imports aviary lazily so other tools' Docker images can
  import it without aviary installed; analysis tools then raise a clear
  install-instruction error.

## Key constraints

- EVERY Aviary run is an optimizer run (dymos collocation) -- there is no
  evaluate-only path. Hence the tool is `run_sizing`, not
  `run_mission_analysis`. ~20 s for the default 3-phase mission.
- `run_off_design` (max_range/min_fuel) and `run_payload_range` need a live
  sized problem. The last converged sizing per aircraft is kept live in
  the session (`AvySession.sized`, keyed by `sizing_fingerprint` = deck +
  overrides + mission + subsystems + optimizer/max_iter) and reused when
  it matches (`results.design_point.{sizing_reused, sizing_run_id}`);
  otherwise the sizing is re-run internally (~2x / ~3x wall-clock).
  Upstream's `run_payload_range` widens the sizing problem's cruise
  bounds in place, so that call consumes the cached sizing. `reset` and
  `load_aircraft_template` drop it.
- `run_sizing(subsystem_mode="precompute")` memoizes the oas_wing_mass
  sub-opt in `AvySession.sub_opt_cache` (key = resolved config + fuel
  load + deck planform when `planform: "deck"`), so repeat sizings at
  unchanged subsystem inputs skip the ~40 s sub-opt
  (`results.subsystems.sub_opt_cached`). `subsystem_feedback=
  "mission_fuel"` (precompute only) iterates the sub-opt on the sized
  mission fuel instead of the deck capacity.
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
  estimate on Aircraft.Wing.MASS. Needs openaerostruct + ambiance
  (declared dependencies of hangar-avy). `run_sizing` couples it
  `coupled` (inside the Aviary problem) or `precompute` (sub-opt once ->
  deck override -> plain sizing) -- exactly equivalent here (feed-forward
  topology, measured bit-identical; docs/aviary-oas-integration-plan.md).
  Wing planform: upstream's hard-coded single-aisle mesh by default,
  `planform: "deck"` derives a simple trapezoid from the deck, or an
  explicit planform dict. The upstream import path is an example
  namespace -- packages/avy/tests/test_avy_oas_contract.py pins it;
  re-run after any AVY_REF/OAS_REF bump.
- Session state is `hangar.avy.state.AvySession` (typed `aircraft`
  registry); the artifact store is the shared SDK singleton.

## Ports

oas=8000, ocp=8001, pyc=8002, omd=8003, evt=8004, avy=8005 (native
defaults; docker-compose maps the same host ports onto in-container 8000).

## Testing

```bash
# Fast unit tests (skips the slow sizing runs)
uv run pytest packages/avy/tests/ -m "not slow"

# Full suite incl. sizing runs + golden anchors
uv run pytest packages/avy/tests/ -v

# OAS-in-Aviary drift contract tests (after AVY_REF/OAS_REF bumps)
uv run pytest packages/avy/tests/test_avy_oas_contract.py -v

# Lane A/B parity examples (run each directory separately)
uv run pytest packages/avy/examples/single_aisle_sizing/tests/ -v --rootdir=.
uv run pytest packages/avy/examples/large_single_aisle_sizing/tests/ -v --rootdir=.
uv run pytest packages/avy/examples/bwb_sizing/tests/ -v --rootdir=.
uv run pytest packages/avy/examples/single_aisle_oas_wing/tests/ -v --rootdir=.
```
