---
name: ocp-cli-guide
description: >
  How to run OpenConcept aircraft conceptual design analyses using the
  ocp-cli command-line tool — without needing MCP. Use this skill whenever the
  user asks you to run a mission analysis, configure a propulsion architecture,
  run a parameter sweep, optimize a hybrid-electric design, or do anything with
  OpenConcept from a terminal or script. Covers all three CLI modes: interactive
  (JSON-lines subprocess), one-shot subcommands, and batch script execution.
  Always consult this skill before reaching for Bash commands that involve ocp-cli.
---

# OCP CLI Guide

`ocp-cli` is the command-line interface to the OpenConcept MCP server. It gives
you full access to all OCP tools (load_aircraft_template, run_mission_analysis,
run_parameter_sweep, run_optimization, etc.) without needing an MCP connection.

**Supporting reference files** (read when you need deeper detail):
- `modes.md` — interactive, one-shot, and script mode protocols
- `commands.md` — all tools and convenience commands with parameters
- `provenance.md` — session tracking, decision logging, DAG export
- `examples/` — complete workflow recipes by analysis type

## Prerequisites

```bash
# From the workspace root (installs all packages):
uv sync

# Or install the OCP package directly:
uv pip install -e packages/ocp/

# Verify:
ocp-cli list-tools
```

If `command not found`, the virtualenv is not activated or the package was not
installed. You can also invoke via `python -m hangar.ocp.cli <args>`.

## Global flags come BEFORE the subcommand

`--pretty`, `--workspace`, and `--save-to` are parser-level flags. They must
appear **before** the subcommand name, not after it:

```bash
# Correct:
ocp-cli --pretty run-mission-analysis

# WRONG — argparse will reject this:
ocp-cli run-mission-analysis --pretty
```

| Flag | Effect |
|------|--------|
| `--pretty` | Indent JSON output for readability |
| `--workspace NAME` | Namespace for one-shot state file (default: "default") |
| `--save-to FILE` | Write JSON response to FILE instead of stdout |

## Workflow order matters

OCP requires a specific setup sequence. Tools will error if prerequisites
are not met:

```
1. load_aircraft_template / define_aircraft  — must be called first
2. set_propulsion_architecture               — must be called second
3. configure_mission                         — optional (uses defaults)
4. run_mission_analysis / run_parameter_sweep / run_optimization
```

Calling `run_mission_analysis` without an aircraft or architecture set will
produce a `USER_INPUT_ERROR`.

## Choosing a mode

| Situation | Best mode | Details |
|-----------|-----------|---------|
| Multiple analyses or architecture comparison | **Interactive** | In-memory state, fastest. See `modes.md` |
| Quick one-off mission analysis from terminal | **One-shot** | One subcommand per tool call. See `modes.md` |
| Reproducible workflow to hand off / re-run | **Script** | JSON file, single process. See `modes.md` |

## Quick reference — key parameter defaults

```
Templates: caravan, b738, kingair, tbm850
Architectures: turboprop, twin_turboprop, series_hybrid, twin_series_hybrid, twin_turbofan

Mission defaults:
  cruise_altitude = 18000 ft
  mission_range   = 250 NM
  climb_vs        = 850 ft/min
  cruise_Ueas     = 129 kn
  num_nodes       = 11         (must be ODD: 3, 5, 7, 11, 21, ...)
  mission_type    = "full"     (includes balanced-field takeoff)
```

## Critical constraints

- **num_nodes must be ODD** (3, 5, 7, 11, 21, ...) for Simpson's rule
  integration. Passing an even value raises an error.
- **Hybrid architectures** require battery weight, motor rating, and
  generator rating in the aircraft data. Use `set_propulsion_architecture`
  with the override parameters or ensure the template includes them
  (kingair template is hybrid-ready).
- **Architecture changes invalidate the cache** — the OpenMDAO problem is
  rebuilt when the architecture changes.
- **descent_vs is given as a positive number** — the tool negates it
  internally.

## Error handling

All responses follow the same envelope:

```json
{"ok": true,  "result": { ... }}
{"ok": false, "error": {"code": "USER_INPUT_ERROR", "message": "..."}}
```

| Code | Cause | Fix |
|------|-------|-----|
| `USER_INPUT_ERROR` | Bad params, missing aircraft/architecture, even num_nodes | Check workflow order and parameter values |
| `SOLVER_CONVERGENCE_ERROR` | OpenMDAO Newton solver failed | Reduce mission range, adjust speeds, check MTOW |
| `INTERNAL_ERROR` | Bug in OCP code | Surface to the user; do not auto-retry |

## Available tools

Run `ocp-cli list-tools` for the complete, up-to-date list. Key groups:

- **Configuration:** `list_aircraft_templates`, `load_aircraft_template`, `define_aircraft`, `set_propulsion_architecture`, `configure_mission`
- **Analysis:** `run_mission_analysis`, `run_parameter_sweep`, `run_optimization`, `reset`
- **Observability:** `get_run`, `get_detailed_results`, `get_last_logs`, `pin_run`, `unpin_run`, `configure_session`, `set_requirements`
- **Artifacts:** `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact`
- **Provenance:** `start_session`, `log_decision`, `export_session_graph`

See `commands.md` for parameters and `provenance.md` for the provenance workflow.
