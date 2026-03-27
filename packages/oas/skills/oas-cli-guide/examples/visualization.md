# Example: Visualization & Output Modes

## The `visualize` tool output modes

| Mode | Behaviour | Best for |
|------|-----------|----------|
| `inline` | Returns `[metadata, ImageContent]` — base64 PNG in JSON | claude.ai |
| `file` | Saves PNG to disk, returns `[metadata]` with `file_path` | CLI / scripts |
| `url` | Returns `[metadata]` with `dashboard_url` and `plot_url` | Remote / VPS |

**Important**: `visualize` returns a **list**, not a dict. The first element is
always a metadata dict. The second element (if present) is the image content.

```python
result = call("visualize", run_id="latest", plot_type="lift_distribution", output="file")
# result is a list: [{"plot_type": "...", "file_path": "/path/to/plot.png", ...}]
file_path = result[0]["file_path"]
```

## Set a session default

Avoid passing `--output` every time:

```bash
oas-cli configure-session --visualization-output file
```

## The `plot` convenience command

Shorthand for `visualize` with `output="file"`:

```bash
oas-cli plot latest lift_distribution              # auto-named file
oas-cli plot latest drag_polar -o polar.png        # custom output path
oas-cli plot 20240315T143022_a1b2c3 stress_distribution
```

## Available plot types

`lift_distribution`, `drag_polar`, `stress_distribution`, `convergence`,
`planform`, `opt_history`, `opt_dv_evolution`, `opt_comparison`,
`deflection_profile`, `weight_breakdown`, `failure_heatmap`,
`twist_chord_overlay`, `mesh_3d`, `multipoint_comparison`, `n2`

## Viewer dashboard

The `oas-cli viewer` command starts an HTTP viewer on localhost (default port
7654). Access it at:

- **Dashboard**: `http://localhost:7654/dashboard?run_id=<id>` — results + plots
- **Provenance**: `http://localhost:7654/viewer?session_id=<id>` — DAG viewer

The `visualize(..., output="url")` mode returns clickable links to these.

```bash
oas-cli viewer                    # start on default port
oas-cli viewer --port 8080        # custom port
```
