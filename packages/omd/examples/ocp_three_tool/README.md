# B738 Mission with OAS Drag + pyCycle HBTF Propulsion

First three-tool composition example. Fills both the drag and propulsion
slots in a B738 basic mission, replacing the default parabolic polar
drag with OAS VLM aerodynamics and the default CFM56 with a pyCycle
high-bypass turbofan (HBTF).

B738 + HBTF is a physically matched combination: a 737-class narrowbody
with a CFM56-class dual-spool turbofan at cruise design conditions
(35,000 ft, M=0.8).

## What this demonstrates

Two-slot composition: OCP provides the mission integration framework,
OAS provides aerodynamic drag, and pyCycle provides propulsion
performance. The weight model uses a passthrough OEW since the pyCycle
slot does not expose engine component weights.

Two coupling strategies are provided -- surrogate (B/C) and
direct-coupled (B2/C2):

| Property | Surrogate (B/C) | Direct (B2/C2) |
|----------|----------------|----------------|
| Drag provider | `oas/vlm` (VLMDragPolar) | `oas/vlm-direct` (DirectVLMDragGroup) |
| Propulsion provider | `pyc/surrogate` (Kriging, HBTF) | `pyc/hbtf` (DirectPyCycleHBTFPropGroup) |
| Solver | Newton + DirectSolver | Newton + DirectSolver |
| VLM runs | At init only (training grid) | Every Newton iteration |
| pyCycle runs | At init only (off-design sweep) | Every Newton iteration |
| Partials | Through surrogates (analytic but poorly conditioned) | Through solvers (analytic) |
| Best for | Mission analysis, trade studies | Optimization with engine/aero DVs |

## Slots

### Drag slot

Replaces `PolarDrag` (parabolic CD0 + e model). Removes
`ac|aero|polar|e`, `CD0_TO`, `CD0_cruise` from the aircraft data and
adds `ac|aero|CD_nonwing = 0.0145`.

### Propulsion slot

Replaces the default CFM56 propulsion model. Removes
`ac|propulsion|engine|rating`. The pyCycle HBTF is designed at cruise
conditions (35,000 ft, M=0.8, Fn=5900 lbf, T4=2857 degR).

### Weight (default)

With a propulsion slot active, OEW uses a passthrough ExecComp reading
`ac|weights|OEW = 41871 kg` from the B738 template data.

## Solver note: why not NLBGS

The surrogate-coupled variant used to run NLBGS + Aitken, on the theory
that the dual-surrogate Jacobian was too ill-conditioned for Newton.
That was a misdiagnosis, and the workaround was worse than the disease.

OpenConcept's mission groups carry no solvers of their own, and each
phase contains three `BalanceComp`s: throttle (thrust = drag), alpha (to
hit the target CL), and phase duration. `NonlinearBlockGS` only *calls*
each subsystem's `_solve_nonlinear`, and `BalanceComp` defines none -- so
all nine balances kept their initial values (throttle frozen at 0.5,
alpha at 1 deg) while NLBGS reported convergence in three iterations.
The numbers it produced were initial guesses propagated through the
explicit components, not a solution.

Newton was in fact reporting something true. Two real defects sat
underneath it:

* **The deck was trained on non-physics.** Deck generation accepted any
  point with `thrust > 0 and fuel > 0`, which kept off-design solves
  that had settled on spurious roots -- including 6.6e10 lbf at
  T4 = 270 degR. Kriging normalizes by the training standard deviation,
  so one such point drove predicted cruise thrust to ~2.3e6 kN against a
  true ~26 kN. Points are now judged on physics
  (`hangar.omd.diagnostics.check_deck`): commanded T4 actually held,
  thrust within range of design, monotone in throttle.
* **The mission flew on one engine.** pyCycle slot providers model a
  single engine; the CFM56 path OCP ships doubles through its own
  ExecComp, but the slot path had no equivalent. Cruise needs ~44 kN and
  one engine gives ~24 kN, so the throttle balance had no solution and
  pegged at its upper bound. Both lanes now scale by the architecture's
  engine count.

With those fixed, Newton converges and both variants use it. Run
`hangar.omd.diagnostics.find_unsolved_implicit(prob)` on any mission
plan to check that a solver can actually reach every balance -- it needs
only `final_setup()`, so it answers in about a second.

## Lane structure

| Lane | What it is | Coupling |
|------|-----------|----------|
| A | Direct upstream code (raw OpenMDAO, no omd) | Surrogate |
| B | omd plan pipeline (`run_plan()` / `omd-cli run`) | Surrogate |
| B2 | omd plan pipeline | Direct |
| C | Agent prompt (use with omd-cli-guide skill) | Surrogate |
| C2 | Agent prompt | Direct |

## Running the lanes

### Lane A: direct reference (surrogate-coupled)

Builds the OpenMDAO problem manually with `VLMDragPolar` +
`PyCycleSurrogateGroup` (HBTF archetype) wired into the B738 aircraft
model, scaled to two engines. Newton + DirectSolver with
`err_on_non_converge`.

The surrogate deck generation runs at setup time and takes ~20 minutes
for the 180-point HBTF grid. It is cached per process (keyed on
archetype, design conditions, engine params and grid), so the three
flight phases share one deck instead of generating three.

To reuse a deck across runs, save one and point Lane A at it:

```bash
HANGAR_HBTF_DECK=/path/to/hbtf_deck.npz \
  uv run python packages/omd/examples/ocp_three_tool/lane_a/coupled_mission.py
```

Lane B takes the same shortcut via `deck_path` in the slot config.

```bash
uv run python packages/omd/examples/ocp_three_tool/lane_a/coupled_mission.py
```

### Lane B: omd plan pipeline (surrogate-coupled)

Runs through the full omd pipeline with `oas/vlm` + `pyc/surrogate`
(HBTF) slots and the Newton solver, with `err_on_non_converge` set so a
mission that hits maxiter raises instead of reporting initial guesses.

```bash
uv run python -m hangar.omd.cli run packages/omd/examples/ocp_three_tool/lane_b/coupled_mission/plan.yaml --mode analysis
```

### Lane B2: omd plan pipeline (direct-coupled) -- WIP

Direct-coupled providers with Newton solver. Coarser VLM mesh (num_y=5)
to keep per-iteration cost manageable.

**Status**: The direct-coupled HBTF does not yet converge in the OCP
mission. The HBTF inner Newton fails at extreme off-design conditions
(climb start at sea level, far from the 35kft/M0.8 design point). The
nozzle static pressure solver produces large residuals. Needs
condition-aware `guess_nonlinear` or a warmup strategy.

```bash
uv run python -m hangar.omd.cli run packages/omd/examples/ocp_three_tool/lane_b2/direct_coupled_mission/plan.yaml --mode analysis
```

### Lane C / C2: agent prompts

Prompts an agent can use to reproduce the analysis via the omd-cli-guide
skill.

## Parity test

Verifies Lane A and Lane B produce matching results (surrogate path):

```bash
uv run pytest packages/omd/examples/tests/test_parity.py::TestOCPThreeToolParity -v -s
```
