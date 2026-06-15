---
name: evt-cli-guide
description: >
  How to run evtolpy electric-VTOL sizing and mission-energy analyses using the
  evt-cli command-line tool -- without needing MCP. Use this skill whenever the
  user asks you to run an eVTOL analysis, load a vehicle template, run a mission
  energy/power/mass analysis, converge MTOW (sizing), or sweep a parameter from a
  terminal or script. Covers all three CLI modes: interactive (JSON-lines
  subprocess), one-shot subcommands, and batch script execution. Always consult
  this skill before reaching for Bash commands that involve evt-cli.
---

# EVT CLI Guide

`evt-cli` is the command-line interface to the evt (evtolpy) MCP server. It
gives you full access to all evt tools (load_vehicle_template,
run_mission_analysis, run_sizing, etc.) without needing an MCP connection.

If instead the user wants to drive the evt tools through an MCP connection
(e.g. `mcp__evt__run_mission_analysis`), the tool surface and parameters are
identical between MCP and CLI; only the invocation shape and the session
lifecycle differ.

**Supporting reference files** (read when you need deeper detail):
- `modes.md` -- interactive, one-shot, and script mode protocols
- `commands.md` -- all tools and convenience commands with parameters
- `provenance.md` -- session tracking, decision logging, DAG export
- `examples/` -- complete workflow recipes by analysis type

## Prerequisites

```bash
# Install the package (evt-cli is a console_scripts entry point):
uv pip install -e packages/evt   # or: pip install -e packages/evt

# Verify:
evt-cli list-tools
```

evtolpy is an upstream dependency with no packaging metadata; `bash
scripts/dev-setup.sh` clones and patches it (`upstream/evtolpy`). If `evt-cli`
reports `command not found`, the virtualenv is not activated or the package was
not installed. You can also invoke via `uv run evt-cli <args>`.

## Global flags come BEFORE the subcommand

`--pretty`, `--workspace`, and `--save-to` are parser-level flags. They must
appear **before** the subcommand name, not after it:

```bash
# Correct:
evt-cli --pretty run-mission-analysis

# WRONG -- argparse will reject this:
evt-cli run-mission-analysis --pretty
```

| Flag | Effect |
|------|--------|
| `--pretty` | Indent JSON output for readability |
| `--workspace NAME` | Namespace for one-shot state file (default: "default") |
| `--save-to FILE` | Write JSON response to FILE instead of stdout |

## Flag names preserve Python parameter case

Only underscores become hyphens; capitalisation is kept verbatim from the
function signature. When in doubt, run `evt-cli <subcommand> --help`.

The section setters (`define-vehicle`, `set-power`, etc.) and the sweep take a
`--params` / `--values` JSON argument -- pass a JSON object/array string:

```bash
evt-cli set-power --params '{"batt_spec_energy_w_h_p_kg": 280.0}'
evt-cli run-parameter-sweep --param power.batt_spec_energy_w_h_p_kg \
        --values '[200, 260, 320]' --metric sized_mtow_kg
```

## Choosing a mode

| Situation | Best mode | Details |
|-----------|-----------|---------|
| Multiple related analyses in one session | **Interactive** | In-memory config, fastest. See `modes.md` |
| Quick one-off check from the terminal | **One-shot** | One subcommand per tool call. See `modes.md` |
| Reproducible workflow to hand off / re-run | **Script** | JSON file, single process. See `modes.md` |

## Mandatory workflow order

```
0. start_session            -- begin provenance session
1. load_vehicle_template    -- seed a COMPLETE config from a baseline
   log_decision             -- record vehicle choice (architecture_choice)
2. define_vehicle / configure_mission / set_power / set_propulsion / set_environment
                            -- (optional) override individual parameters
3. run_mission_analysis     -- energy, power, and mass tables at the configured MTOW
   run_sizing               -- converge MTOW (separate iteration)
   log_decision             -- interpret results (result_interpretation)
4. run_parameter_sweep      -- (optional) 1-D sensitivity study
   visualize                -- generate plots for any analysis run
5. export_session_graph     -- save provenance DAG at workflow end
6. reset (optional)         -- clear config between unrelated experiments
```

