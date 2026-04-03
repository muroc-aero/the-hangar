# CLI Modes

## Mode 1 — Interactive (JSON-lines subprocess)

Spawn a single `oas-cli interactive` process, write JSON commands to its
stdin, and read JSON responses from its stdout. All state (surfaces, cached
OpenMDAO problems) lives in memory for the lifetime of the process.

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
(e.g. `visualize`, `get_run`, `get_detailed_results`), and it will be resolved
automatically to the last run_id seen in this session.

### Example — full aero workflow (Python)

```python
import subprocess, json

proc = subprocess.Popen(
    ["oas-cli", "interactive"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
    bufsize=1,          # line-buffered
)

def call(tool, **args):
    proc.stdin.write(json.dumps({"tool": tool, "args": args}) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    resp = json.loads(line)
    if not resp["ok"]:
        raise RuntimeError(resp["error"]["message"])
    return resp["result"]

# Step 1: define the wing
call("create_surface", name="wing", wing_type="CRM", num_x=7, num_y=35,
     symmetry=True, with_viscous=True, CD0=0.015)

# Step 2: single-point aero analysis
result = call("run_aero_analysis", surfaces=["wing"], alpha=5.0,
              velocity=248.136, Mach_number=0.84, density=0.38,
              reynolds_number=1e6)
print(result["results"]["CL"], result["results"]["L_over_D"])

# Step 3: visualize using "latest" — no need to track run_id manually
viz = call("visualize", run_id="latest", plot_type="lift_distribution",
           output="file")
print(viz[0]["file_path"])   # visualize returns a list, not a dict

proc.stdin.close()
proc.wait()
```

### Tips

- The process caches the OpenMDAO problem after the first analysis. Subsequent
  calls with the same surface names are much faster (~0.01 s vs ~0.1 s).
- Calling `create_surface` again with the same name invalidates the cache.
- Call `{"tool": "reset", "args": {}}` to clear all session state.
- If you don't need Python, pipe newline-separated JSON directly:

```bash
printf '{"tool":"create_surface","args":{"name":"wing","num_y":7}}\n
{"tool":"run_aero_analysis","args":{"surfaces":["wing"],"alpha":5,"velocity":50,"Mach_number":0.3,"density":1.225,"reynolds_number":1e6}}\n
{"tool":"visualize","args":{"run_id":"latest","plot_type":"lift_distribution","output":"file"}}\n' \
  | oas-cli interactive
```

---

## Mode 2 — One-shot subcommands

Each invocation is a standalone process. Surface definitions are persisted to
`~/.hangar/state/<workspace>.json` so multi-step workflows work across calls.

### Naming convention

Tool names use underscores; subcommands use hyphens:
`run_aero_analysis` -> `oas-cli run-aero-analysis`

### Parameter types

| Python type | CLI form |
|-------------|----------|
| `str`, `int`, `float` | `--name value` |
| `bool` | `--flag` / `--no-flag` |
| `list`, `dict`, complex | `--param '[1,2,3]'` (JSON string) |

### Example — multi-step workflow

```bash
# Step 1: create surface (args saved to ~/.hangar/state/default.json)
oas-cli create-surface --name wing --wing-type CRM --num-y 7 \
        --symmetry --with-viscous --CD0 0.015

# Step 2: run analysis (surface loaded from state file automatically)
oas-cli run-aero-analysis --surfaces '["wing"]' --alpha 5.0 \
        --velocity 248.136 --Mach-number 0.84 --density 0.38 \
        --reynolds-number 1e6

# Step 3: visualize using "latest" — resolves to the most recent run
oas-cli visualize --run-id latest --plot-type lift_distribution --output file

# Use a named workspace to isolate state from other workflows
oas-cli --workspace myproject create-surface --name wing --num-y 7
oas-cli --workspace myproject run-aero-analysis --surfaces '["wing"]' --alpha 5

# Clear state when done (global flags BEFORE the subcommand)
oas-cli --workspace myproject reset
```

### Extracting run_id in bash

When chaining one-shot commands that need a specific run_id (instead of
"latest"), extract it from the JSON response:

```bash
# Extract run_id with python
RUN_ID=$(oas-cli run-aero-analysis --surfaces '["wing"]' --alpha 5 \
         --velocity 248 --Mach-number 0.84 --density 0.38 --reynolds-number 1e6 \
  | python -c "import sys,json; print(json.load(sys.stdin)['result']['run_id'])")

# Use the extracted run_id
oas-cli visualize --run-id "$RUN_ID" --plot-type lift_distribution --output file

# Or with jq if installed
oas-cli run-aero-analysis --surfaces '["wing"]' --alpha 5 --pretty \
  | jq -r '.result.run_id'
```

### Important: one-shot mode rebuilds the OpenMDAO problem each invocation

The surface dict is persisted; the compiled OpenMDAO problem is not. Each call
to an analysis tool costs ~0.1 s for problem setup. This is usually negligible
compared to analysis time but matters for tight loops — use interactive mode
for sweeps.

---

## Mode 3 — Script / batch

Write a JSON array of tool calls, execute in one process. State is shared
across all steps in memory.

### run_id interpolation

Scripts support variable references so you can chain create->analyze->visualize
in a single self-contained file:

- `"$prev.run_id"` -> run_id from the most recent successful step
- `"$2.run_id"` -> run_id from step 2 (1-indexed)

### Workflow file format

```json
[
  {"tool": "create_surface", "args": {"name": "wing", "wing_type": "CRM",
                                       "num_x": 7, "num_y": 35, "symmetry": true,
                                       "with_viscous": true}},
  {"tool": "run_aero_analysis", "args": {"surfaces": ["wing"], "alpha": 5.0,
                                          "Mach_number": 0.84, "velocity": 248.136,
                                          "density": 0.38, "reynolds_number": 1e6}},
  {"tool": "visualize", "args": {"run_id": "$prev.run_id",
                                  "plot_type": "lift_distribution",
                                  "output": "file"}}
]
```

```bash
oas-cli run-script workflow.json
oas-cli --pretty --save-to results.json run-script workflow.json
```

Each step's result is printed as a JSON line as it completes. With `--save-to`,
all results are collected and written to a single file at the end.
