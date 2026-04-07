# Task: Paraboloid Analysis and Optimization

Run both a function evaluation and an optimization of the paraboloid
f(x, y) = (x - 3)^2 + x*y + (y + 4)^2 - 3 using omd-cli.

## Part 1: Analysis

Evaluate f at x=1.0, y=2.0. Report f_xy.

## Part 2: Optimization

Minimize f with x in [-50, 50] and y in [-50, 50] using SLSQP.
Report optimal x, y, and f_xy. Verify against the analytic minimum
(x=20/3, y=-22/3, f=-82/3).

## Part 3: Summary

Show provenance timelines for both runs and report a comparison table
of the analysis and optimization results.

Use `/omd-cli-guide` to learn the plan YAML structure.
