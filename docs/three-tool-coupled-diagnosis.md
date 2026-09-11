# Diagnosing the three-tool coupled case (`ocp_three_tool`)

The B738 + OAS VLM drag + pyCycle HBTF example has been failing across
lanes A, B and C. This note records what the failures are, and — more
usefully — the staged decomposition that found them, so the next coupled
example does not need a 70-minute run to debug.

## Why the case was hard to debug

One `ocp_three_tool` run costs roughly 70 minutes, and almost all of it is
two training stages:

| Stage | Cost | Notes |
|-------|------|-------|
| pyCycle HBTF off-design deck | ~20 min | 125 points, one cold pyCycle solve each |
| OAS VLM drag-polar grid | minutes | 9 Mach x 6 alpha x 4 alt = 216 VLM runs |
| Coupled mission solve | ~5-8 s | the part anyone actually wants to look at |

Worse, the propulsion slot has `slot_scope = "per_phase"`, so the mission
builds it once for climb, once for cruise and once for descent — paying the
deck three times and fitting three independent surrogates from what should
be identical data. That is where the ~70 min comes from, and it is why the
"change something, run it, read the number" loop was unusable.

## The staged decomposition

Each stage is now separately testable, and only one of them is expensive.

| Tier | What it checks | Cost | Where |
|------|----------------|------|-------|
| 0 | Structure: can a solver reach every balance? | **~1 s** | `diagnostics/solver_coverage.py`, `tests/test_solver_coverage.py` |
| 1 | Deck admissibility: is each pyCycle point physical? | **ms** on a saved deck | `diagnostics/deck_quality.py`, `tests/test_deck_quality.py` |
| 2 | Surrogate: Kriging fit quality and query envelope | seconds | from a cached `.npz` |
| 3 | Coupled solve with a cached deck | ~10 s | `deck_path` / the new deck cache |
| 4 | Full lane A/B/C parity | ~70 min | existing `test_parity.py` (`-m slow`) |

Two changes make tiers 0-3 possible at all:

* **Stub the training stages.** Structural questions do not depend on deck
  contents. `tests/test_solver_coverage.py` swaps in an 8-point synthetic
  deck and a constant-CL/CD `VLMDataGen`, and audits the assembled model in
  1.35 s.
* **Cache the deck.** A deck is a pure function of
  `(archetype, design conditions, engine params, grid)`.
  `pyc/surrogate.py` now memoizes on that key, so the three phases share one
  deck. `deck_path` already let a plan point at a saved `.npz`; generating
  one once and reusing it turns tier 3 into a ten-second loop.

## Findings

### 1. NLBGS cannot solve this model, and reports success anyway

`lane_b/coupled_mission/plan.yaml` sets `solver_type: nlbgs`, and the
README explains it as avoiding an ill-conditioned Newton Jacobian.

`NonlinearBlockGS` only *calls* each subsystem's `_solve_nonlinear`. An
`ImplicitComponent` that defines no `solve_nonlinear` treats that call as a
no-op, and OpenConcept's mission groups carry no solvers of their own. So
all nine balances in the mission are never solved:

```
analysis.{climb,cruise,descent}.steadyflt              throttle
analysis.{climb,cruise,descent}.acmodel.drag.alpha_bal alpha for target CL
analysis.{climb,cruise,descent}.{phase}dt              phase duration
```

Observed on a real run: `climb.throttle == [0.5, 0.5, 0.5]` — the
`BalanceComp`'s initial value, untouched — alpha pinned at 1.0 deg in every
phase, cruise thrust 6.1 kN against 38.7 kN of drag, and a residual of
**3048** on `descent.descentdt.duration`. NLBGS declared convergence in
**3 iterations** with `atol = rtol = 1e-8` and printed no warning.

The reported fuel burn is therefore not a solution: it is the initial
guesses propagated through the explicit components. Anything that perturbs
the surrogate moves it, which is what made the case look intermittent.

Upstream OpenConcept's own `B738_VLM_drag.py` uses
`NewtonSolver(solve_subsystems=True)` with `err_on_non_converge = True`.

### 2. The deck keeps points that are not physics

`_run_hbtf_deck` marks a point converged when `thrust > 0 and fuel > 0`. It
never consults the solver, and never checks that the off-design balance held
the T4 it was commanded. On a real 125-point deck, **122 points passed that
test and only 109 are physically admissible**:

