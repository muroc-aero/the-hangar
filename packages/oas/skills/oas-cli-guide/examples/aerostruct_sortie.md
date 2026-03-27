# Example: Aerostructural Analysis (Tube Spar)

## Required surface parameters

Structural analysis requires `fem_model_type` plus material properties:

| Parameter | Tube | Wingbox |
|-----------|------|---------|
| `fem_model_type` | `"tube"` | `"wingbox"` |
| `E` (Young's modulus) | Required | Required |
| `G` (shear modulus) | Required | Required |
| `yield_stress` | Required | Required |
| `mrho` (material density) | Required | Required |
| `thickness_cp` | Required | - |
| `spar_thickness_cp` | - | Required |
| `skin_thickness_cp` | - | Required |

## Script mode — tube spar

```json
[
  {"tool": "start_session", "args": {"notes": "CRM aerostruct baseline"}},
  {"tool": "create_surface", "args": {
    "name": "wing", "wing_type": "CRM", "num_y": 7, "symmetry": true,
    "fem_model_type": "tube",
    "thickness_cp": [0.05, 0.08, 0.05],
    "E": 70e9, "G": 30e9, "yield_stress": 500e6, "mrho": 3000.0
  }},
  {"tool": "run_aerostruct_analysis", "args": {
    "surfaces": ["wing"],
    "velocity": 248.136, "Mach_number": 0.84,
    "density": 0.38, "alpha": 5.0, "reynolds_number": 1e6,
    "W0": 120000, "R": 11.165e6, "speed_of_sound": 295.4,
    "load_factor": 1.0
  }},
  {"tool": "visualize", "args": {
    "run_id": "$prev.run_id",
    "plot_type": "stress_distribution",
    "output": "file"
  }},
  {"tool": "export_session_graph", "args": {"output_path": "aerostruct_provenance.json"}}
]
```

## Key notes

- `failure > 1.0` = structural failure (utilisation ratio); NOT `failure > 0`
- `load_factor` scales L=W trim weight, NOT aerodynamic loads; use alpha to change structural loads
- Omitting structural parameters produces a `USER_INPUT_ERROR`

## Wingbox variant

Replace `fem_model_type` and thickness parameters:

```json
{
  "fem_model_type": "wingbox",
  "spar_thickness_cp": [0.004, 0.005, 0.004],
  "skin_thickness_cp": [0.003, 0.006, 0.003],
  "original_wingbox_airfoil_t_over_c": 0.12
}
```
