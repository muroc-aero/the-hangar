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
| Solver | NLBGS + Aitken | Newton + DirectSolver |
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

## Solver note: dual-surrogate coupling

The surrogate-coupled variant uses NLBGS (Gauss-Seidel) with Aitken
relaxation instead of Newton. Both surrogates provide analytic
derivatives via their metamodel components, but the combined Jacobian
is ill-conditioned, causing Newton to diverge. NLBGS avoids this by
iterating subsystems sequentially without forming the system Jacobian.

The direct-coupled variant uses Newton normally since VLM and pyCycle
provide well-conditioned analytic partials through their actual solvers.

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
model. Uses NLBGS + Aitken.

The surrogate deck generation runs at setup time and can take 15-30
minutes.

```bash
uv run python packages/omd/examples/ocp_three_tool/lane_a/coupled_mission.py
```

### Lane B: omd plan pipeline (surrogate-coupled)

Runs through the full omd pipeline with `oas/vlm` + `pyc/surrogate`
(HBTF) slots and NLBGS solver.

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