**Critical**: a config must be **complete** (all five sections) before any
analysis. `load_vehicle_template` seeds a complete baseline; the setters only
override individual keys. evtolpy **silently ignores unrecognized config keys**,
so the setters REJECT unknown parameter names (with a typo suggestion) -- use
the exact schema keys (see `commands.md` or the `evt://reference` resource).

`run_mission_analysis` reads the aircraft at the **as-configured MTOW** (no
sizing). `run_sizing` runs the MTOW fixed-point iteration. They are separate
tools with different result payloads.

## Quick reference -- key facts

```
template = "test_all"   # lift+cruise eVTOL reference (the only shipped template;
                        # 6 lift + 6 tilt rotors + 1 pusher, 3175 kg initial MTOW)

# Headline numbers at the test_all baseline (golden, pinned at the evtolpy ref):
#   cruise segment energy       = 124.289885 kW*hr
#   total mission energy        = 166.77776  kW*hr
#   sized MTOW                   = 4076.0876  kg (37 iterations)

# Units are baked into key/attribute names -- never convert implicitly:
#   _kg  _kw  _kw_hr  _m  _m2  _m_p_s  _s
```

## Error handling

All responses follow the same envelope:

```json
{"ok": true,  "result": { ... }}
{"ok": false, "error": {"code": "...", "message": "..."}}
```

**Important**: most tools return `result` as a **dict** (a versioned envelope
with `results`/`validation`/`telemetry`/`run_id`), but `visualize` returns
`result` as a **list** (`[metadata_dict]` or `[metadata_dict, image_dict]`).
Always check the type before accessing fields.

| Cause | Fix |
|-------|-----|
| Unknown config key | The message names the rejected key and suggests the nearest valid one -- use the exact schema key |
| Incomplete config (`load_vehicle_template` not called) | Load a template first; the setters only override |
| Diverging MTOW iteration | Inputs are likely self-inconsistent (wingspan, rotor count/diameter, battery/EPU scaling, mission energy) |

Always check the `validation` block before trusting numbers: the `mtow.converged`
finding is load-bearing -- a non-converged but returned sizing result is flagged
as an `error` finding, never a silent pass.

## Conclude the study (record_conclusion)

Close every requirements-driven study with `record_conclusion` once a run
answers the question. Set requirements first so the verdict has something to
judge:

```bash
evt-cli set_requirements --requirements '[{"label":"max_energy","path":"totals.total_mission_energy_kw_hr","operator":"<","value":170}]'
# ... run the mission analysis / sizing that answers the study ...
evt-cli record_conclusion --run_id <run_id> --narrative "mission energy within budget at test_all baseline"
```

`path` uses dot notation into `results` (e.g. `totals.total_mission_energy_kw_hr`,
`sized_mtow_kg`, `propulsion.disk_loading_kg_p_m2`). The threshold key is `value`,
not `target`.

## Available tools

Run `evt-cli list-tools` for the complete, up-to-date list. Key groups:

- **Vehicle config:** `list_vehicle_templates`, `load_vehicle_template`, `define_vehicle`, `set_propulsion`, `set_power`, `set_environment`, `configure_mission`
- **Analysis:** `run_mission_analysis`, `run_sizing`, `run_parameter_sweep`, `reset`
- **Visualization:** `visualize`
- **Observability:** `get_run`, `get_detailed_results`, `get_last_logs`, `pin_run`, `unpin_run`, `configure_session`, `set_requirements`, `record_conclusion`
- **Artifacts:** `list_artifacts`, `get_artifact`, `get_artifact_summary`, `delete_artifact`
- **Provenance:** `start_session`, `log_decision`, `link_cross_tool_result`, `export_session_graph`
- **Convenience commands:** `list-tools`, `list-runs`, `show`, `plot`, `viewer`

See `commands.md` for parameters and `provenance.md` for the provenance workflow.
