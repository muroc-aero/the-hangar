# Plan Authoring

Deep-dive companion to `SKILL.md` covering:

- the interactive plan builder (`omd-cli plan init/add-*/set-*`),
- the decision-logging contract (what, when, how),
- enriched requirements with acceptance criteria and verification,
- the `analysis_plan` section,
- the `omd-cli plan review` completeness checker.

## Interactive Plan Builder

New plans can be built step-by-step through `omd-cli plan` subcommands
instead of hand-writing YAML files. Each subcommand mutates one
modular file, validates the resulting partial plan, and (when
`--rationale` is passed) auto-appends a structured entry to
`decisions.yaml`.

```bash
# Scaffold the plan directory (creates metadata.yaml only)
omd-cli plan init hangar_studies/my-plan --id my-plan --name "My study"

# Add a component. Flag-driven (supply a ready-made config):
omd-cli plan add-component hangar_studies/my-plan \
    --id wing --type oas/AerostructPoint \
    --config-file wing-config.yaml \
    --rationale "Baseline wing geometry"

# Or interactively (Click prompts for each field; rationale required):
omd-cli plan add-component hangar_studies/my-plan -i

# Set operating point, solver, DVs, and objective
omd-cli plan set-operating-point hangar_studies/my-plan \
    --mach 0.84 --alpha 5.0 --velocity 248 --re 1e6 --rho 0.38 \
    --rationale "Cruise design point"
omd-cli plan set-solver hangar_studies/my-plan \
    --nonlinear NewtonSolver --linear DirectSolver \
    --nonlinear-maxiter 20 --rationale "Standard aerostruct choice"
omd-cli plan add-dv hangar_studies/my-plan \
    --name twist_cp --lower -10 --upper 15 \
    --rationale "Conservative envelope"
omd-cli plan set-objective hangar_studies/my-plan \
    --name structural_mass --scaler 1e-4 --rationale "Primary goal"

# Hand-authored decision, phase scaffold, completeness check
omd-cli plan add-decision hangar_studies/my-plan \
    --stage optimizer_selection --decision "SLSQP with maxiter 200" \
    --rationale "Inequality constraints + continuous DVs"
omd-cli plan set-analysis-strategy hangar_studies/my-plan \
    --phases 2 --rationale "Baseline verify then optimize"
omd-cli plan review hangar_studies/my-plan
```

**DV / objective short-name validation.** `add-dv` and `set-objective`
validate the name against the component's factory `var_paths`. Under
`--interactive`, the allowed short names are printed before the
prompt. For OAS AerostructPoint: `twist_cp`, `thickness_cp`,
`chord_cp`, `spar_thickness_cp`, `skin_thickness_cp`, `t_over_c_cp`,
`S_ref`, `structural_mass`, `CL`, `CD`, `CDi`, `CDv`, `CDw`, `CM`,
`failure`, `tsaiwu_sr`, `L_equals_W`, `fuelburn`. For OAS AeroPoint:
`twist_cp`, `chord_cp`, `t_over_c_cp`, `S_ref`, and the same `CL..CM`
set. Prefixed forms like `wing.twist_cp` are accepted as long as the
suffix matches.

**Rationale policy.** Under `--interactive`, the subcommand refuses an
empty rationale (exit 1). In non-interactive runs `--rationale` is
optional; omitting it means no `decisions.yaml` entry is appended.
Auto-appended decisions use `dec-auto-{N}` ids and a stage inferred
from the primitive (`add_dv → dv_setup`, `set_objective →
objective_selection`, etc.).

**Partial validation.** Each mutation validates against a relaxed
schema (`validate_partial`) so missing top-level sections are
permitted, but structural errors in whatever *is* present (bad
component config, malformed requirement, etc.) fail fast with the
file reverted.

See `packages/omd/docs/plan-authoring-workflow.md` for a richer
walkthrough and `commands.md` for the full subcommand reference.

## Decision Logging (Required)

Agents MUST record decisions at key points in every omd workflow.
There are two mechanisms depending on context:

### CLI vs MCP Decision Logging

| Context | Mechanism | Storage |
|---------|-----------|---------|
| **CLI workflow** (`omd-cli`) | Add entries to `decisions.yaml` in the plan directory, then re-assemble | Persisted in the assembled plan YAML and plan store |
| **MCP workflow** (interactive) | Call `log_decision()` tool | Recorded in the SDK provenance DB with session context |

Use `decisions.yaml` when building plans from files. Use
`log_decision()` when working interactively through MCP tool calls.
Both produce provenance records, but through different paths.

### Decision Types

| Type | When | What to Log |
|------|------|-------------|
| `formulation_decision` | After choosing mesh, fidelity, solver | Mesh resolution (num_y, num_x), solver type, why this fidelity level was chosen |
| `result_interpretation` | After each analysis run | Specific metric values (CL, CD, L/D, mass), whether they are physically reasonable, comparison to expectations |
| `dv_selection` | Before optimization | Which DVs were chosen and why, bound rationale, constraint selection |
| `convergence_assessment` | After optimization | Iteration count, constraint satisfaction, whether result is accepted or needs rerun |
| `replan_reasoning` | When changing approach | What failed, root cause diagnosis, what changed in the new plan version |

### CLI Workflow: Step by Step

1. Create the plan directory with component YAML files (or use the
   interactive builder above).
2. **Log formulation decision** -- add an entry to `decisions.yaml`
   explaining mesh/solver choices.
3. Run `omd-cli assemble my-plan/` to produce `plan.yaml`.
4. Run `omd-cli run plan.yaml --mode analysis`.
5. **Log result interpretation** -- add an entry to `decisions.yaml`
   with specific values from the run output.
6. Run `omd-cli assemble my-plan/` again to capture the new decision.
7. If optimizing: **log dv_selection** before, **log
   convergence_assessment** after.
8. If replanning: **log replan_reasoning** explaining what changed
   and why.

### Agent Checklist

Before running analysis:
- [ ] Log `formulation_decision` with mesh density, solver, and fidelity rationale.

After running analysis:
- [ ] Log `result_interpretation` with specific numeric values and physics reasoning.

Before running optimization:
- [ ] Log `dv_selection` with DV names, bounds, and constraint choices.

After running optimization:
- [ ] Log `convergence_assessment` with iteration count and constraint status.

On any replan:
- [ ] Log `replan_reasoning` with failure diagnosis and changes made.

### decisions.yaml: Good vs Insufficient Examples

**Good entry** -- specific values, physics reasoning, actionable
conclusion:

```yaml
- decision_type: result_interpretation
  agent: have-agent
  reasoning: >
    CL=0.45, CD=0.035, L/D=12.9 at M=0.84, alpha=5 deg.
    CD is consistent with a rectangular wing at this Mach number
    (wave drag onset near M=0.85). Structural mass 1,247 kg with
    failure=-0.12 (safe, 12% margin below yield). L/D of 12.9 is
    reasonable for an unswept rectangular planform.
  selected_action: "Accept baseline results; proceed to twist optimization"
```

**Insufficient entry** -- vague, no numbers, no physics reasoning:

```yaml
- decision_type: result_interpretation
  agent: have-agent
  reasoning: "Results look reasonable"
  selected_action: "Proceed"
```

The difference: a good entry lets someone (or a future agent)
understand *why* the results were accepted without re-running the
analysis.

### Enriched Decision Format

Each decision in `decisions.yaml` can (and should) carry two extra
fields that let the plan knowledge graph and provenance DAG render
decisions as concrete justifications instead of free-floating nodes:

```yaml
- id: dec-mesh
  stage: mesh_selection                                  # see recommended stages below
  decision: Set num_y=7
  rationale: Moderate fidelity for exploration.
  element_path: "components[wing].config.surfaces[wing].num_y"   # what this justifies
  alternatives_considered:
    - option: "num_y=21"
      rejected_because: Iteration time too high for exploration.
```

**`element_path`** addresses the specific plan element the decision
justifies. Supported syntax:

