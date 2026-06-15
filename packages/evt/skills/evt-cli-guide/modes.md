# CLI Modes

`evt-cli` supports three execution modes. All use the same tool registry and
response envelope format.

## Mode 1 -- Interactive (JSON-lines subprocess)

Spawn a single long-lived process. Write JSON commands to stdin, read JSON
responses from stdout -- one object per line.

```bash
evt-cli interactive
```

### Protocol

Send one JSON object per line:

```json
{"tool": "load_vehicle_template", "args": {"template": "test_all"}}
```

Receive one JSON object per line:

```json
{"ok": true, "result": {"template": "test_all", "sections": [...], ...}}
```

### Python example

```python
import subprocess, json

proc = subprocess.Popen(
    ["evt-cli", "interactive"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    text=True, bufsize=1,
)

def call(tool, **args):
    proc.stdin.write(json.dumps({"tool": tool, "args": args}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())["result"]

# Workflow
call("start_session", notes="eVTOL mission energy study")
call("load_vehicle_template", template="test_all")
call("set_power", params={"batt_spec_energy_w_h_p_kg": 280.0})
mission = call("run_mission_analysis")
e = mission["results"]["totals"]["total_mission_energy_kw_hr"]
print(f"total mission energy = {e:.3f} kW*hr")
sizing = call("run_sizing")
print(f"sized MTOW = {sizing['results']['sized_mtow_kg']:.1f} kg "
      f"in {sizing['results']['iterations']} iters")
```

### When to use

- Multi-step workflows where you need in-memory config (the accumulated config
  stays in the session between calls)
- Agent-driven analysis (Claude spawning evt-cli as a subprocess)
- Fastest mode -- no per-call process startup

### Special run_id values

- `"latest"` or `"last"` -- resolves to the most recent run_id in the session

## Mode 2 -- One-shot subcommands

Each invocation is a standalone process. Tool names use hyphens instead of
underscores: `load_vehicle_template` -> `evt-cli load-vehicle-template`.

```bash
evt-cli load-vehicle-template --template test_all
evt-cli set-power --params '{"batt_spec_energy_w_h_p_kg": 280.0}'
evt-cli --pretty run-mission-analysis
```

### State persistence

The accumulated config is persisted to `~/.hangar/state/<workspace>.json` so a
later `run-mission-analysis` invocation can find the config seeded by
`load-vehicle-template`. The `--workspace` flag namespaces these state files.

### When to use

- Quick one-off checks from the terminal
- Shell scripts and CI pipelines
- When you only need a single tool call

## Mode 3 -- Script / batch

Write a JSON array of tool calls and execute them in a single process with
shared in-memory config.

```json
[
  {"tool": "start_session", "args": {"notes": "eVTOL sizing study"}},
  {"tool": "load_vehicle_template", "args": {"template": "test_all"}},
  {"tool": "set_power", "args": {"params": {"batt_spec_energy_w_h_p_kg": 280.0}}},
  {"tool": "run_mission_analysis", "args": {}},
  {"tool": "run_sizing", "args": {}},
  {"tool": "visualize", "args": {
    "run_id": "$prev.run_id", "plot_type": "mtow_convergence", "output": "file"
  }},
  {"tool": "export_session_graph", "args": {}}
]
```

Run with:

```bash
evt-cli --pretty run-script workflow.json
evt-cli run-script workflow.json --save-to results.json
```

### Variable interpolation

- `$prev.run_id` -- run_id from the immediately preceding step
- `$1.run_id`, `$2.run_id` -- run_id from step 1, step 2 (1-indexed)

### When to use

- Reproducible workflows to share or re-run
- Multi-point studies (mission + sizing + a sweep)
- Batch execution with full provenance tracking
