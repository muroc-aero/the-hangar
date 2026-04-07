# omd Examples: Three-Lane Comparison

Each example runs the same analysis three different ways:

| Lane | Approach | Files |
|------|----------|-------|
| **Lane A** | Direct OpenMDAO/OAS/OCP scripts (importable `run()` functions) | `lane_a/*.py` |
| **Lane B** | omd plan YAML + `omd-cli` (pre-built reference plans) | `lane_b/*/` plan directories |
| **Lane C** | Agent task prompts (agent creates the plan from scratch) | `lane_c/*.prompt.md` |

Lane C prompts describe *what* to analyze, not *how*. The agent uses
`/omd-cli-guide` or `omd-cli --help` to learn how to author plan YAML
files, creates the plan, runs it via `omd-cli`, and reports results.
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

## Data Artifacts

All omd runtime data is stored in `hangar_data/omd/`:
- `analysis.db` -- provenance and run case data (SQLite)
- `plans/{plan-id}/v{N}.yaml` -- assembled plan versions
- `recordings/{run-id}.sql` -- OpenMDAO recorder output (inspectable with CaseReader)
