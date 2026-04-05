# OAS Aero Analysis Workflow

Step-by-step rectangular wing VLM analysis via omd-cli.

## Analysis

```bash
omd-cli assemble packages/omd/examples/oas_aero_rect/lane_b/aero_analysis/
omd-cli run packages/omd/examples/oas_aero_rect/lane_b/aero_analysis/plan.yaml --mode analysis
omd-cli results <run_id> --summary
omd-cli provenance <plan_id> --format text
```

Expected: CL ~ 0.45, CD ~ 0.035, L/D ~ 13

**Required decision:** After reviewing results, add to `decisions.yaml`:
```yaml
- decision_type: result_interpretation
  agent: have-agent
  reasoning: "CL=0.45, CD=0.035, L/D=12.9. Consistent with rectangular wing at M=0.84."
  selected_action: "Accept baseline analysis"
```

## Twist Optimization

```bash
omd-cli assemble packages/omd/examples/oas_aero_rect/lane_b/twist_optimization/
omd-cli run packages/omd/examples/oas_aero_rect/lane_b/twist_optimization/plan.yaml --mode optimize
omd-cli results <run_id> --summary
```

Expected: CL = 0.5 (constraint), CD reduced from baseline.

**Required decisions:** Before optimization, document DV selection in `decisions.yaml`:
```yaml
- decision_type: dv_selection
  agent: have-agent
  reasoning: "Twist CP as DV to minimize CD at target CL=0.5. SLSQP optimizer."
  selected_action: "Optimize twist distribution"
```

After optimization, add convergence assessment:
```yaml
- decision_type: convergence_assessment
  agent: have-agent
  reasoning: "Converged in N iterations. CL=0.5 constraint met. CD reduced X% from baseline."
  selected_action: "Accept optimized design"
```

## Key Parameters

- Wing: rectangular, span=10m, chord=1m, num_y=7
- Flight: Mach=0.84, alpha=5 deg, Re=1e6
- Optimizer: SLSQP
