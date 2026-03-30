# CLI Modes

## Mode 1 — Interactive (JSON-lines subprocess)

Spawn a single `ocp-cli interactive` process, write JSON commands to its
stdin, and read JSON responses from its stdout. All state (aircraft config,
cached OpenMDAO problems) lives in memory for the lifetime of the process.

### Protocol

Every request: one JSON object per line on stdin.
```json
{"tool": "<tool_name>", "args": {<keyword args>}}
```

Every response: one JSON object per line on stdout.
```json
{"ok": true, "result": { ... }}
{"ok": false, "error": {"code": "USER_INPUT_ERROR", "message": "..."}}
```

### run_id chaining

The CLI tracks the `run_id` from the most recent successful analysis. You can
use `"latest"` or `"last"` as the run_id value in any tool that accepts one
(e.g. `get_run`, `get_detailed_results`), and it will be resolved automatically.

### Example — Caravan mission (Python)

```python
import subprocess, json

proc = subprocess.Popen(
    ["ocp-cli", "interactive"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
    bufsize=1,
)

def call(tool, **args):
    proc.stdin.write(json.dumps({"tool": tool, "args": args}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    if not resp["ok"]:
        raise RuntimeError(resp["error"]["message"])
    return resp["result"]

# Step 1: load aircraft
call("load_aircraft_template", template="caravan")

# Step 2: set propulsion
call("set_propulsion_architecture", architecture="turboprop")

# Step 3: configure mission
call("configure_mission", mission_type="basic", cruise_altitude=18000,
     mission_range=250, num_nodes=11)

# Step 4: run analysis
result = call("run_mission_analysis")
print(result["results"]["fuel_burn_kg"])

proc.stdin.close()
proc.wait()
```

### Tips

- The process caches the OpenMDAO problem after the first analysis. Subsequent
  calls with different mission params (altitude, range, speeds) reuse the cache.
- Changing the propulsion architecture or aircraft data invalidates the cache.
- Call `{"tool": "reset", "args": {}}` to clear all session state.

---

## Mode 2 — One-shot subcommands

Each invocation is a standalone process. Aircraft and propulsion state is
persisted to `~/.hangar/state/<workspace>.json` so multi-step workflows work
across calls.

### Naming convention

Tool names use underscores; subcommands use hyphens:
`run_mission_analysis` -> `ocp-cli run-mission-analysis`

### Parameter types

| Python type | CLI form |
|-------------|----------|
| `str`, `int`, `float` | `--name value` |
| `bool` | `--flag` / `--no-flag` |
| `list`, `dict`, complex | `--param '[1,2,3]'` (JSON string) |

### Example — multi-step workflow

```bash
# Step 1: load aircraft template
ocp-cli load-aircraft-template --template caravan

# Step 2: set propulsion architecture
ocp-cli set-propulsion-architecture --architecture turboprop

# Step 3: configure and run
ocp-cli configure-mission --mission-type basic --cruise-altitude 18000 \
        --mission-range 250 --num-nodes 11

ocp-cli --pretty run-mission-analysis

# Use a named workspace to isolate state
ocp-cli --workspace study1 load-aircraft-template --template kingair
ocp-cli --workspace study1 set-propulsion-architecture --architecture twin_series_hybrid

# Clear state when done
ocp-cli --workspace study1 reset
```

### Important: one-shot mode rebuilds the OpenMDAO problem each invocation

The aircraft and architecture state are persisted; the compiled OpenMDAO
problem is not. Each call to an analysis tool costs ~1-3 s for problem setup.
Use interactive mode for sweeps or repeated analyses.

---

## Mode 3 — Script / batch

Write a JSON array of tool calls, execute in one process. State is shared
across all steps in memory.

### run_id interpolation

Scripts support variable references:
- `"$prev.run_id"` -> run_id from the most recent successful step
- `"$2.run_id"` -> run_id from step 2 (1-indexed)

### Workflow file format

```json
[
  {"tool": "load_aircraft_template", "args": {"template": "caravan"}},
  {"tool": "set_propulsion_architecture", "args": {"architecture": "turboprop"}},
  {"tool": "configure_mission", "args": {
    "mission_type": "basic",
    "cruise_altitude": 18000,
    "mission_range": 250,
    "num_nodes": 11
  }},
  {"tool": "run_mission_analysis", "args": {"run_name": "caravan_basic"}}
]
```

```bash
ocp-cli run-script workflow.json
ocp-cli --pretty --save-to results.json run-script workflow.json
```

Each step's result is printed as a JSON line as it completes. With `--save-to`,
all results are collected and written to a single file at the end.

### Architecture comparison script

```json
[
  {"tool": "load_aircraft_template", "args": {"template": "kingair"}},
  {"tool": "set_propulsion_architecture", "args": {"architecture": "twin_turboprop"}},
  {"tool": "configure_mission", "args": {"mission_range": 250}},
  {"tool": "run_mission_analysis", "args": {"run_name": "turboprop_baseline"}},
  {"tool": "set_propulsion_architecture", "args": {
    "architecture": "twin_series_hybrid", "battery_specific_energy": 450
  }},
  {"tool": "configure_mission", "args": {"mission_range": 250, "cruise_hybridization": 0.1}},
  {"tool": "run_mission_analysis", "args": {"run_name": "hybrid_10pct"}}
]
```
