---
name: avy-cli-guide
description: >
  How to run NASA Aviary aircraft sizing and mission optimization using the
  avy-cli command-line tool -- without needing MCP. Use this skill whenever
  the user asks you to size an aircraft, run an Aviary mission, fly an
  off-design mission, generate a payload-range diagram, or do anything with
  Aviary from a terminal or script. Covers all three CLI modes: interactive
  (JSON-lines subprocess), one-shot subcommands, and batch script execution.
  Always consult this skill before reaching for Bash commands that involve
  avy-cli.
---

# AVY CLI Guide

`avy-cli` is the command-line interface to the Aviary MCP server. It gives you
full access to all Aviary tools (load_aircraft_template, run_sizing, etc.)
without needing an MCP connection.

If instead the user wants to drive the Aviary tools through an MCP connection
(e.g. `mcp__Aviary__run_sizing`), see the `hangar-mcp-guide` skill -- the tool
surface and parameters are identical between MCP and CLI; only the invocation
shape and the session lifecycle differ.

**Supporting reference files** (read when you need deeper detail):
- `modes.md` -- interactive, one-shot, and script mode protocols
- `commands.md` -- all tools and convenience commands with parameters
- `provenance.md` -- session tracking, decision logging, DAG export
- `examples/` -- complete workflow recipes by analysis type

## Prerequisites

```bash
# Install the workspace packages (avy-cli is a console_scripts entry point
# from packages/avy; aviary is an ordinary dependency installed by the dev
# setup into the single workspace venv):
bash scripts/dev-setup.sh

# Verify:
avy-cli list-tools
```

If `command not found`, the virtualenv is not activated or the packages were
not installed. `uv run avy-cli <args>` works without activating the venv.

## Global flags come BEFORE the subcommand

`--pretty`, `--workspace`, and `--save-to` are parser-level flags. They must
appear **before** the subcommand name, not after it:

```bash
# Correct:
avy-cli --pretty run-sizing --aircraft-name ac1 --optimizer SLSQP

# WRONG -- argparse will reject this:
avy-cli run-sizing --pretty --aircraft-name ac1
```

| Flag | Effect |
|------|--------|
| `--pretty` | Indent JSON output for readability |
| `--workspace NAME` | Namespace for one-shot state file (default: "default") |
| `--save-to FILE` | Write JSON response to FILE instead of stdout |

## Flag names preserve Python parameter case

Only underscores become hyphens. So `target_range_nm` -> `--target-range-nm`,
`mission_gross_mass_lbm` -> `--mission-gross-mass-lbm`. When in doubt, run
`avy-cli <subcommand> --help`.

Dict-valued parameters (`overrides`, `phase_options`) are passed as JSON
strings:

```bash
avy-cli define-aircraft \
    --overrides '{"aircraft:wing:aspect_ratio": 13.0}'
```

## Choosing a mode

| Situation | Best mode | Details |
|-----------|-----------|---------|
| Multiple related runs in one session | **Interactive** | In-memory state, one process. See `modes.md` |
| Quick one-off sizing from the terminal | **One-shot** | One subcommand per tool call. See `modes.md` |
| Reproducible workflow to hand off / re-run | **Script** | JSON file, single process. See `modes.md` |

## The 60-second sizing run

```bash
avy-cli load-aircraft-template --template advanced_single_aisle
avy-cli --pretty run-sizing
```

Expect ~20 s of wall-clock for the default 3-phase energy_state mission. The
response is a versioned envelope; the headline numbers are under
`result.results.performance` (`gross_mass_lbm`, `total_fuel_mass_lbm`,
`range_nmi`, `final_time_min`).

## Critical constraints (same as the MCP server)

- **EVERY run is an optimizer run.** There is no evaluate-only path; that is
  why the tool is `run_sizing`, not `run_mission_analysis`.
- **Optimizer non-convergence does NOT raise.** Always check
  `result.validation.passed` (the `optimizer.success` finding) before
  trusting numbers -- a failed run returns the last iterate.
- Default optimizer SLSQP. IPOPT/SNOPT need pyoptsparse and are rejected
  with instructions when it is absent.
- Deck variable names use the `aircraft:wing:span` hierarchy and are
  validated against Aviary's metadata; typos error with close matches.
- Only energy_state missions run today; GASP 2DOF templates are listed but
  rejected by analysis tools.
- `run_off_design` / `run_payload_range` fly from the session's last
  converged sizing of the aircraft when its deck/overrides/mission/
  subsystems/optimizer settings still match (see
  `results.design_point.sizing_reused`); otherwise they re-run the sizing
  internally first (~2x / ~3x run_sizing wall-clock). `run_payload_range`
  consumes the cached sizing (upstream widens its cruise bounds in place).

## Common pitfalls

| Symptom | Cause / fix |
|---------|-------------|
| `RuntimeError: The 'aviary' package is not installed` | Workspace not installed. Run `bash scripts/dev-setup.sh` (or `uv sync`), then `uv run avy-cli` |
| `validation.passed` false, `optimizer.success` failed | Optimizer did not converge -- raise `--max-iter`, simplify the mission, or check overrides |
| `Unknown Aviary variable ...` | Typo in an override name -- the error lists close matches |
| `... uses a '2DOF' deck` | GASP templates are not runnable yet; use a FLOPS/energy_state template |
| `mission_type='min_fuel' requires mission_range_nm` | min_fuel flies a FIXED range; pass `--mission-range-nm` |
