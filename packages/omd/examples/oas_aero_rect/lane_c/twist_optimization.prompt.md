# Task: Rectangular Wing Twist Optimization

Optimize the twist distribution of a rectangular wing to minimize drag
at a target lift coefficient using omd-cli.

## Requirements

- Same wing and flight conditions as the aero analysis task (10 m span,
  1 m chord, Mach=0.84, alpha=5 deg)
- Design variable: twist_cp, bounds [-10, 15] deg
- Constraint: CL = 0.5
- Objective: minimize CD (use scaler=10000 for optimizer scaling)
- Optimizer: SLSQP, maxiter=100

## Deliverables

1. Create a plan YAML with the optimization setup
2. Run the optimization and report final CL, CD, and L/D
3. Record a convergence assessment decision (did the optimizer converge?
   is the CL constraint satisfied?)
4. Compare the optimized CD against the baseline analysis CD and report
   the drag reduction
5. Generate convergence and planform plots

Use `/omd-cli-guide` to learn the plan structure for optimization
(design variables, constraints, objective, optimizer sections).
