# Design Study Workflow

A multi-step process for conducting systematic design studies using Hangar
tool servers. This skill provides the overall structure; individual tool
skills handle the details of each analysis.

## When to use

Use this skill when the user wants to:
- Conduct a structured design study with baseline, variations, and comparison
- Follow a disciplined analysis process with provenance tracking
- Explore a design space systematically rather than ad hoc

## Workflow phases

### Phase 1 -- Problem definition

Before touching any tools:
1. Clarify the design objective (min drag, min weight, min fuel burn, max L/D)
2. Identify the design variables and their ranges
3. Define constraints (structural limits, target CL, stability requirements)
4. Establish flight conditions (Mach, altitude, weight)
5. Choose the analysis fidelity (aero-only vs aerostructural, mesh resolution)

Document these decisions before proceeding.

### Phase 2 -- Baseline analysis

1. Start a provenance session: `start_session(notes="<study description>")`
2. Create the baseline geometry with nominal parameters
3. Run the appropriate analysis (aero or aerostruct) at the design condition
4. Record baseline metrics: CL, CD, L/D, structural mass, fuel burn
5. Save the baseline `run_id` for later comparison
6. **Required:** Log the baseline interpretation:
   ```
   log_decision(
       decision_type="result_interpretation",
       reasoning="Baseline performance: CL=X, CD=Y, L/D=Z. These values
                  are consistent with expectations for this class of wing.",
       selected_action="Accept baseline; proceed with variations",
       prior_call_id=<baseline_run_call_id>
   )
   ```

### Phase 3 -- Design variations

For each variation in the study:
1. **Required:** Log the variation rationale before running:
   ```
   log_decision(
       decision_type="variation_rationale",
       reasoning="Testing sweep=30 deg to evaluate wave drag sensitivity.
                  Hypothesis: moderate sweep increase improves transonic L/D.",
       selected_action="Run analysis with sweep=30 deg, all else held constant"
   )
   ```
2. Modify the relevant parameter(s)
3. Re-create the surface with updated geometry
4. Run the same analysis at the same flight condition
5. Record the `run_id` and key metrics
6. **Required:** Log result interpretation:
   ```
   log_decision(
       decision_type="result_interpretation",
       reasoning="Sweep=30 yields CD=X (delta from baseline), L/D=Y.",
       selected_action="Record; compare in synthesis phase",
       prior_call_id=<variation_run_call_id>
   )
   ```

Typical variation strategies:
- **Parametric sweep:** vary one parameter across a range (e.g. sweep 0--40 deg)
- **Factorial:** vary two parameters in a grid (e.g. sweep x taper)
- **Optimization:** let the optimizer find the best combination

### Phase 4 -- Comparison and synthesis

1. Retrieve all run artifacts using `get_artifact(run_id)` for each run
2. Build a comparison table with key metrics and percentage changes
3. Identify trends (e.g. "increasing sweep reduces induced drag but increases
   structural mass")
4. Determine the best design point and justify why
5. **Required:** Log the synthesis decision:
   ```
   log_decision(
       decision_type="result_interpretation",
       reasoning="Across N variations, sweep=30 gives best L/D with acceptable
                  structural mass increase (+X%). Diminishing returns above 30 deg
                  due to wave drag. Recommended design point: sweep=30.",
       selected_action="Select sweep=30 as recommended design",
       confidence="high"
   )
   ```

### Phase 5 -- Reporting

Summarize the study with:
- Objective and constraints
- Baseline performance
- Variations explored and their results
- Best design point with justification
- Limitations and caveats (e.g. TTBW strut limitation, mesh sensitivity)
- Provenance graph export for audit trail

### Phase 6 -- Export provenance

```
export_session_graph(session_id=session_id, output_path="design_study_provenance.json")
```

## Example study structure

```
Study: Effect of wing sweep on cruise efficiency
  Baseline: CRM wing, sweep=25 deg
  Variations: sweep = [0, 10, 20, 25, 30, 35, 40] deg
  Analysis: aero at M=0.84, CL=0.5
  Metrics: CD, L/D, CDi, CDw
  Comparison: table + trends
```

## Cross-tool studies

When a study involves multiple tool servers (e.g. OAS for aerostruct +
a propulsion tool for engine sizing):
1. Run each tool's analysis independently
2. Exchange results through shared parameters (e.g. drag from OAS becomes
   thrust requirement for propulsion)
3. Document the coupling assumptions
4. See the `multi-tool-composition` skill for integration patterns