| Index | Condition | Reported |
|-------|-----------|----------|
| 115 | 40,000 ft, M 0.70, throttle 0.30 | Fn = **6.56e10 lbf**, T4 = 270 degR (below ambient) |
| 110 | 40,000 ft, M 0.55, throttle 0.30 | Fn = 2.97e7 lbf, T4 = 4500 degR (commanded 2117) |
| 109 | 40,000 ft, M 0.40, throttle 1.00 | Fn = 1.51e7 lbf |
| 100-104 | 40,000 ft, M 0.20, all throttles | identical Fn = 8584 lbf, T4 frozen at 2394 degR |

`KrigingSurrogate` normalizes by the training standard deviation, so one
10-order-of-magnitude outlier flattens every real point into numerical noise.
Measured at the cruise design point (35,000 ft, M 0.80, full throttle):

| Deck | Predicted thrust | Truth |
|------|------------------|-------|
| as generated | **2,286,163 kN** | ~26 kN |
| physics-filtered | 24.2 kN | 26.2 kN design |

Dropping the 13 inadmissible points moves the reported fuel burn from
2885 kg to 2282 kg — a 21% shift, with the run reporting success both times.

The generator's fixed cold-start guesses (`DEFAULT_HBTF_OD_GUESSES`) are
used for all 125 points, from sea level to 40,000 ft, with no continuation
from the design point. Every bad point is at the 40,000 ft edge, furthest
from the 35,000 ft design condition.

### 3. The propulsion slot never accounts for engine count

The CFM56 default path wraps `propmodel` in a `doubler` ExecComp
(`thrust = 2*thrust_in`) for a twin. The propulsion-**slot** path has no
equivalent, in the omd factory or in Lane A, so `twin_turbofan` with
`pyc/surrogate` flies a B738 on one engine's thrust.

With a clean deck and Newton, cruise needs 43.9 kN and one engine gives
~24 kN, so the throttle balance pegs at its upper bound 1.05 in all three
cruise nodes and Newton cannot converge. Adding the missing x2 puts cruise
throttle back at an interior 0.86-0.91 with thrust exactly equal to drag,
and fuel burn at a plausible 10,015 kg.

This is very likely *why* the example was switched to NLBGS: Newton was
correctly reporting that the mission has no solution, and NLBGS hid it by
not solving anything.

### 4. The deck's throttle floor does not cover descent

The deck trains on `throttle in [0.30, 1.00]`; OpenConcept's throttle
balance is bounded `[0.01, 1.05]`. Descent needs idle, so the balance is
driven into Kriging extrapolation, where the fit is non-monotonic and can go
negative. Even with a clean deck and the engine count fixed, descent thrust
still reaches -3.1 kN and Newton does not fully converge.

## What is in this change

Diagnostics and tests only — no lane physics or reference values were
changed, since those feed the published parity tables.

* `hangar.omd.diagnostics.solver_coverage` — find implicit components no
  solver in their ancestry can solve. Needs only `final_setup()`.
* `hangar.omd.diagnostics.deck_quality` — admissibility checks for a
  pyCycle deck: T4 held, thrust in range, monotone in throttle, per-line
  coverage.
* `pyc/surrogate.py` — deck memoization keyed on the generating inputs,
  plus `deck_cache_key` / `clear_deck_cache`.
* `packages/omd/tests/test_solver_coverage.py`,
  `packages/omd/tests/test_deck_quality.py` — 13 tests, 1.4 s total.

## Recommended fixes, in dependency order

1. **Deck admissibility** — have `_run_hbtf_deck` reject points via
   `physically_converged` instead of `thrust > 0`, and add continuation from
   the design point (or per-condition `guess_nonlinear`) so the 40,000 ft
   edge converges rather than being dropped.
2. **Engine count** — give the propulsion slot an engine-count multiplier,
   matching the CFM56 `doubler`; mirror it in Lane A.
3. **Deck envelope** — extend the throttle grid down toward idle so descent
   is interpolated, not extrapolated.
4. **Solver** — with 1-3 done, move `ocp_three_tool` back to
   `NewtonSolver(solve_subsystems=True)` and set `err_on_non_converge=True`
   in the OCP builder so a non-converged mission fails loudly. Then correct
   `skills/omd-cli-guide/ocp-specifics.md`, which currently tells agents to
   pick `nlbgs` for dual-surrogate slots — that advice reaches Lane C agents
   and reproduces this failure.

Until 1-4 land, `ocp_three_tool`'s Lane A numbers are not a physical
reference and should not anchor an eval.
