# Plan: native OpenMDAO formulation of evtolpy (upstream)

Status: proposed (not started). This is a design doc, not a committed work item.

## Why this exists

evt is integrated into omd today as a **black box**: `EvtolSizingComp`
(`packages/evt/src/hangar/evt/omd_component.py`) wraps evtolpy's
`Aircraft(...)` + `_iterate_mtow()` inside one OpenMDAO `ExplicitComponent`
with finite-difference partials. That is the right first step (it reproduces
the AIAA SciTech 2026 grid exactly and needs no physics rewrite), but it has
one structural limitation: **evtolpy is gradient-free**, so any optimization
over the component finite-differences the entire fixed-point sizing loop per
design-variable perturbation. That is fine for the small DV counts evt studies
use; it does not scale to coupled, gradient-based MDO (e.g. converging the
eVTOL mass loop simultaneously with an OAS aero point or a pyCycle deck in one
Newton system).

A native OpenMDAO formulation removes that limitation. This doc describes what
it looks like and recommends doing it **upstream in evtolpy** rather than as a
hangar-side fork.

## When to trigger this

Do **not** start this work just because it is possible. Start it when a study
actually needs one of:

- gradient-based optimization over many evtolpy design variables (the FD cost
  of the black box becomes the bottleneck), or
- evtolpy coupled into a single converged solver with another tool (OAS / pyc),
  sharing variables and total derivatives, rather than run as an isolated box.

Until then, the black box is the correct tool. Keep this doc as the ready plan.

## Feasibility: no blockers

evtolpy is structurally already an OpenMDAO model written as Python properties.
From the source review (`upstream/evtolpy/evtol/`):

- Every quantity is a stateless `@property` recomputed from inputs on access.
  The only mutable state is `max_takeoff_mass_kg`, which exists solely to drive
  the iteration (the solver would own that iterate instead).
- Geometry, aero, propulsion/power, the ~15 component masses, and the 18 mission
  segments are all **closed-form algebraic** -- no tables, no interpolation, no
  internal loops, no path dependence.
- The 18 mission segments are **independent**: no segment consumes another's
  output, battery state-of-charge is not carried forward, and total energy is
  `sum(segment energies)`. The mission is one feed-forward block.
- There is exactly **one** feedback loop: MTOW closure
  (`aircraft_modules/aircraft_iteration.py`), a pure fixed-point substitution
  `mtow -> empty + payload + battery -> mtow`.

## What the native build looks like

Group the physics by domain into a handful of components (vectorize rather than
one-component-per-equation):

- `Geometry` -- wing/tail/fuselage areas and chords (closed form).
- `Aero` -- cruise CL/CD buildup, L/D.
- `PropulsionPower` -- disk loading, rotor solidity, hover/cruise power.
- `MissionEnergy` -- 18 segments vectorized; outputs per-segment energy/power
  and the total. Feed-forward.
- `MassBuildup` -- the ~15 component masses + empty mass.

Then close MTOW with the single implicit coupling, two idiomatic options:

- `BalanceComp` / `ImplicitComponent` with residual
  `R = (empty + payload + battery) - mtow`, driven by `NewtonSolver`
  (quadratic convergence; the "right" OpenMDAO way), **or**
- `NonlinearBlockGS` to mirror evtolpy's existing fixed-point substitution
  exactly -- useful during validation to match the legacy iterate step for step.

That is the entire solver structure: one mass-balance Newton loop, the most
common pattern in conceptual-design MDAO.

## The payoff: real derivatives

The reason to do this at all is cheap, accurate derivatives:

- Because the physics is pure arithmetic with no tables, **complex step** gives
  exact component partials, and OpenMDAO assembles total derivatives
  analytically through the model.
- **Caveat that drives the rewrite shape:** the current source uses Python's
  `math` module (`math.sqrt`, `math.log10`, ...), which is **not complex-safe**.
  Complex step cannot be applied to the code as-is. The rewrite must use `numpy`
  math throughout so complex step works. This is the single most important
  mechanical change and the main reason a rewrite (not a thin adapter) is needed.

## Parity strategy (the bulk of the cost)

The work is dominated by validation, not by writing components:

1. Golden-value tests of the native model against current evtolpy across all 18
   AIAA configs (`packages/evt/examples/abu_scitech_2026/cfg/`) plus the
   `test_all` baseline, for: sized MTOW, total/reserve mission energy, peak
   power, the 18 segment energies/powers, and the 15 component masses.
2. A `|delta|` tolerance budget per quantity (energy/power should match to
   floating point; MTOW closure may differ slightly if the solver is Newton vs
   fixed-point -- validate against the `NonlinearBlockGS` variant first to
   isolate solver differences from transcription errors).
3. `check_partials` / `check_totals` with complex step vs FD to confirm the
   derivatives are exact.
4. Re-point omd's `evt/Sizing` factory at the native model behind the same
   metadata contract; the existing `test_abu_reproduction.py` then guards the
   omd-level reproduction unchanged.

## Where it should live: upstream evtolpy (recommended)

Recommendation: implement the native formulation **inside upstream evtolpy**, so
the OpenMDAO model becomes the library's own and the hangar consumes it like any
other OpenMDAO-native tool (as it does OAS / OpenConcept / pyCycle).

Rationale and caveats:

- **Pro:** no hangar-side physics fork to maintain; the AIAA-reproduction drift
  stays "upstream owns the physics" rather than becoming ours; other evtolpy
  users benefit; the hangar factory simplifies to a thin builder.
- **Caveat:** evtolpy ships no `pyproject.toml` (the hangar patches one via
  `scripts/evtolpy-packaging.patch`) and is a small academic library, so an
  upstream OpenMDAO dependency + rewrite needs maintainer buy-in and a packaging
  story. Coordinate before investing.
- **Fallback if upstreaming stalls:** a hangar-side native package
  (`hangar.omd.evt` archetypes) mirroring the self-contained `hangar.omd.pyc`
  pattern -- the hangar already vendors pyCycle archetypes this way. This keeps
  everything in-repo at the cost of owning the physics fork and its parity
  suite. Choose this only if upstream coordination is not viable.

## Effort and risk

- Effort: on the order of weeks, almost all in transcription + the parity suite.
  The component graph itself is small and mechanical.
- Risk: the NDARC mass regressions and empirical factors are easy to transcribe
  with a subtle coefficient/units error; the golden-parity suite is the
  non-negotiable backstop. Drift ownership shifts from upstream to us if forked.

## Decision gate

Before starting: confirm a concrete study needs coupled gradients or
many-DV gradient optimization (see "When to trigger"), and confirm the
upstream-vs-fork decision with the evtolpy maintainer. Until both are true, the
black box stands.
