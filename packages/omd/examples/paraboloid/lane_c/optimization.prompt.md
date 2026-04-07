# Task: Paraboloid Optimization

Find the minimum of f(x, y) = (x - 3)^2 + x*y + (y + 4)^2 - 3 using
omd-cli with SLSQP optimization.

## Requirements

- Design variables: x in [-50, 50], y in [-50, 50]
- Objective: minimize f_xy
- Optimizer: SLSQP, maxiter 50

## Deliverables

1. Create a plan YAML with the optimization setup
2. Run the optimization and report the optimal x, y, and f_xy
3. Record a convergence assessment decision
4. Verify the result against the analytic minimum (x=20/3, y=-22/3, f=-82/3)

Use `/omd-cli-guide` to learn how to set up design variables, objectives,
and optimizer configuration in the plan YAML.
