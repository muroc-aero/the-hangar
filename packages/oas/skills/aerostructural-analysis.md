# Aerostructural Analysis

Run a coupled aerostructural analysis using the OAS MCP server. This workflow
sizes a wing structure against aerodynamic loads at cruise and computes mission
fuel burn.

## When to use

Use this skill when the user wants to:
- Check whether a wing structure can carry aerodynamic loads
- Compute fuel burn for a given mission profile
- Evaluate structural margins (failure index) at a flight condition
- Get both aerodynamic and structural results in a single coupled solve

## Workflow

### Step 0 -- Start provenance session

```
start_session(notes="aerostructural analysis: <brief description>")
```

Save the returned `session_id`.

### Step 1 -- Define wing with structural properties

```
create_surface(
    name="wing", wing_type="CRM",
    num_x=7, num_y=35, symmetry=True,
    with_viscous=True, CD0=0.015,
    fem_model_type="tube",
    E=70e9, G=30e9, yield_stress=500e6, safety_factor=2.5, mrho=3000.0
)
```

Critical requirements:
- `fem_model_type` must be `"tube"` or `"wingbox"` -- aero-only surfaces will error
- Material properties (`E`, `G`, `yield_stress`, `mrho`) must be provided
- `num_y` must be odd (3, 5, 7, 9, ...)
- Default to num_x=7, num_y=35 (publication quality). The server default
  (num_x=2, num_y=7) is a unit-test mesh that under-resolves spanwise loads
  and structural stress distributions. Only reduce mesh if the user asks for
  speed or runtime is a problem. See the oas-cli-guide SKILL.md mesh table.

Log the mesh decision:
```
log_decision(
    decision_type="mesh_resolution",
    reasoning="num_y=35 publication-quality mesh, matches upstream OAS examples",
    selected_action="num_x=7, num_y=35"
)
```

### Step 2 -- Run coupled analysis

```
run_aerostruct_analysis(
    surfaces=["wing"],
    velocity=248.136, alpha=5.0,
    Mach_number=0.84, density=0.38,
    W0=120000,              # aircraft empty weight excl. wing, kg
    R=11.165e6,             # mission range, m
    speed_of_sound=295.4,
    load_factor=1.0         # ALWAYS set explicitly (caching bug)
)
```

### Step 3 -- Interpret results

Check the response envelope:

| Field | Meaning |
|-------|---------|
| `failure < 0` | Structure is safe at this load |
| `failure > 0` | Structural failure -- increase `thickness_cp` or reduce `load_factor` |
| `L_equals_W ~ 0` | Wing is properly trimmed for aircraft weight |
| Large `L_equals_W` residual | Adjust `alpha` or `W0` |
| `fuelburn` | Mission fuel burn in kg |
| `structural_mass` | Wing structural mass in kg |

Always check `validation.passed` before trusting results. Note any flags in
`summary.flags` (e.g. `tip_loaded`, `high_stress`).

```
log_decision(
    decision_type="result_interpretation",
    reasoning="<interpretation of failure, fuelburn, structural_mass>",
    selected_action="<next step or conclusion>",
    prior_call_id="<call_id from analysis result>"
)
```

### Step 4 -- Visualize (optional)

```
visualize(run_id=run_id, plot_type="stress_distribution", output="file")
visualize(run_id=run_id, plot_type="lift_distribution", output="file")
```

In CLI environments, use `output="file"` or `output="url"` since inline images
render as `[image]`.

### Step 5 -- Export provenance

```
export_session_graph(session_id=session_id)
```

## Typical flight conditions (cruise, FL350)

| Parameter | Value |
|-----------|-------|
| velocity | 248.136 m/s |
| Mach_number | 0.84 |
| density | 0.38 kg/m3 |
| speed_of_sound | 295.4 m/s |
| reynolds_number | 1e6 |

## Material defaults (Al 7075)

| Property | Value |
|----------|-------|
| E | 70e9 Pa |
| G | 30e9 Pa |
| yield_stress | 500e6 Pa |
| mrho | 3000 kg/m3 |
| safety_factor | 2.5 |

## Common errors

- "missing structural props" -- re-create surface with `fem_model_type="tube"` and material properties
- Large `L_equals_W` residual -- alpha or W0 is inconsistent with the wing sizing
- `failure > 0` at load_factor=1.0 -- wing is undersized; increase `thickness_cp`
