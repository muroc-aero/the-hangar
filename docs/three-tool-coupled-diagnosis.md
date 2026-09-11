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

## The fix, and what it produced

All four defects are fixed. Lane A now converges in **6 Newton iterations**
(worst residual 2.3e-10) where NLBGS previously "converged" in 3 on a model
it never solved.

| Lane | What it is | fuel_burn_kg | OEW_kg | MTOW_kg | Diff vs A |
|------|-----------|--------------|--------|---------|-----------|
| A | direct OpenMDAO, no omd | 10645.149781505615 | 41871.0 | 79002.0 | -- |
| B | omd plan pipeline (`run_plan`) | 10645.149781505615 | 41871.0 | 79002.0 | +0.0000% |
| C | MCP tool surface (scripted) | 10645.149781505615 | 41871.0 | 79002.0 | +0.0000% |

All three agree to the last digit, against a parity tolerance of 1e-3. Both
parity tests pass:

```
packages/omd/examples/tests/test_parity.py::TestOCPThreeToolParity          PASSED
packages/omd/examples/tests/test_parity_lane_c.py::TestOCPThreeToolLaneC    PASSED
2 passed in 3588.34s (0:59:48)
```

That hour is one deck generation, not three: the run reported
`HBTF deck: 144/180 points physically admissible (36 rejected)` once and the
cache served it to both tests and to all three flight phases of each.

Physical plausibility of the converged state, which the old answer had none of:

* Cruise thrust equals drag to 7e-8 kN at every node (43.76 / 42.32 / 41.01 kN).
* Throttle is interior everywhere -- [0.41, 1.02] against bounds [0.01, 1.05] --
  rather than frozen at its 0.5 initial value.
* Alpha solves to 6.3-9.4 deg rather than sitting at 1.0 deg.
* 10,645 kg for a 737-800 flying 1500 NM at FL350 is in the right band
  (roughly 2.5 t/h in cruise over a ~3.7 h block).

The answer is tolerance-stable: 10645.1498 at atol/rtol 1e-10 and
10645.1508 at 1e-12 (1e-7 relative). At the 1e-8 the example previously used
it lands 1.9e-4 from the root -- inside the parity band but close enough to
it that the example now runs at 1e-10.

### 4. The mission profile was outside the aircraft's envelope

Found only after fixing 1-3, because until then nothing was solving well
enough to notice. The example prescribed a **constant** 2000 ft/min climb to
FL350 and a constant -1500 ft/min descent to sea level. Measured against the
deck:

| Node | Required | Available | |
|------|----------|-----------|---|
| climb, 17,500 ft | 86.7 kN | 83.7 kN | infeasible |
| climb, 35,000 ft | 75.2 kN | 52.0 kN | infeasible |
| descent, sea level | **-3.1 kN** | 110.6 kN | needs drag devices |

A steady-flight throttle balance has a root only where required thrust lies
inside what the engine can produce. Two nodes were outside it and one wanted
negative thrust, so Newton could not converge however good the solver was --
a mission-definition problem wearing a solver problem's clothes.

OpenConcept's own `B738.py` and `B738_VLM_drag.py` decay both rates:
`linspace(2300, 600)` ft/min on climb and `linspace(-1000, -150)` on descent.
The example now uses that shape (omd's `_phase_array` already expanded
`[start, end]` pairs; `shared.phase_array` mirrors it so the two lanes cannot
drift). With it, every node is inside the envelope and Newton converges.

## What is in this change

### Fixes

* `factories/ocp/aircraft_model.py` -- installed-thrust scaling for the
  propulsion slot, mirroring the CFM56 `doubler`. Driven by the
  architecture's `num_engines`; a provider that already models the whole
  installation opts out with `engine_count: 1`.
* `pyc/surrogate.py` -- deck points are judged on physics rather than
  `thrust > 0`; the HBTF grid gains a 35,000 ft line (the design and cruise
  altitude, previously interpolated between 30,000 ft and a mostly-broken
  40,000 ft line) and a 0.15 throttle floor so descent interpolates instead
  of extrapolating; decks are memoized on their generating inputs so the
  three flight phases share one.
* `factories/ocp/{builder,defaults}.py` -- `err_on_non_converge` is now a
  solver setting (off by default to preserve existing plans; on for the
  three-tool example).
* `examples/ocp_three_tool/` -- Newton everywhere, engine-count scaling in
  Lane A, decaying climb/descent rates, and a `HANGAR_HBTF_DECK` escape
  hatch so Lane A can reuse a saved deck.

### Diagnostics

* `diagnostics/solver_coverage.py` -- implicit components no solver in their
  ancestry can solve. Needs only `final_setup()`.
* `diagnostics/deck_quality.py` -- deck admissibility: commanded T4 held,
  thrust in range, monotone in throttle, per-line coverage.
* `diagnostics/thrust_margin.py` -- required vs available thrust per mission
  node, from the deck alone.
* `python -m hangar.omd.diagnostics {solver,deck}` -- both as one-liners.

### Guidance

`skills/omd-cli-guide/{ocp-specifics,slots-and-fidelity}.md` and
`packages/omd/CLAUDE.md` told agents to pick `nlbgs` for dual-surrogate
slots. That advice reaches Lane C agents and reproduces this failure, so
Lane C was not independently broken -- it was following instructions. All
three now say why NLBGS cannot solve an OCP mission and point at the
diagnostics instead.

## Running the checks

```bash
# the fast tiers -- ~4 s total
uv run pytest packages/omd/tests/test_solver_coverage.py \
              packages/omd/tests/test_deck_quality.py \
              packages/omd/tests/test_slot_engine_count.py \
              packages/omd/tests/test_thrust_margin.py -v

# audit any plan for balances no solver can reach (~1 s, stubs the training)
uv run python -m hangar.omd.diagnostics solver \
  packages/omd/examples/ocp_three_tool/lane_b/coupled_mission/plan.yaml

# audit a saved deck
uv run python -m hangar.omd.diagnostics deck /path/to/hbtf_deck.npz

# the real thing (~30 min for the deck, then seconds)
uv run pytest packages/omd/examples/tests/test_parity.py::TestOCPThreeToolParity -v -s
```
