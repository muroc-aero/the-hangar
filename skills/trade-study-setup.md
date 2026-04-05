# Trade Study Setup

Coordinate trade studies that compare design alternatives across one or more
analysis tools in the Hangar workspace.

## When to use

Use this skill when the user wants to:
- Compare multiple design alternatives on a common basis
- Set up a parametric sweep across a design variable
- Evaluate tradeoffs between competing objectives (e.g. drag vs weight)
- Structure a multi-point comparison with consistent methodology

## Trade study structure

### 1. Define the trade space

Identify:
- **Independent variable(s):** what is being varied (e.g. aspect ratio, sweep,
  material, thickness distribution)
- **Dependent metrics:** what is being measured (e.g. CD, structural mass,
  fuel burn, L/D)
- **Fixed conditions:** flight point, constraints, other geometry parameters
  that remain constant

### 2. Establish the baseline

Run a single analysis at the nominal design point. Record all metrics.
This is the reference against which all variations are compared.

### 3. Define the variation matrix

**Single-variable sweep:**
```
Variable: sweep angle
Values: [0, 10, 20, 30, 40] deg
Fixed: M=0.84, CL=0.5, taper=0.3, span=30m
```

**Two-variable grid:**
```
Variable 1: sweep = [10, 20, 30] deg
Variable 2: taper = [0.2, 0.4, 0.6]
Grid: 3 x 3 = 9 runs
Fixed: M=0.84, CL=0.5, span=30m
```

**Discrete alternatives:**
```
Alternative A: Al 7075 tube, sweep=25, taper=0.3
Alternative B: CFRP wingbox, sweep=30, taper=0.25
Alternative C: Al 7075 wingbox, sweep=25, taper=0.3
```

### 4. Execute the runs

For each point in the matrix:
1. **Required:** Log the configuration rationale before running:
   ```
   log_decision(
       decision_type="variation_rationale",
       reasoning="Configuration: sweep=30, taper=0.3. Part of single-variable
                  sweep to isolate effect of sweep on transonic drag.",
       selected_action="Run analysis at this configuration"
   )
   ```
2. Create the surface with the appropriate parameters
3. Run the analysis (keep flight conditions and constraints constant)
4. Record the `run_id` and key metrics
5. **Required:** Log result interpretation for each run:
   ```
   log_decision(
       decision_type="result_interpretation",
       reasoning="Configuration sweep=30: CD=X, L/D=Y, mass=Z kg.
                  Delta from baseline: CD -3%, mass +5%.",
       selected_action="Record for comparison",
       prior_call_id=<run_call_id>
   )
   ```

### 5. Build the comparison

Construct a results table:

| Configuration | CD | L/D | Mass (kg) | Fuel (kg) | Notes |
|---------------|-----|-----|-----------|-----------|-------|
| Baseline | ... | ... | ... | ... | reference |
| Sweep=30 | ... | ... | ... | ... | +5% L/D |
| Sweep=40 | ... | ... | ... | ... | wave drag |

Include absolute values and percentage changes from baseline.

### 6. Identify the Pareto front

When objectives conflict (e.g. lower drag vs lower weight):
- Plot the tradeoff (CD vs structural mass for each configuration)
- Identify Pareto-optimal designs (no design dominates them on all metrics)
- Recommend based on the user's priority weighting
- **Required:** Log the tradeoff interpretation:
  ```
  log_decision(
      decision_type="result_interpretation",
      reasoning="Pareto front contains configs A, C, D. Config A minimizes drag
                 but has highest mass. Config D balances drag and mass.
                 Recommended: Config D given equal priority weighting.",
      selected_action="Recommend Config D as best compromise",
      confidence="high"
  )
  ```

### 7. Document assumptions and limitations

Every trade study should note:
- Analysis fidelity level (VLM, panel, tube FEM vs wingbox)
- What physics are included/excluded (viscous drag, wave drag, aeroelastic coupling)
- Known tool limitations that affect the comparison (e.g. TTBW strut limitation)
- Whether results are converged (check `validation.passed`)

## Tips for clean trades

- Change only one variable at a time for parametric sweeps
- Use the same mesh resolution for all runs in a trade
- Keep the same flight condition (Mach, altitude, weight) across all runs
- Re-create surfaces fresh for each configuration (do not rely on incremental changes)
- Use provenance tracking to maintain an audit trail -- log decisions at every step
- Name runs descriptively: `run_name="sweep_30_taper_03"`

## Cross-tool trades

When a trade involves multiple Hangar tools:
1. Define the interface variables (e.g. drag from OAS feeds thrust from propulsion)
2. Run each tool for each configuration
3. Combine results in a unified comparison table
4. See `multi-tool-composition` for integration patterns
