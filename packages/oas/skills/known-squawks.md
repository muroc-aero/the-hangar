# Known Squawks -- OAS Failure Modes and Workarounds

Known failure modes, silent errors, and workarounds for the OpenAeroStruct
MCP server. Consult this list before debugging unexpected OAS behavior.

## Critical failure modes

### 1. Silent DV name rejection

**Symptom:** Optimization converges in 1--2 iterations with no design change,
or `success: true` but the objective barely improved.

**Cause:** OAS silently ignores unrecognized design variable names. A typo
like `"thicknes"` instead of `"thickness"` means no DVs are active.

**Workaround:** Always validate DV names against the known set before
calling `run_optimization`:
```
twist, thickness, chord, sweep, taper, alpha,
spar_thickness, skin_thickness (wingbox only)
```

The server validates DV names and will return an error if one is unrecognized,
but double-check the exact spelling in the request.

### 2. load_factor caching bug

**Symptom:** Changing `load_factor` between runs has no effect. Results at
2.5g look identical to 1.0g.

**Cause:** OAS caches the OpenMDAO problem and does not always propagate
`load_factor` changes to the cached problem.

**Workaround:** Always set `load_factor` explicitly in every
`run_aerostruct_analysis` call. If results look wrong, call `reset()` to
clear the cached problem and re-create the surface.

### 3. TTBW strut load relief not modeled

**Symptom:** Truss-braced wing (TTBW) studies show unrealistically high
bending loads because the strut load path is not captured.

**Cause:** OAS has no strut element. The structural FEM models the wing as
a single cantilever beam (tube or wingbox). There is no mechanism to apply
the load relief that a strut provides.

**Workaround:** Do not attempt strut-braced wing studies without clearly
documenting this limitation. Results will overpredict structural mass and
failure index. See the `ttbw-study` skill for details.

### 4. Fast convergence = wrong setup

**Symptom:** Optimizer converges in 1--2 iterations.

**Cause:** Usually one of:
- DV bounds are too tight (the optimizer is already at a bound)
- DVs are not being applied (see squawk #1)
- The initial point already satisfies all constraints and is near-optimal
  (unlikely for a real problem)

**Workaround:** Check that DV bounds span a physically meaningful range.
Verify that optimized DV values differ from initial values. If they are
identical, the DVs were not connected.

### 5. SLSQP scaling failures

**Symptom:** `success: false` with few iterations, or constraints violated
at termination despite a feasible starting point.

**Cause:** SLSQP is gradient-based and uses finite-difference gradients. If
the objective is O(100,000) while a DV is O(0.01), the gradient is poorly
conditioned.

**Workaround:** Set `objective_scaler ~ 1/baseline_objective`. For DVs with
small magnitudes (thickness ~0.01 m), set `scaler: 100`. See the
`optimization-setup` skill for the full scaling guide.

### 6. num_y must be odd

**Symptom:** Error "num_y must be odd" when creating a surface.

**Cause:** OAS requires an odd number of spanwise panels for VLM symmetry.

**Workaround:** Use the nearest odd number: 3, 5, 7, 9, 11, ...

### 7. Missing structural properties

**Symptom:** Error "missing structural props" when running aerostructural
analysis.

**Cause:** The surface was created without `fem_model_type` or without the
required material properties.

**Workaround:** Re-create the surface with `fem_model_type="tube"` (or
`"wingbox"`) and provide `E`, `G`, `yield_stress`, `mrho`.

### 8. Surface not found

**Symptom:** Error "Surface not found" when running analysis.

**Cause:** The surface name in the analysis call does not match any surface
created in the current session.

**Workaround:** Call `create_surface` first with the exact name string used
in the analysis call. Names are case-sensitive.

### 9. Failure metric convention (failure > 0 = overstress, not > 1)

**Symptom:** A wing with `failure = 0.4` is reported or interpreted as safe
("utilisation 40%"), when it is actually 40% OVER the allowable stress.

**Cause:** OAS's KS failure aggregate is `failure = stress/allowable - 1`
(see upstream `structures/failure_ks.py`), not a raw utilisation ratio.
Zero is the failure boundary. The same convention applies to the composite
Tsai-Wu variant (`failure = SR * safety_factor - 1`).

**Workaround:** Interpret `failure > 0` as structural failure and `-failure`
as the margin to allowable (e.g. `failure = -0.3` means 30% margin). When
setting optimization constraints or requirements, use `failure <= 0` (or
`upper: -0.05` for a 5% margin), never `failure <= 1`.

## Diagnostic checklist

When OAS results look wrong:

1. Check `validation.passed` in the response envelope
2. Read `summary.flags` for physics warnings
3. Verify DV names are spelled correctly and are in the valid set
4. Confirm `load_factor` was set explicitly
5. Check that DV bounds are not too tight
6. Verify `objective_scaler` is approximately `1/baseline_objective`
7. If all else fails, call `reset()` and start fresh
