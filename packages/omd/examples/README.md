# omd Examples: Three-Lane Comparison

Each example runs the same analysis three different ways:

| Lane | Approach | Files |
|------|----------|-------|
| **Lane A** | Direct OpenMDAO/OAS/OCP scripts (importable `run()` functions) | `lane_a/*.py` |
| **Lane B** | omd plan YAML + `omd-cli` (pre-built reference plans) | `lane_b/*/` plan directories |
| **Lane C** | Agent task prompts (agent creates the plan from scratch) | `lane_c/*.prompt.md` |

Lane C prompts describe *what* to analyze, not *how*. Each example has
two flavors:

- `lane_c/<name>.prompt.md` -- guided: names the component type, config
  keys, and CLI deliverables. For a human (or agent) driving `omd-cli`
  with the `/omd-cli-guide` skill available.
- `lane_c/<name>_open.prompt.md` -- open: states the engineering goal
  and the physical inputs only. It deliberately names no factory, slot
  provider, parameter key, or tool-call sequence; the agent must work
  out the workflow from the server's own affordances (tool
  descriptions, `omd://reference`). The blind agent eval uses these.

The agent's output should match Lane A and Lane B.

## Examples

| Problem | Type | Description |
|---------|------|-------------|
| `paraboloid/` | Smoke test | Trivial `f(x,y)` analysis + optimization |
| `oas_aero_rect/` | Aero-only | Rectangular wing VLM analysis + twist optimization |
| `oas_aerostruct_rect/` | Coupled | Aerostructural analysis (aero + tube FEM) |
| `ocp_caravan_basic/` | Mission | Caravan 3-phase mission (climb/cruise/descent) |
| `ocp_caravan_full/` | Mission | Caravan full mission with takeoff |
| `ocp_hybrid_twin/` | Mission | King Air series-hybrid electric mission |
| `oas_ocp_combined/` | Composite | OAS wing + OCP mission side-by-side (uncoupled) |
| `ocp_oas_coupled/` | Slot-coupled | OCP mission with OAS VLM drag via slot system |
| `evt_native_sizing/` | Sizing | Native (gradient-capable) eVTOL MTOW closure sizing |
| `avy_single_aisle/` | Sizing | Aviary single-aisle coupled sizing + mission (subprocess into `.venv-avy`) |
| `avy_bwb/` | Sizing | Aviary blended-wing-body fixed-profile sizing |
| `avy_oas_wing/` | Tight-coupled | OAS wingbox wing mass *inside* Aviary sizing (external subsystem) |
| `oas_avy_wing_mass/` | Loose-coupled | OAS structural mass drives Aviary sizing across the venv boundary (`override_inputs`) |

## Prerequisites

```bash
cd /path/to/the-hangar
uv sync
uv run omd-cli --help
```

## Quick Start

```bash
# Lane A: direct script
uv run python packages/omd/examples/paraboloid/lane_a/analysis.py

# Lane B: omd plan pipeline
omd-cli run packages/omd/examples/paraboloid/lane_b/analysis/plan.yaml

# Lane C: paste task prompt into Claude Code
claude
# Then paste the contents of lane_c/analysis.prompt.md
```

## Parity Tests

Run with `-s` to see comparison tables of Lane A vs Lane B results:

```bash
uv run pytest packages/omd/examples/tests/ -v -s
```

Lane C parity is covered in two stages:

1. **Scripted (CI)** -- `tests/test_parity_lane_c.py` drives the same
   MCP tool functions an agent uses (plan_init -> plan_add_component ->
   assemble_plan -> validate_plan -> run_plan -> get_results) in
   process and compares against Lane A. Covers every parity case except
   `ocp_pyc_coupled` (a documented Lane B/C gap -- see that example's
   TODO.md) and the slow Aviary cases beyond `avy_single_aisle`
   (`avy_bwb`, `avy_oas_wing`, `oas_avy_wing_mass` ship closed Lane C
   prompts only).
2. **Agent eval (manual / automatable)** -- `agent_eval/eval_lane_c.py`
   launches a blind agent through the Claude Agent SDK, restricted to
   the omd MCP tools, and scores its reported metrics against Lane A.
   See `agent_eval/README.md`.

## Data Artifacts

All omd runtime data is stored in `hangar_data/omd/`:
- `analysis.db` -- provenance and run case data (SQLite)
- `plans/{plan-id}/v{N}.yaml` -- assembled plan versions
- `recordings/{run-id}.sql` -- OpenMDAO recorder output (inspectable with CaseReader)
