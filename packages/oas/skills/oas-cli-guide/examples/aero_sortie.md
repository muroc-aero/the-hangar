# Example: Single-Point Aero Analysis

## Interactive mode (Python)

```python
call("create_surface", name="wing", wing_type="CRM", num_y=7, symmetry=True,
     with_viscous=True, CD0=0.015)

result = call("run_aero_analysis", surfaces=["wing"], alpha=5.0,
              velocity=248.136, Mach_number=0.84, density=0.38,
              reynolds_number=1e6)
print(result["results"]["CL"], result["results"]["L_over_D"])

viz = call("visualize", run_id="latest", plot_type="lift_distribution",
           output="file")
print(viz[0]["file_path"])
```

## One-shot mode (bash)

```bash
oas-cli create-surface --name wing --wing-type CRM --num-y 7 \
        --symmetry --with-viscous --CD0 0.015

oas-cli run-aero-analysis --surfaces '["wing"]' --alpha 5.0 \
        --velocity 248.136 --Mach-number 0.84 --density 0.38 \
        --reynolds-number 1e6

oas-cli visualize --run-id latest --plot-type lift_distribution --output file
```

## Script mode (JSON)

```json
[
  {"tool": "create_surface", "args": {
    "name": "wing", "wing_type": "CRM", "num_y": 7,
    "symmetry": true, "with_viscous": true, "CD0": 0.015
  }},
  {"tool": "run_aero_analysis", "args": {
    "surfaces": ["wing"], "alpha": 5.0,
    "velocity": 248.136, "Mach_number": 0.84,
    "density": 0.38, "reynolds_number": 1e6
  }},
  {"tool": "visualize", "args": {
    "run_id": "$prev.run_id",
    "plot_type": "lift_distribution",
    "output": "file"
  }}
]
```

```bash
oas-cli --pretty run-script aero_workflow.json
```

## Incompressible flow (Mach = 0)

OAS supports `Mach_number=0` for incompressible flow:

```bash
oas-cli create-surface --name wing --wing-type rect --num-y 7 --symmetry
oas-cli run-aero-analysis --surfaces '["wing"]' --alpha 5.0 \
        --velocity 50 --Mach-number 0 --density 1.225 --reynolds-number 1e6
```
