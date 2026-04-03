# Example: Aero-Only Optimization (Minimize CD at Fixed CL)

## Script mode with provenance

```json
[
  {"tool": "start_session", "args": {"notes": "Aero optimization — min CD at CL=0.5"}},
  {"tool": "create_surface", "args": {
    "name": "wing", "wing_type": "CRM", "num_x": 7, "num_y": 35,
    "symmetry": true, "with_viscous": true, "CD0": 0.015
  }},
  {"tool": "log_decision", "args": {
    "decision_type": "dv_selection",
    "reasoning": "Twist + alpha for aero-only min-drag at fixed lift",
    "selected_action": "twist (3 cp), alpha",
    "confidence": "high"
  }},
  {"tool": "run_optimization", "args": {
    "surfaces": ["wing"],
    "analysis_type": "aero",
    "objective": "CD",
    "design_variables": [
      {"name": "twist", "lower": -10, "upper": 10, "n_cp": 3},
      {"name": "alpha", "lower": -5,  "upper": 15}
    ],
    "constraints": [{"name": "CL", "equals": 0.5}],
    "Mach_number": 0.84, "density": 0.38, "velocity": 248.136,
    "reynolds_number": 1e6
  }},
  {"tool": "visualize", "args": {
    "run_id": "$prev.run_id",
    "plot_type": "opt_history",
    "output": "file"
  }},
  {"tool": "export_session_graph", "args": {"output_path": "aero_opt_provenance.json"}}
]
```

## One-shot mode

```bash
oas-cli create-surface --name wing --wing-type CRM --num-y 7 \
        --symmetry --with-viscous --CD0 0.015

oas-cli run-optimization \
  --surfaces '["wing"]' \
  --analysis-type aero \
  --design-variables '[{"name":"twist","lower":-10,"upper":10,"n_cp":3},{"name":"alpha","lower":-5,"upper":15}]' \
  --constraints '[{"name":"CL","equals":0.5}]' \
  --objective CD

oas-cli plot latest opt_history
```

## Optimization tuning parameters

- `--objective-scaler` — scale the objective (e.g. `1e4` for small CD values); helps optimizer convergence
- `--tolerance` — convergence tolerance (default: 1e-6; loosen to 1e-4 for faster exploration)
- `--max-iterations` — iteration cap (default: 200)
- `--capture-solver-iters` — log solver residuals per iteration (default: False)

## Extracting run_id in bash for chaining

```bash
RUN_ID=$(oas-cli run-optimization \
  --surfaces '["wing"]' --analysis-type aero --objective CD \
  --design-variables '[{"name":"twist","lower":-10,"upper":10,"n_cp":3}]' \
  --constraints '[{"name":"CL","equals":0.5}]' \
  | python -c "import sys,json; print(json.load(sys.stdin)['result']['run_id'])")

oas-cli visualize --run-id "$RUN_ID" --plot-type opt_history --output file
```
