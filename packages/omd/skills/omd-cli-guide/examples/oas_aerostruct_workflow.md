# OAS Aerostructural Workflow

Step-by-step coupled aero+struct analysis via omd-cli.

## Analysis

```bash
omd-cli assemble packages/omd/examples/oas_aerostruct_rect/lane_b/aerostruct_analysis/
omd-cli run .../plan.yaml --mode analysis
omd-cli results <run_id> --summary
omd-cli provenance <plan_id> --format text
```

Expected: CL > 0, CD > 0, structural_mass > 0, failure < 0 (safe).

**Required decision:** After reviewing results, add to `decisions.yaml`:
```yaml
- decision_type: result_interpretation
  agent: have-agent
  reasoning: "CL=X, CD=Y, structural_mass=Z kg, failure=W (<0, safe).
              Newton solver converged. Results physically reasonable."
  selected_action: "Accept aerostruct analysis"
```

## Key Parameters

- Wing: rectangular, span=10m, tube FEM, aluminum
- Solver: Newton + DirectSolver on coupled group
- Flight: Mach=0.84, alpha=5 deg

## Notes

- The coupled aero+struct solver (Newton) must converge before results are meaningful
- `failure < 0` means the structure has margin; `failure > 0` means overstressed
- `structural_mass` is the total mass of the tube elements
