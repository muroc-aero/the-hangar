---
name: pyc-cli-guide
description: >
  How to run pyCycle gas turbine cycle analyses using the pyc-cli command-line
  tool -- without needing MCP. Use this skill whenever the user asks you to run
  a pyCycle analysis, create an engine, run a design point, evaluate off-design
  performance, or do anything with pyCycle from a terminal or script. Covers all
  three CLI modes: interactive (JSON-lines subprocess), one-shot subcommands,
  and batch script execution. Always consult this skill before reaching for Bash
  commands that involve pyc-cli.
---

# PYC CLI Guide

`pyc-cli` is the command-line interface to the pyCycle MCP server. It gives you
full access to all pyCycle tools (create_engine, run_design_point, etc.)
without needing an MCP connection.

If instead the user wants to drive the pyCycle tools through an MCP
connection (e.g. `mcp__pyCycle__run_design_point`), see the
`hangar-mcp-guide` skill - the tool surface and parameters are
identical between MCP and CLI; only the invocation shape and the
session lifecycle differ.

**Supporting reference files** (read when you need deeper detail):
- `modes.md` -- interactive, one-shot, and script mode protocols
- `commands.md` -- all tools and convenience commands with parameters
- `provenance.md` -- session tracking, decision logging, DAG export
- `examples/` -- complete workflow recipes by analysis type

## Prerequisites

```bash
# Install the package (pyc-cli is a console_scripts entry point):
uv pip install -e packages/pyc   # or: pip install -e packages/pyc

# Verify:
pyc-cli list-tools
```

If `command not found`, the virtualenv is not activated or the package was not
installed. You can also invoke via `uv run pyc-cli <args>`.

## Global flags come BEFORE the subcommand

`--pretty`, `--workspace`, and `--save-to` are parser-level flags. They must
appear **before** the subcommand name, not after it:

```bash
# Correct:
pyc-cli --pretty run-design-point --engine-name tj1 --alt 0 --MN 0.000001

# WRONG -- argparse will reject this:
pyc-cli run-design-point --pretty --engine-name tj1 --alt 0
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
function signature. So `Fn_target` -> `--Fn-target`, `T4_target` ->
`--T4-target`, `MN` -> `--MN`. When in doubt, run `pyc-cli <subcommand> --help`.

## Choosing a mode

| Situation | Best mode | Details |
|-----------|-----------|---------|
| Multiple related analyses in one session | **Interactive** | In-memory state, fastest. See `modes.md` |
| Quick one-off check from the terminal | **One-shot** | One subcommand per tool call. See `modes.md` |
| Reproducible workflow to hand off / re-run | **Script** | JSON file, single process. See `modes.md` |

## Quick reference -- key parameter defaults

```
archetype="turbojet"   # only archetype currently available

# Compressor / turbine defaults (turbojet)
comp_PR=13.5           # compressor pressure ratio
comp_eff=0.83          # compressor isentropic efficiency
turb_eff=0.86          # turbine isentropic efficiency
Nmech=8070             # shaft speed (rpm)
burner_dPqP=0.03       # combustor pressure loss fraction
nozz_Cv=0.99           # nozzle velocity coefficient
thermo_method="TABULAR"  # fast; use "CEA" for higher fidelity

# Design point defaults
alt=0.0        ft      # sea-level static
MN=0.000001            # near-zero Mach (NOT exactly 0)
Fn_target=11800  lbf   # design thrust
T4_target=2370   degR  # turbine inlet temperature (limit ~3600 degR)
```

## Mandatory workflow order

```
0. start_session        -- begin provenance session
1. create_engine        -- define engine from archetype + parameters
   log_decision         -- record archetype/parameter choices
2. run_design_point     -- size engine at design conditions (MUST precede off-design)
   log_decision         -- interpret design results
3. run_off_design       -- evaluate at off-design flight conditions
   log_decision         -- interpret off-design results
4. visualize            -- generate plots for any analysis run
5. export_session_graph -- save provenance DAG at workflow end
6. reset (optional)     -- clear state between unrelated experiments
```

**Critical**: `run_design_point` MUST be called before `run_off_design` -- the
design point sizes the engine geometry (areas, map scalars) which is held fixed
during off-design analysis.

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
| `USER_INPUT_ERROR` | Bad param values, missing engine, bad JSON | Check parameter values and engine existence |
| `SOLVER_CONVERGENCE_ERROR` | Newton solver failed to converge | Adjust initial guesses or flight conditions |
| `INTERNAL_ERROR` | Bug in pyCycle/MCP code | Surface to the user; do not auto-retry |

## Conclude the study (record_conclusion)

Close every requirements-driven study with `record_conclusion` once a run
answers the question. It ties the chosen run to the requirements you set with
`set_requirements` / `configure_session` and records a verdict:

```bash
pyc-cli set_requirements --requirements '[{"path":"performance.TSFC","operator":"<","target":0.8,"label":"max_TSFC"}]'
# ... run the design point / off-design that answers the study ...
pyc-cli record_conclusion --run_id <run_id> --narrative "design point meets TSFC target"
```

The per-requirement verdicts are auto-derived by evaluating each persisted
requirement against the chosen run's results, so they cannot drift from the
numbers; you supply only the run and a short narrative. The overall verdict is
`meets` / `fails` / `partial` / `open`.

This is the step that flips the **Concluding** stage in the range-safety
dashboard to populated. To watch a study fill in live, start the dashboard once
and open it on `sdk:<session_id>` as soon as the session starts:

```bash
uv run uvicorn hangar.range_safety.dashboard.app:app --port 8011
explorer.exe "http://localhost:8011/"   # WSL: then pick sdk:<session_id>
```

Requirements populate Gather Requirements, runs populate Executing,
`log_decision` calls populate Verifying, and `record_conclusion` populates
Concluding. Without persisted requirements the conclusion has nothing to judge,
so set them at the start.

## Available tools

Run `pyc-cli list-tools` for the complete, up-to-date list. Key groups:

- **Analysis:** `create_engine`, `run_design_point`, `run_off_design`, `reset`
- **Visualization:** `visualize`
- **Observability:** `get_run`, `get_last_logs`, `pin_run`, `unpin_run`, `configure_session`, `set_requirements`, `record_conclusion`
- **Artifacts:** `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact`
- **Provenance:** `start_session`, `log_decision`, `link_cross_tool_result`, `export_session_graph`
- **Convenience commands:** `list-tools`, `list-runs`, `show`, `plot`, `viewer`

See `commands.md` for parameters and `provenance.md` for the provenance workflow.
