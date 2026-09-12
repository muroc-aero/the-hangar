# CLI Modes

`avy-cli` supports three execution modes. All use the same tool registry and
response envelope format. Always invoke via the isolated venv:
`.venv-avy/bin/avy-cli` (see SKILL.md prerequisites).

## Mode 1 -- Interactive (JSON-lines subprocess)

Spawn a single long-lived process. Write JSON commands to stdin, read JSON
responses from stdout -- one object per line.

```bash
.venv-avy/bin/avy-cli interactive
```

### Protocol

Send one JSON object per line:

```json
{"tool": "load_aircraft_template", "args": {"template": "advanced_single_aisle", "name": "ac1"}}
```

Receive one JSON object per line:

```json
{"ok": true, "result": {"aircraft_name": "ac1", ...}}
```

### Python example

```python
import subprocess, json

proc = subprocess.Popen(
    [".venv-avy/bin/avy-cli", "interactive"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    text=True, bufsize=1,
)

def call(tool, **args):
    proc.stdin.write(json.dumps({"tool": tool, "args": args}) + "\n")
    proc.stdin.flush()
    resp = json.loads(proc.stdout.readline())
    assert resp["ok"], resp.get("error")
    return resp["result"]

call("start_session", notes="Single-aisle sizing study")
call("load_aircraft_template", template="advanced_single_aisle", name="ac1")
call("configure_mission", aircraft_name="ac1", target_range_nm=1906)
env = call("run_sizing", aircraft_name="ac1")           # ~20 s
assert env["validation"]["passed"], "optimizer did not converge"
perf = env["results"]["performance"]
print(f"gross mass = {perf['gross_mass_lbm']:,.0f} lbm")
print(f"total fuel = {perf['total_fuel_mass_lbm']:,.0f} lbm")
```

### When to use

- Multi-step workflows with in-memory state (aircraft registry persists)
- Agent-driven analysis (Claude spawning avy-cli as a subprocess)
- Comparing several runs (sizing + off-design + payload-range) in one session

## Mode 2 -- One-shot subcommands

Each tool is a subcommand; state persists across invocations via a
workspace file, so a load-then-run sequence works across processes.

```bash
.venv-avy/bin/avy-cli load-aircraft-template --template advanced_single_aisle
.venv-avy/bin/avy-cli define-aircraft --overrides '{"aircraft:wing:aspect_ratio": 13.0}'
.venv-avy/bin/avy-cli --pretty run-sizing
```

Remember: global flags (`--pretty`, `--workspace`, `--save-to`) come BEFORE
the subcommand. Dict parameters are JSON strings.

### When to use

- Quick single runs from a terminal
- Shell scripts and CI snippets

## Mode 3 -- Script (batch JSON)

Author a JSON list of `{tool, args}` steps; run them in one process:

```bash
.venv-avy/bin/avy-cli run-script workflow.json
```

`workflow.json`:

```json
[
  {"tool": "start_session", "args": {"notes": "range sensitivity"}},
  {"tool": "load_aircraft_template", "args": {"template": "advanced_single_aisle", "name": "short"}},
  {"tool": "configure_mission", "args": {"aircraft_name": "short", "target_range_nm": 1500}},
  {"tool": "run_sizing", "args": {"aircraft_name": "short", "run_name": "1500 nmi"}},
  {"tool": "export_session_graph", "args": {}}
]
```

The parity-lane examples (`packages/avy/examples/*/lane_b/*.json`) are
exactly this format.

### When to use

- Reproducible workflows to hand off or re-run
- The Lane B side of parity examples

## Runtime expectations (all modes)

| Tool | Wall-clock (default mission, SLSQP) |
|------|-------------------------------------|
| `run_sizing` | ~20 s |
| `run_off_design` | ~40 s (re-runs the sizing internally) |
| `run_payload_range` | ~60 s (sizing + 2 off-design missions) |
