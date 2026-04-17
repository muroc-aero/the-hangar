# OAS Aero Analysis Workflow

Step-by-step rectangular wing VLM analysis via omd-cli.

## Analysis

```bash
omd-cli assemble packages/omd/examples/oas_aero_rect/lane_b/aero_analysis/
omd-cli run packages/omd/examples/oas_aero_rect/lane_b/aero_analysis/plan.yaml --mode analysis
omd-cli results <run_id> --summary
```

Expected: CL ~ 0.45, CD ~ 0.035, L/D ~ 13

## Twist Optimization

```bash
omd-cli assemble packages/omd/examples/oas_aero_rect/lane_b/twist_optimization/
omd-cli run packages/omd/examples/oas_aero_rect/lane_b/twist_optimization/plan.yaml --mode optimize
omd-cli results <run_id> --summary
```

Expected: CL = 0.5 (constraint), CD reduced from baseline.

## Key Parameters

- Wing: rectangular, span=10m, chord=1m, num_y=7
- Flight: Mach=0.84, alpha=5 deg, Re=1e6
- Optimizer: SLSQP
