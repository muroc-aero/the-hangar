# Drag Polar Sweep

Compute a drag polar across a range of angles of attack to characterize wing
aerodynamic performance and find the best L/D operating point.

## When to use

Use this skill when the user wants to:
- Map out CL vs CD across the flight envelope
- Find the angle of attack for best L/D
- Find the alpha that achieves a target CL
- Characterize drag breakdown (induced, viscous, wave) across alpha range
- Compare aerodynamic performance before and after a design change

## Workflow

### Step 0 -- Start provenance session

```
start_session(notes="drag polar sweep: <brief description>")
```

### Step 1 -- Define the geometry

```
create_surface(
    name="wing", wing_type="CRM",
    num_x=7, num_y=35, symmetry=True,
    with_viscous=True, CD0=0.015
)
```

Default to num_x=7, num_y=35 for drag polars. Coarser meshes under-resolve
induced drag and can shift the best-L/D point. Only reduce if the user asks
for speed or runtime is a problem (try num_y=21, num_x=5 as a fallback).

For wave drag studies at transonic speeds, set `with_wave=True`.

### Step 2 -- Run drag polar

```
compute_drag_polar(
    surfaces=["wing"],
    alpha_start=-5.0, alpha_end=15.0, num_alpha=21,
    Mach_number=0.84, density=0.38
)
```

Parameter guidance:
- `alpha_start=-5.0, alpha_end=15.0, num_alpha=21` gives 1-degree resolution
  across the useful range
- For a quick scan, use `alpha_start=0.0, alpha_end=12.0, num_alpha=13`
- For high resolution near stall, narrow the range and increase `num_alpha`

### Step 3 -- Interpret results

The response contains arrays indexed by alpha:

| Field | Description |
|-------|-------------|
| `alpha_deg[]` | Angles of attack swept |
| `CL[]` | Lift coefficient at each alpha |
| `CD[]` | Total drag coefficient at each alpha |
| `CM[]` | Pitching moment coefficient at each alpha |
| `L_over_D[]` | Lift-to-drag ratio at each alpha |
| `best_L_over_D` | Object with `alpha_deg`, `CL`, `CD`, `L_over_D` at the optimum |

Key things to report:
1. Best L/D point: alpha, CL, CD, L/D
2. The alpha that gives the target CL (if specified by user)
3. Whether the polar shape is reasonable (parabolic drag rise)
4. Drag breakdown if available (CDi, CDv, CDw percentages)

```
log_decision(
    decision_type="result_interpretation",
    reasoning="<polar interpretation -- best L/D, target CL alpha, drag breakdown>",
    selected_action="<recommended operating point>",
    prior_call_id="<call_id from drag polar result>"
)
```

### Step 4 -- Stability check (optional)

If the user needs stability information at the operating point:

```
compute_stability_derivatives(
    surfaces=["wing"],
    alpha=<best_alpha>, Mach_number=0.84, density=0.38,
    cg=[<x_cg>, 0, 0]
)
```

Returns `CL_alpha`, `CM_alpha`, `static_margin`, and stability classification.

### Step 5 -- Export provenance

```
export_session_graph(session_id=session_id)
```

## Multi-surface drag polars

For wing + tail configurations:

```
create_surface(name="wing", wing_type="CRM", num_x=7, num_y=35, ...)
create_surface(name="tail", wing_type="rect", span=6.0, root_chord=1.5,
               num_x=7, num_y=21, offset=[20.0, 0.0, 0.0],
               CD0=0.0, CL0=0.0)
compute_drag_polar(surfaces=["wing", "tail"], ...)
```

## Comparing polars

To compare before/after a design change:
1. Run the baseline polar, note the `run_id`
2. Modify the surface (e.g. change sweep, taper, twist_cp)
3. Run a second polar
4. Use `get_artifact(run_id)` to retrieve both and compare key metrics

## Common issues

- Flat polar (no drag variation) -- check that `with_viscous=True` and `CD0` is reasonable
- Negative L/D at low alpha -- normal for cambered wings at negative alpha
- No wave drag contribution -- set `with_wave=True` for transonic analysis