- `components[wing]` or `design_variables[wing.twist_cp]` -- id/name
  match.
- `components[wing].config.surfaces[wing].num_y` -- dot-separated
  nested access.
- `objective`, `solvers.nonlinear`, `solvers.linear`,
  `requirements[R1]`, `analysis_plan.phases[phase-1]`.
- `connections[0].src` -- positional fallback when elements have no
  id.

When `element_path` is present the plan knowledge graph emits a
`justifies` edge from the decision node to the specific element node.
When it's absent the checker warns and the edge falls back to the
generic "plan" node.

**Recommended `stage` values** (enforced softly by `plan review`):
`problem_definition`, `component_selection`, `mesh_selection`,
`solver_selection`, `dv_setup`, `constraint_setup`,
`objective_selection`, `operating_point_selection`,
`optimizer_selection`, `diagnosis`, `replan`, `formulation`.

`stage` is a free string; custom values are allowed but trigger a
WARN in `omd-cli plan review`. If a stage label is recurring, add it
to `RECOMMENDED_DECISION_STAGES` in `plan_schema.py`.

## Enriched Requirements

Requirements can carry acceptance criteria and a verification method
so runs can be checked automatically later:

```yaml
- id: R1
  text: Minimize structural mass under cruise aerostructural loading.
  type: objective
  priority: primary                 # primary | secondary | goal
  source: study instruction
  status: open                      # draft | open | verified | violated | waived
  traces_to: [structural_mass, twist_cp, thickness_cp]
  acceptance_criteria:
    - metric: structural_mass
      comparator: "<"               # < | <= | > | >= | == | != | in
      threshold: 200.0
      units: kg
  verification:
    method: automated               # automated | visual | comparison
    assertion: "structural_mass < 200.0"
```

The `status` field drives border color in the provenance DAG
(verified=green, violated=red, waived=grey/dashed). Requirements are
recorded as first-class provenance entities so downstream assessments
can emit `satisfies` / `violates` edges against them.

## analysis_plan: Capture Process, Not Just Product

An optional top-level `analysis_plan` section documents *how* the
analysis should proceed, alongside *what* to analyze:

```yaml
analysis_plan:
  strategy: Verify baseline, optimize, then assert.
  phases:
    - id: phase-1
      name: Baseline verification
      mode: analysis
      depends_on: []
      success_criteria:
        - metric: CL
          comparator: in
          range: [0.3, 0.7]
      checks:
        - type: plot
          plots: [planform, lift, twist]
          look_for: Smooth lift distribution
        - type: assertion
          command: "range-safety validate {plan}"
    - id: phase-2
      name: Optimization
      mode: optimize
      depends_on: [phase-1]
      success_criteria: [...]
      checks: [...]
  replan_triggers:
    - Solver divergence or NaN
    - Optimizer hits maxiter
```

Phases are rendered in both the plan knowledge graph and the
provenance DAG (violet nodes, `precedes` edges). Today phases are
*documentation*; execution orchestration (`omd-cli run --phase`) is
deferred -- see `packages/omd/docs/deferred-enhancements.md`.

## omd-cli plan review

Reports per-section completeness (OK / WARN / MISSING / ERROR).
Always exits 0 (advisory). Use `--format json` for CI gating.

```bash
omd-cli plan review my-plan/
omd-cli plan review my-plan/plan.yaml
omd-cli plan review my-plan/ --format json > review.json
```

What it flags:

- requirements without acceptance_criteria or verification method
- decisions without `element_path` (cannot render as `justifies` edges)
- decisions whose `element_path` fails to resolve against the plan
- decisions with a `stage` value outside the recommended set
- configurable sections (mesh, DVs, constraints, objective, solvers,
  optimizer) with no decisions pointing at them
- missing `analysis_plan` or phases without `success_criteria` / `checks`
- `analysis_plan` phase `depends_on` referring to an unknown phase (ERROR)
- missing top-level `rationale`

The checker and the graph builder share the same element-path
resolver, so a WARN here corresponds exactly to a missing edge in the
viewer.
