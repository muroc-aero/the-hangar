# evt_native_sizing: Native eVTOL MTOW Sizing (Three-Lane)

Sizes an Archer Midnight lift+cruise eVTOL three ways through the **native
OpenMDAO formulation of evtolpy** (`hangar.omd.evt` / the `evt/Sizing`
factory). All three lanes run the MTOW fixed-point closure to a sized takeoff
mass on the same vendored AIAA SciTech 2026 config
(`archer-midnight-1500-30`), and must agree to round-off.

| Lane | Approach | Files |
|------|----------|-------|
| **Lane A** | Native model as a plain OpenMDAO library (`build_problem`) | `lane_a/sizing.py` |
| **Lane B** | omd plan YAML + `omd-cli` (the `evt/Sizing` factory) | `lane_b/sizing/plan.yaml` |
| **Lane C** | Agent task prompt (agent authors the plan via omd MCP tools) | `lane_c/sizing.prompt.md` |

## What's native about it

The `evt/Sizing` factory builds an idiomatic OpenMDAO model -- five
explicit components with **complex-step partials** and a real Newton
MTOW-closure solver -- rather than wrapping evtolpy as a finite-difference
black box. It reproduces upstream evtolpy to floating point (see the parity
suite `packages/evt/examples/native_parity/`) while adding the capability the
black box lacks: **analytic total derivatives through the sizing loop**.

Lane A demonstrates that headline capability directly: `run_gradient()`
computes the analytic `d(sized_MTOW)/d(payload)` through the implicit closure
and checks it against a finite difference (they agree to a few parts in 1e4).
The legacy black box is still available as `evt/SizingFD` for configs that
exercise a non-smooth branch the gradient path cannot cross.

## Quick Start

```bash
cd /path/to/the-hangar

# Lane A: direct native library script
uv run python packages/omd/examples/evt_native_sizing/lane_a/sizing.py

# Lane B: omd plan pipeline (run from the repo root so config_dir resolves)
omd-cli run packages/omd/examples/evt_native_sizing/lane_b/sizing/plan.yaml --mode analysis

# Lane C: paste lane_c/sizing.prompt.md into Claude Code
```

## Expected Results

| Metric | Value |
|--------|-------|
| `sized_mtow_kg` | ~2019.5 |
| `total_mission_energy_kw_hr` | ~65.95 |
| `peak_power_kw` | ~846.5 |

## Parity Tests

```bash
# Lane A vs Lane B (plan pipeline)
uv run pytest packages/omd/examples/tests/test_parity.py -k EvtNative -v -s

# Lane C scripted (MCP tool surface) vs Lane A
uv run pytest packages/omd/examples/tests/test_parity_lane_c.py -k EvtNative -v -s
```
