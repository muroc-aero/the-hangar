---
name: oas-cli-guide
description: >
  How to run OpenAeroStruct (OAS) analyses using the
  oas-cli command-line tool — without needing MCP. Use this skill whenever the
  user asks you to run an OAS analysis, compute a drag polar, run a wing
  optimization, or do anything with OpenAeroStruct from a terminal or script.
  Covers all three CLI modes: interactive (JSON-lines subprocess), one-shot
  subcommands, and batch script execution. Always consult this skill before
  reaching for Bash commands that involve oas-cli.
---

# OAS CLI Guide

`oas-cli` is the command-line interface to the OAS MCP server. It gives you
full access to all OAS tools (create_surface, run_aero_analysis, etc.)
without needing an MCP connection.

**Supporting reference files** (read when you need deeper detail):
- `modes.md` — interactive, one-shot, and script mode protocols
- `commands.md` — all tools and convenience commands with parameters
- `provenance.md` — session tracking, decision logging, DAG export
- `examples/` — complete workflow recipes by analysis type

## Prerequisites

```bash
# Install the package (oas-cli is a console_scripts entry point):
uv pip install -e ".[mcp]"   # or: pip install -e ".[mcp]"

# Verify:
oas-cli list-tools
```

If `command not found`, the virtualenv is not activated or the package was not
installed. You can also invoke via `python -m oas_mcp.cli <args>`.

## Global flags come BEFORE the subcommand

`--pretty`, `--workspace`, and `--save-to` are parser-level flags. They must
appear **before** the subcommand name, not after it:

```bash
# Correct:
oas-cli --pretty run-aero-analysis --surfaces '["wing"]' --alpha 5

# WRONG — argparse will reject this:
oas-cli run-aero-analysis --pretty --surfaces '["wing"]' --alpha 5
```

| Flag | Effect |
|------|--------|
| `--pretty` | Indent JSON output for readability |
| `--workspace NAME` | Namespace for one-shot state file (default: "default") |
| `--save-to FILE` | Write JSON response to FILE instead of stdout |

**Important**: `--save-to` writes the full JSON response to a file. This is
different from the `visualize` tool's `--output` parameter, which controls the
visualization rendering mode (`inline`/`file`/`url`). Don't confuse the two.

## Flag names preserve Python parameter case

Only underscores become hyphens; capitalisation is kept verbatim from the
function signature. So `Mach_number` -> `--Mach-number`, `CD0` -> `--CD0`,
`CL0` -> `--CL0`. When in doubt, run `oas-cli <subcommand> --help`.

## Choosing a mode

| Situation | Best mode | Details |
|-----------|-----------|---------|
| Multiple related analyses in one session | **Interactive** | In-memory state, fastest. See `modes.md` |
| Quick one-off check from the terminal | **One-shot** | One subcommand per tool call. See `modes.md` |
| Reproducible workflow to hand off / re-run | **Script** | JSON file, single process. See `modes.md` |

## Quick reference — key parameter defaults

```
velocity=248.136 m/s   # cruise
Mach_number=0.84
density=0.38 kg/m^3
reynolds_number=1e6    # REQUIRED — server rejects if omitted
alpha=5.0 degrees

num_x=2, num_y=7       # fast mesh (num_y must be ODD)
wing_type="CRM"        # realistic transport wing
symmetry=True          # model half-span
```

## Error handling

All responses follow the same envelope:

```json
{"ok": true,  "result": { ... }}
{"ok": false, "error": {"code": "USER_INPUT_ERROR", "message": "..."}}
```

**Important**: Most tools return `result` as a **dict**, but `visualize`
returns `result` as a **list** (`[metadata_dict]` or `[metadata_dict,
image_dict]`). Always check the type before accessing fields.

| Code | Cause | Fix |
|------|-------|-----|
| `USER_INPUT_ERROR` | Bad param values, missing surface, bad JSON | Check parameter values and surface existence |
| `SOLVER_CONVERGENCE_ERROR` | OpenMDAO solver failed | Coarser mesh (`num_y=5`), lower Mach, adjust alpha |
| `CACHE_EVICTED_ERROR` | Cached problem was cleared | Call `create_surface` again, then rerun |
| `INTERNAL_ERROR` | Bug in OAS/MCP code | Surface to the user; do not auto-retry |

## Structural tools — required surface parameters

If you need `run_aerostruct_analysis` or an aerostruct optimization, the
surface **must** include:

- `fem_model_type`: `"tube"` or `"wingbox"`
- `E`, `G`, `yield_stress`, `mrho` (material properties)
- For tube: `thickness_cp` (list of control-point values in metres)
- For wingbox: `spar_thickness_cp` and `skin_thickness_cp`

Omitting these will produce a `USER_INPUT_ERROR`.

For composite laminates, also set `use_composite=True` with `ply_angles`,
`ply_fractions`, and composite moduli (`E1`, `E2`, `nu12`, `G12`) plus
strength properties. See `commands.md` for the full parameter list.

## Available tools

Run `oas-cli list-tools` for the complete, up-to-date list. Key groups:

- **Analysis:** `create_surface`, `run_aero_analysis`, `run_aerostruct_analysis`, `compute_drag_polar`, `compute_stability_derivatives`, `run_optimization`, `reset`
- **Observability:** `visualize`, `get_run`, `get_detailed_results`, `get_n2_html`, `get_last_logs`, `pin_run`, `unpin_run`, `configure_session`, `set_requirements`
- **Artifacts:** `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact`
- **Provenance:** `start_session`, `log_decision`, `export_session_graph`
- **Convenience commands:** `list-tools`, `list-runs`, `show`, `plot`, `viewer`

See `commands.md` for parameters and `provenance.md` for the provenance workflow.
