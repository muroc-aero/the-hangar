# Parity lanes and agent eval: how the Hangar proves its wrappers use the upstream tools correctly

**Audience:** new developers getting up to speed on how the Hangar tests that
its MCP/CLI wrappers and the omd plan runner reproduce the upstream engineering
tools, and the authors of the-hangar paper who need a precise, citable account
of the design, its relationship to differential/metamorphic testing and to
recent agentic-MDAO / MCP-agent benchmarks, and where it differs.

**TL;DR.** Every capability the Hangar exposes is expressed as *the same
engineering problem, solved three ways*, and correctness is defined as
**agreement across the three lanes**:

| Lane | What runs | The claim it certifies |
|---|---|---|
| **A** | direct OpenMDAO / OAS / OpenConcept / pyCycle / evtolpy Python, hand-written | "this is what the upstream tool says" — the **reference** |
| **B** | a declarative omd plan YAML through the omd materializer + runner | "the plan pipeline reproduces the upstream tool" |
| **C** | the MCP tool surface — first **scripted in-process**, then a **blind LLM agent** — | "an agent working only the tools reproduces the upstream tool" |

A case *passes* when Lanes B and C match Lane A to a stated per-metric tolerance.
Because there is no analytic oracle for "what should this VLM/mission/cycle
analysis return," Lane A **is** the oracle: it is the shortest path to the
upstream physics with no Hangar code in the way. The wrappers are correct iff
they land on the same numbers. This is a **pseudo-oracle / differential-testing**
design (see §7), specialized to a wrapper-equivalence question and extended with
a **blind-agent lane** that also tests whether the tool surface is *discoverable*,
not just numerically faithful.

Two things make it more than "run it twice and diff": (1) a small set of
**golden physics anchors** pins Lane A itself to published/upstream values so a
silent upstream regression is caught, separately from lane-to-lane drift; and
(2) the parity suites are the **single source of truth** — the paper's results
harness re-runs the very same pytest suites through a recording hook rather than
re-implementing any lane orchestration.

---

## 1. Why lanes at all

A wrapper server has a peculiar correctness question. The physics is upstream
and trusted; what can break is *the Hangar's translation of it* — a mesh key not
forwarded to OAS, a unit dropped, a solver setting silently defaulted, a short
DV name resolved to the wrong OpenMDAO path, a plan schema that materializes a
subtly different problem. None of these throw; they return plausible wrong
numbers. There is no closed-form answer to check against.

The lane design turns that into a checkable question. Fix one problem
specification. Reach the upstream tool three ways with progressively more Hangar
machinery in the path:

- **Lane A** imports the upstream library directly and drives it with raw
  OpenMDAO — the fewest moving parts, so it is the least likely to be wrong and
  is treated as the reference.
- **Lane B** encodes the identical problem as an omd plan and runs it through the
  materializer, factory registry, solver/DV wiring, and recorder — the full
  declarative pipeline.
- **Lane C** reaches the same plan through the MCP tool surface an agent actually
  sees (`plan_init` → `plan_add_component` → … → `run_plan` → `get_results`).

If B or C disagrees with A beyond tolerance, a specific layer of the wrapper is
mistranslating the problem, and the diff table points at which metric. If all
three agree, every layer between the tool boundary and the upstream physics is
faithful. That is the whole idea; everything below is mechanism.

---

## 2. Two levels of the harness

The lane pattern exists at two scopes.

### 2.1 Per-tool examples (Lane A vs Lane B, one server at a time)

Each leaf server ships an `examples/<case>/` package that certifies *that
server's own* CLI/MCP wrapper against raw upstream code:

- `packages/oas/examples/rectangular_wing/` — VLM aero, drag polar, twist & chord
  optimization.
- `packages/ocp/examples/caravan_mission/`, `.../kingair_mission/` — OpenConcept
  missions.
- `packages/pyc/examples/turbojet/` — pyCycle design/off-design.
- `packages/evt/examples/mission_segments/`, `.../abu_scitech_2026/` — evtolpy
  energy/power/mass and the AIAA SciTech 2026 case study.

