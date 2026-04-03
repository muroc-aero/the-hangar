# TTBW Study -- Truss-Braced Wing Analysis

Guidelines and limitations for truss-braced wing (TTBW) studies using the
OAS MCP server.

## Critical limitation

**OAS cannot model strut load relief.** The structural FEM in OpenAeroStruct
models the wing as a single cantilever beam (tube or wingbox geometry). There
is no strut element, no intermediate support, and no mechanism to capture the
bending moment reduction that a strut or jury strut provides.

This means:
- **Bending loads are overpredicted** -- the wing sees full cantilever bending
  from root to tip, ignoring the strut attachment point
- **Structural mass is overpredicted** -- sizing to cantilever loads produces
  a heavier structure than a properly braced wing would require
- **Failure index is overpredicted** -- von Mises stress will be higher than
  in reality because the strut load path is absent
- **Fuel burn is overpredicted** -- heavier structure drives higher fuel burn

## What you CAN do with OAS for TTBW studies

Despite the strut limitation, OAS can still provide useful partial results:

### 1. Aerodynamic characterization

The VLM aerodynamics do not depend on the strut structural model. You can:
- Analyze the aerodynamic performance of a high-aspect-ratio wing planform
- Compute drag polars for TTBW-like geometries (high span, thin airfoils)
- Study the effect of sweep, taper, and twist on aerodynamic efficiency
- Compare L/D of conventional vs high-AR planforms

```
create_surface(
    name="wing", wing_type="rect",
    span=50.0,              # TTBW: high aspect ratio
    root_chord=4.0,
    taper=0.3,
    sweep=10.0,
    num_x=7, num_y=51,      # high AR needs extra spanwise panels
    symmetry=True,
    with_viscous=True, with_wave=True, CD0=0.010
)
compute_drag_polar(surfaces=["wing"], alpha_start=-2, alpha_end=10, num_alpha=13,
                   Mach_number=0.78, density=0.38)
```

### 2. Aero-only optimization

Twist optimization for minimum drag is valid because it depends only on
the aerodynamic model:

```
run_optimization(
    surfaces=["wing"], analysis_type="aero",
    objective="CD", objective_scaler=50,
    design_variables=[
        {"name": "twist", "lower": -10, "upper": 15},
        {"name": "alpha", "lower": -5, "upper": 10}
    ],
    constraints=[{"name": "CL", "equals": 0.5}],
    Mach_number=0.78, density=0.38
)
```

### 3. Upper-bound structural estimates

Aerostructural analysis will give a **conservative upper bound** on structural
mass and fuel burn. The actual TTBW values would be lower due to strut relief.
This can be useful for:
- Establishing worst-case structural mass
- Comparing against conventional wings on a consistent (if biased) basis
- Sensitivity studies on material properties or thickness distribution

## What you CANNOT do

- Accurately predict TTBW structural mass, failure margins, or fuel burn
- Compare TTBW vs conventional on structural merit (the comparison is biased
  against TTBW)
- Optimize structural thickness for a TTBW -- the result will be sized for
  cantilever loads, not braced loads
- Model strut-wing interference aerodynamics (strut is not in the VLM mesh)

## Required documentation

When reporting TTBW results that include structural analysis, always include
this caveat:

> **Limitation:** OAS models the wing as a cantilever beam without strut load
> relief. Structural mass, failure index, and fuel burn are conservative upper
> bounds. Actual TTBW performance would be better due to bending moment
> reduction at the strut attachment point.

## Alternative approaches

For proper TTBW structural analysis, consider:
- Adding a strut as a separate beam element in a dedicated FEM tool
- Using NASTRAN or similar FEA with explicit strut modeling
- Applying a bending moment correction factor based on strut geometry
  (not implemented in OAS, would require manual post-processing)
