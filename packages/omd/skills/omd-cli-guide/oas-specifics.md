# OAS-Specific Notes

Deep-dive companion to `SKILL.md` covering OAS mesh conventions and
the wingbox multipoint optimization pattern.

## OAS Mesh Conventions

When using OAS components (`oas/AeroPoint`, `oas/AerostructPoint`,
`oas/AerostructMultipoint`) with `symmetry: true`:

- **`span`** is the **full** wingspan. OAS halves it internally to
  mesh the half-span. For a 28m wing, set `span: 28.0`, not
  `span: 14.0`.
- **`num_y`** is the **full-span** node count. OAS halves it for the
  half-span mesh. `num_y: 21` with symmetry gives 11 half-span nodes.
  Must be odd.
- **`num_x`** is the chordwise node count. Not affected by symmetry.

## Wingbox Multipoint Optimization

For `oas/AerostructMultipoint` wingbox problems (following the
upstream Q400 example pattern):

**Required design variables:**
- `twist_cp` (scaler=0.1)
- `spar_thickness_cp` (scaler=100)
- `skin_thickness_cp` (scaler=100)
- `t_over_c_cp` (scaler=10) -- controls wave drag vs fuel volume vs
  weight
- `fuel_mass` (scaler=1e-5) -- required to close the `fuel_diff=0`
  constraint
- `alpha_maneuver` -- trim angle at maneuver point

**Recommended constraint formulation:**
- `AS_point_0.CL` equals target (e.g., 0.5) -- cruise trim via CL
  target
- `AS_point_1.L_equals_W` equals 0.0 -- maneuver lift = weight
- `AS_point_1.wing_perf.failure` upper 0.0 -- structural failure at
  maneuver only (binding case)
- `fuel_vol_delta` lower 0.0 -- fuel fits in wingbox
- `fuel_diff` equals 0.0 -- fuel mass consistency

**Surface config keys for wingbox:**

```yaml
struct_weight_relief: true    # wing weight provides load relief
distributed_fuel_weight: true # fuel distributed along span
exact_failure_constraint: false
wing_weight_ratio: 1.25       # secondary structure factor
```

**Objective:** `fuelburn` with `scaler: 1.0e-5`

**Optimizer:** SLSQP with `ftol: 1.0e-4` typically converges in 10-15
iterations when the formulation follows this pattern.