Here Lane A is `lane_a/*.py` (raw library) and Lane B is `lane_b/*.json` — a
list of MCP tool-call steps replayed **in process** through the shared SDK CLI
runner (`hangar.sdk.cli.runner.run_tool`), so the test exercises the real tool
implementations without spawning a server. See
`packages/oas/examples/rectangular_wing/tests/test_parity.py:27` (`run_lane_b`)
and `:44` (`run_lane_a`). Tolerances live beside the parameters in `shared.py`.

### 2.2 omd cross-tool examples (Lanes A/B/C, the composition layer)

The primary parity system — and the one the paper reports — lives under
`packages/omd/examples/`. There are **13 cases** spanning single-tool,
coupled-tool, and three-tool problems, each a directory with `lane_a/`,
`lane_b/`, `lane_c/`, `shared.py`, and a `README.md`:

| Case (dir) | Tools | Headline metrics |
|---|---|---|
| `paraboloid` | OpenMDAO | `f_xy` (analysis + SLSQP opt) |
| `oas_aero_rect` | OAS VLM | `CL`, `CD` |
| `oas_aerostruct_rect` | OAS tube-FEM | `CL`, `CD` |
| `ocp_caravan_basic` / `ocp_caravan_full` | OpenConcept | `fuel_burn_kg`, `OEW_kg`, `MTOW_kg` |
| `ocp_hybrid_twin` | OpenConcept (series-hybrid) | mission masses |
| `oas_ocp_combined` | OAS + OCP (uncoupled composite) | `wing_CL/CD` + mission |
| `ocp_oas_coupled` / `ocp_oas_direct` | OCP + OAS VLM drag slot | mission masses |
| `ocp_pyc_coupled` | OCP + pyCycle | mission masses *(known gap, §6)* |
| `pyc_turbojet` | pyCycle | `Fn`, `TSFC`, `OPR` |
| `evt_native_sizing` | native-evt OpenMDAO | `sized_mtow_kg`, energy, peak power |
| `ocp_three_tool` | OCP + OAS + pyCycle | mission masses (deactivated 2026-09-20, see its README; PR #88) |
| `avy_three_tool` | Aviary + OAS + pyCycle | sizing masses, wing mass, engine scale factor |

The list is the same set the paper's Table renders; slugs match the `case=` tags
in the tests (`paper/make_tables.py:37`, `CASE_INFO`).

---

## 3. Anatomy of one example

Take `packages/omd/examples/oas_aero_rect/`:

```
oas_aero_rect/
  shared.py                       # single source of truth: WING, FLIGHT, tolerances
  lane_a/aero_analysis.py         # raw OpenAeroStruct + OpenMDAO -> {"CL","CD"}
  lane_b/aero_analysis/           # modular plan YAML (metadata/components/op point)
  lane_c/
    aero_analysis.prompt.md       # "closed" prompt: names the tools/steps
    aero_analysis_open.prompt.md  # "open" prompt: engineering goal + physics only
    README.md
```

**`shared.py` — the contract.** All lanes import the same geometry, flight
condition, and tolerances from one module, so the lanes cannot silently drift
apart by editing a number in only one place. `shared.py` also carries the
tolerance dicts, which are consumed directly by `pytest.approx`
(`packages/oas/examples/rectangular_wing/shared.py:65`):

```python
TOL_ANALYSIS = dict(rtol=1e-6)   # CL/CD for analysis runs
TOL_OPT_OBJ  = dict(rtol=1e-3)   # optimized objective
TOL_OPT_CON  = dict(atol=1e-4)   # constraint satisfaction
```

**Lane A** builds the OpenMDAO problem by hand and returns a plain dict
(`packages/omd/examples/oas_aero_rect/lane_a/aero_analysis.py:16`). It is
deliberately verbose and dependency-light — no Hangar imports beyond `shared` —
because it is the reference the other two lanes are judged against.

**Lane B** is the same problem as declarative YAML. The plan names the component
type (`oas/AeroPoint`), the surface config, and the operating point; the omd
materializer turns it into the same OpenMDAO problem
(`packages/omd/examples/ocp_caravan_basic/lane_b/basic_mission/plan.yaml` shows
the shape — component `config` mirrors the Lane A kwargs one-for-one, including
the Newton/Direct solver settings so the two solve the *same* problem, not merely
a similar one).

**Lane C** is the plan *authored through tools*, and it comes in two prompt
flavours that matter for the agent eval (§5): a **closed** prompt that spells out
the workflow, and an **open** prompt that gives only the engineering goal and the
physical inputs and explicitly withholds the component type, parameter keys, and
tool sequence (`oas_aero_rect/lane_c/aero_analysis_open.prompt.md` ends: *"This
task deliberately does not name the component type, parameter keys, or tool
workflow. Consult the server's own reference material to choose them."*).

---

## 4. The parity mechanism (Lane A vs B)

`packages/omd/examples/tests/test_parity.py` is one pytest class per case. Each
test:

1. imports and runs the Lane A module → reference dict;
2. `assemble_plan()`s the Lane B modular YAML and `run_plan(mode="analysis")`s it;
3. calls `_print_comparison(...)` to emit a side-by-side table and record it;
4. asserts each metric `== pytest.approx(lane_a[...], rel=...)`.

A representative body (`test_parity.py:141`, the OAS aero case):

```python
lane_a = lane_a_run()
assemble_plan(plan_dir, output=out)
result = run_plan(out, mode="analysis", recording_level="minimal", db_path=...)
_print_comparison("OAS Aero Analysis", lane_a, result["summary"],
                  keys=["CL", "CD"], case="oas_aero_rect")
assert result["summary"]["CL"] == pytest.approx(lane_a["CL"], rel=1e-6)
assert result["summary"]["CD"] == pytest.approx(lane_a["CD"], rel=1e-6)
```

Key mechanics:

- **The comparison printer is also the recorder.** `_print_comparison`
  (`test_parity.py:66`) always prints a `Metric | Lane A | Lane B | Diff%` table
  (visible with `pytest -s`), and — *only if* `$PARITY_RESULTS_JSONL` is set —
  appends a JSON row via `_record_comparison` (`test_parity.py:26`). That env-var
  hook is how the paper harness harvests numbers without duplicating lane logic
  (§8). With the var unset, the tests are ordinary CI parity tests.
- **Composite results are unwrapped explicitly.** For multi-component plans the
  runner nests results under `summary["components"][id]`; the test flattens them
  before comparing (`test_parity.py:277`, the OAS+OCP composite).
- **Per-test isolation.** `conftest.py:10` (`isolate_omd_data`) redirects the omd
  DB, plan store, and recordings to a `tmp_path` per test; `conftest.py:29`
  (`clean_shared_modules`) purges each example's `shared` and package modules from
  `sys.modules` between tests, because every example ships a *different* `shared.py`
  and they collide on `sys.path` otherwise. This module-collision hazard is real
  and recurs in the agent harness, which sidesteps it with subprocesses (§5).
- **Tiered tolerances encode intent.** Analysis metrics that should agree to
  round-off use `rel=1e-6`; optimizer objectives that depend on convergence path
  use `rel=1e-3`; mission fuel burn uses `rel=1e-3`; MTOW (an input echoed
  through) uses `rel=1e-6`. The tolerance is a claim about *how identical the two
  lanes should be*, and slack is granted only where a solver or optimizer
  legitimately introduces it.

---

## 5. Lane C in two stages: scripted surface, then blind agent

Lane C is "the agent path," and it is certified in two escalating stages.

### 5.1 Stage 1 — scripted tool surface (in CI, no agent)

`packages/omd/examples/tests/test_parity_lane_c.py` drives the **actual MCP tool
functions** in process — `plan_init`, `plan_add_component`, `plan_set_solver`,
`plan_set_operating_point`, `plan_add_dv`, `plan_set_objective`, `assemble_plan`,
`validate_plan`, `run_plan`, `get_results` — and compares to Lane A with the same
tolerances. It reuses `_print_comparison` from the A-vs-B suite with
`lane_label="C"` so both lanes land in the same JSONL stream
(`test_parity_lane_c.py:39`). It unwraps the versioned response **envelope**
and fails loudly on an error envelope (`_summary`, `:56`), and it asserts the run
came back `completed`/`converged` and that the optimum is retrievable through
`get_results` (`:176`).

This stage certifies that *the tool surface itself* — workspace resolution,
schema validation, envelope shape, plan authoring order — reaches the same
physics. It runs in CI with no API credentials. Twelve of the thirteen cases are
covered (`ocp_pyc_coupled` excepted, §6), so the "Lane C (scripted)" table
column is fully populated by a plain test run.

### 5.2 Stage 2 — blind agent eval (the real thing)

`packages/omd/examples/agent_eval/eval_lane_c.py` runs a live LLM agent through
the **Claude Agent SDK** against a real omd MCP **stdio** server, and scores what
it reports against Lane A. This is where "can an agent actually use the tools
correctly" is tested, not just "do the tools compute correctly."

The harness (`eval_lane_c.py`):

- **Computes Lane A in a subprocess per example** (`lane_a_reference`, `:191`) —
  one process each, precisely because the `shared.py` modules collide otherwise
  (the same hazard the conftest handles with module purging).
- **Builds a blind prompt** (`build_prompt`, `:249`): the example's *open*
  prompt, wrapped in a preamble with **hard rules** — *ONLY* the `mcp__omd__*`
  tools, no filesystem/shell/web, "the task states the engineering goal, not the
  tool procedure … work out the right calls from the server's own affordances:
  tool descriptions, the `omd://reference` resource, and error messages"
  (`PREAMBLE`, `:213`) — plus a required fenced-JSON report format (`:228`).
- **Sandboxes the agent** (`run_agent`, `:263`): `allowed_tools=["mcp__omd"]`,
  `disallowed_tools` covering Bash/Read/Write/Glob/Grep/WebFetch/WebSearch/Task,
  a fresh `OMD_DATA_ROOT` in a temp dir, and `permission_mode="bypassPermissions"`.
  The agent has **no access to the repo**, so it cannot peek at `lane_a`/`lane_b`.
- **Scores** the parsed report metric-by-metric against Lane A within per-metric
  rtols (`score_case`, `:332`), prints a `Lane A | Agent | Rel err | Verdict`
  table, exits nonzero on any *required*-metric miss, and prints the agent's
  self-reported **friction log** (tool errors, confusing parameters,
  workarounds) — which feeds `docs/FEATURE_BACKLOG.md`.

The open-vs-closed prompt split is the crux: passing the open prompt means the
agent **discovered** the component type, config keys, slot providers, and
tool-call order from the server's self-description alone. That certifies the tool
surface is *self-teaching*, a stronger and more paper-worthy claim than "the
functions compute the right number."

### 5.3 Stage 3 — sandboxed local-model evals (sibling repo)

A third variant lives in the sibling `hangar-evals` repo: local models × OpenCode
/ OpenHands harnesses, summarized into `*_summary.json` and folded into the paper
by `paper/make_tables.py` (`build_evals_rows`, `:260`). It reports operational
metrics (valid-call rate, turns, wall-clock, pass rate) rather than parity
tolerances — it measures *harness/model fitness on the tool surface*, complementary
to the numeric-parity question.

---

## 6. Two kinds of tolerance, and the honest gaps

**Parity tolerance vs golden anchor.** These answer different questions and the
`evt_native_sizing` example makes the split explicit
(`packages/omd/examples/evt_native_sizing/shared.py:28`):

- `TOL_PARITY = dict(rel=1e-9, abs=1e-9)` — B and C drive the *same* native
  problem A builds, so they must agree to **round-off**. This catches a wrapper
  mistranslation.
- `TOL_GOLDEN = dict(rel=1e-4)` on pinned `GOLDEN` values — Lane A itself is
  checked against values pinned from upstream evtolpy. This catches an **upstream
  physics regression** on a pin bump, independently of lane agreement. Without it,
  all three lanes could drift together and the parity checks would still pass.

The evt case adds a third: `TOL_GRADIENT` checks the native model's analytic
`d(MTOW)/d(payload)` against a finite difference — a capability (differentiable
sizing) the upstream black box lacks, so parity there is against FD, not against a
second implementation.

**What the harness deliberately does NOT cover / known gaps:**

- **`ocp_pyc_coupled` has no Lane B/scored Lane C.** A faithful plan cannot reach
  parity with its Lane A reference: the shared materializer's weight-slot
  precedence forces an OEW passthrough (~8% OEW / ~4% fuel gap). It is documented
  as non-physical in that example's `TODO.md`, excluded by default in
  `paper/run_lanes.py` (`KNOWN_GAPS`, `:45`), and *not scored* in the agent eval.
  This is surfaced, not hidden — a model of how a negative result is recorded.
- **DV retrieval through the tool surface is a known gap.** The paraboloid agent
  case marks `opt_x`/`opt_y` as `required=False` (warn, not fail) because reading
  optimized DV values back through the tools is incomplete (FEATURE_BACKLOG). The
  scripted Lane C only asserts the *objective*, plus that a results handle exists.
- **No cross-lane check of intermediates.** Parity is asserted on the headline
  summary metrics named per case, not on per-iteration histories, plots, or
  provenance edges. Convergence *is* checked (status must be
  `completed`/`converged`) but the iteration path is not compared lane-to-lane.
- **Agent eval is not hermetic across model versions.** Stage 2 depends on a live
  model and API; it is designed for cron/CI-with-credentials, and results carry a
  cost and a model tag, not a fixed expectation.

---

## 7. What the recorded schema includes

When `$PARITY_RESULTS_JSONL` is set, each comparison is one JSON line
(`_record_comparison`, `test_parity.py:26`):

```json
{"case": "oas_aero_rect", "name": "OAS Aero Analysis", "lane": "B",
 "keys": ["CL", "CD"], "lane_a": {"CL": 0.53, "CD": 0.031},
 "values": {"CL": 0.53, "CD": 0.031}}
```

- `case` — stable slug joining A/B/C rows and the paper `CASE_INFO`.
- `lane` — `"B"` or `"C"`; Lane A is carried on every row as the reference.
- `keys` / `lane_a` / `values` — the compared metrics and both lanes' numbers,
  coerced to float/str so the record is portable.

The agent eval writes a richer per-case record (`eval_lane_c.py:431`): `plan_id`,
`run_id`, `status`, `cost_usd`, the `friction` list, and a `metrics` array of
`{key, lane_a, agent, rel_err, rtol, required, verdict}`. `make_tables.py` maps
agent metric keys back onto parity case slugs (`AGENT_METRIC_MAP`, `:112`) so the
agent column aligns with the scripted columns.

The schema **does not** carry: units (they are implicit in the metric name and
enforced in-lane), solver iteration traces, timing/telemetry, or provenance —
those live in the response envelope and the provenance DB
(see [`provenance-and-capture-tool.md`](provenance-and-capture-tool.md)), not in
the parity record. The parity record is intentionally a thin numeric ledger.

---

## 8. The paper harness: tests as the single source of truth

`paper/run_lanes.py` does **not** re-implement any lane. It runs the existing
pytest suites with the recording hook enabled:

```python
env = dict(os.environ, PARITY_RESULTS_JSONL=str(args.out))
cmd = [sys.executable, "-m", "pytest",
       "packages/omd/examples/tests/test_parity.py",
       "packages/omd/examples/tests/test_parity_lane_c.py", "-v", "-s"]
```

(`paper/run_lanes.py:82`). It truncates the JSONL so one run = one coherent
result set, deselects the known-gap node unless `--include-known-gaps`, supports
`--quick` (`-m "not slow"`) and `-k`, and writes `lane_parity_meta.json` with the
git SHA, timestamp, and **the pytest exit code** — a nonzero exit is stamped into
the rendered table's comment so a failing parity run cannot be silently reported
as clean (`:97`). `paper/make_tables.py` renders `lane_parity.{csv,md,tex}` with
`rel diff` columns for B, scripted C, and (when present) agent C. The invariant
is that the tests remain the one place that defines *how each lane runs and what
tolerance counts as a pass*; the paper reads them, it does not paraphrase them.

Full recipe in `paper/README.md`.

---

## 9. Related work, and how the-hangar differs

The parity design sits at the intersection of a classic software-testing idea and
a very new agent-evaluation one.

**Differential / pseudo-oracle / metamorphic testing.** When a program has no
analytic oracle — the *test oracle problem*, endemic to scientific software — a
standard response is a **pseudo-oracle**: run multiple implementations and flag a
fault when they disagree ([Exploratory Metamorphic Testing for Scientific
Software](https://pmc.ncbi.nlm.nih.gov/articles/PMC7252536/);
[metamorphic testing overview](https://en.wikipedia.org/wiki/Metamorphic_testing)).
**Differential testing** compares implementations/versions on shared inputs
([Godefroid et al., *Differential Regression Testing for REST APIs*, ISSTA
2020](https://patricegodefroid.github.io/public_psfiles/issta2020.pdf)), and
**parity testing** puts a common contract between a legacy and a new
implementation so both run the same suite
([ModernizeSpec: Parity Testing](https://modernizespec.dev/techniques/parity-testing/)).
Cross-framework API-equivalence testing (e.g.
[XAMT](https://arxiv.org/pdf/2508.12546) for deep-learning libraries) matches
functionally equivalent APIs and differential-tests them.

> **How the-hangar differs.** The classic setups compare *two peer implementations*
> to find a bug in *either*. Here the comparison is deliberately **asymmetric**:
> Lane A is a designated reference (raw upstream, minimal Hangar code) and Lanes
> B/C are the artifacts under test, so a disagreement localizes to *the wrapper
> layer*, not to "one of them." The pseudo-oracle weakness ("different people
> make the same mistake") is mitigated by the **golden anchors** (§6) that pin
> Lane A to published/upstream values independently. And the metamorphic idea is
> present but narrow: the evt gradient check is a metamorphic relation (analytic
> total = FD of the same model) rather than a second implementation.

**Agentic MDAO / engineering-analysis frameworks.** The closest system in the
literature is Lee, Martins & Çınar, *Aerodynamic Design and Optimization via a
Specialized Agentic Generative AI Framework* (2025), which has a multi-agent LLM
system **generate, execute, and analyze OpenAeroStruct optimization scripts** from
natural language
([paper](https://www.gokcincinar.com/publication/pp-2025-agenticframework/)).
[DUCTILE](https://arxiv.org/pdf/2603.10249) orchestrates engineering analysis in
product-development practice with agentic LLMs.

> **How the-hangar differs.** Those frameworks evaluate the agent on **task
> success / convergence** and on **beating single-shot prompting** — did it
> produce a working, optimized design. They generate *code* (scripts the agent
> writes and runs). the-hangar instead (a) exposes the tool as a **constrained MCP
> surface** the agent composes declaratively (no free-form code generation, so the
> failure surface is the tool schema, not arbitrary Python), and (b) grades on
> **numeric parity to a code-free reference within per-metric tolerances**, across
> a 13-case matrix that includes *coupled and three-tool* problems, not only
> single-wing aero. The question shifts from "can an agent get a good design?" to
> "does the agent, using only the tools, reproduce the upstream tool to 1e-6?"

**LLM/MCP tool-use benchmarks.** A wave of 2025-26 benchmarks grade agents on MCP
tool use — [MCP-Bench](https://arxiv.org/abs/2508.20453) (28 servers, 250 tools,
fuzzy-instruction tool retrieval and multi-hop planning),
[MCPAgentBench](https://arxiv.org/abs/2512.24565),
[MCPToolBench++](https://arxiv.org/pdf/2508.07575), and physics-simulation-specific
[SimulCost](https://arxiv.org/pdf/2603.20253) (cost-aware automation of physics
simulations).

> **How the-hangar differs.** General MCP benchmarks score *trajectory* quality —
> tool-selection accuracy, schema-valid calls, task completion — often with an
> LLM judge, over breadth of domains. the-hangar's agent lane is **narrow and
> physically grounded**: the pass criterion is a numeric tolerance against a
> physics reference, and it is the *same* reference and *same* tolerances the
> non-agent lanes use, so the agent result is directly commensurable with the
> deterministic pipeline. It is less a general agent benchmark than a
> **wrapper-fidelity certificate that happens to also be runnable by an agent**.
> The `friction`/backlog loop treats the agent as an instrument for finding
> tool-surface defects, not only as a subject being scored.

**One-line distinction for the paper.** Prior agentic-MDAO work asks whether an
LLM can *drive* a simulation tool to a good design; MCP benchmarks ask whether an
agent can *call tools well* in general. the-hangar instead certifies that its
tool wrappers are **behaviorally identical to the upstream libraries** — via an
asymmetric three-lane differential test anchored by golden physics values — and
then shows that a *blind* agent, given only the engineering goal and the tools'
own self-description, lands on those same certified numbers. Correctness of the
wrapper and usability by an agent are measured on one ruler.

---

## 10. Code map — where to look

**omd lanes (the paper's parity system)** — `packages/omd/examples/`
- `<case>/shared.py` — parameters + tolerances shared by all lanes (the contract).
- `<case>/lane_a/*.py` — raw upstream reference; `run()` returns a metric dict.
- `<case>/lane_b/**/plan.yaml` — declarative omd plan (modular or assembled).
- `<case>/lane_c/*_open.prompt.md` / `*.prompt.md` — open vs closed agent prompts.
- `tests/test_parity.py` — Lane A vs B suite; `_print_comparison` /
  `_record_comparison` (the print-and-record printer); `conftest.py` isolation.
- `tests/test_parity_lane_c.py` — scripted MCP-tool-surface Lane C suite.
- `agent_eval/eval_lane_c.py` — blind-agent Lane C harness (Claude Agent SDK,
  sandbox, scoring, friction log); `agent_eval/README.md` — cases & tolerances.

**Per-tool lanes (each server's own wrapper)** — `packages/<tool>/examples/`
- e.g. `oas/examples/rectangular_wing/tests/test_parity.py` — `run_lane_a`
  (import) vs `run_lane_b` (JSON tool-call script via
  `hangar.sdk.cli.runner.run_tool`); tolerances in `shared.py`.

**Paper harness** — `paper/`
- `run_lanes.py` — re-runs the pytest suites with `PARITY_RESULTS_JSONL`;
  `KNOWN_GAPS`; writes `lane_parity_meta.json` (git sha + pytest exit).
- `make_tables.py` — renders `lane_parity.{csv,md,tex}`; `CASE_INFO`,
  `AGENT_METRIC_MAP`, sandboxed-evals table.
- `README.md` — full recipes; `results/`, `tables/`.

**Try it**
```bash
# Lane A vs B, and scripted Lane C — the CI parity suites (see the diff tables)
uv run pytest packages/omd/examples/tests/test_parity.py -v -s
uv run pytest packages/omd/examples/tests/test_parity_lane_c.py -v -s -m "not slow"

# A single per-tool wrapper's parity
uv run pytest packages/oas/examples/rectangular_wing/tests/ -v

# Collect the paper's lane-parity table from the same suites
uv run python paper/run_lanes.py --quick && uv run python paper/make_tables.py

# The blind-agent Lane C column (needs Claude Code CLI + claude-agent-sdk)
uv run --with claude-agent-sdk \
    packages/omd/examples/agent_eval/eval_lane_c.py oas_aero_rect --verbose
```

---

*Related docs: [`provenance-and-capture-tool.md`](provenance-and-capture-tool.md)
(how runs are recorded), [`omd-plans-and-studies.md`](omd-plans-and-studies.md)
(what a Lane B plan is), and `paper/README.md` (where these numbers land).*
