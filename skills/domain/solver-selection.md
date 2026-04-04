# Solver Selection Guide

When to use which solver configuration for OAS problems.

## Nonlinear solvers

### NonlinearBlockGS (Gauss-Seidel)

- **When**: moderate mesh (num_y < 30), initial exploration, robust convergence
  needed
- **Options**: `maxiter: 50`, `atol: 1e-6`, `rtol: 1e-6`
- **Pros**: robust, rarely diverges, no need for good initial guess
- **Cons**: slow convergence for tightly coupled problems

### NewtonSolver

- **When**: fine meshes, production runs, faster convergence needed
- **Options**: `maxiter: 20`, `atol: 1e-6`, `rtol: 1e-6`,
  `solve_subsystems: true`
- **Pros**: quadratic convergence near the solution
- **Cons**: can diverge with poor initial guess, needs a linear solver
- **Required**: always pair with a linear solver (DirectSolver recommended)

### When to switch from GS to Newton

- GS is stalling (residuals plateau after many iterations)
- GS is taking > 100 iterations to converge
- You need faster turnaround on a large mesh
- The aerostructural coupling is strong (high load_factor, flexible structure)

## Linear solvers

### DirectSolver

- **When**: always works, good default for small-medium problems
- **Complexity**: O(n^3) with problem size
- **Use for**: num_y up to ~40, all optimization runs

### LinearBlockGS

- **When**: large problems where DirectSolver is too slow
- **Options**: `maxiter: 25`, `atol: 1e-10`
- **Use for**: num_y > 40

## Solver configuration in plan YAML

```yaml
solvers:
  nonlinear:
    type: NewtonSolver
    options:
      maxiter: 20
      atol: 1.0e-6
      rtol: 1.0e-6
      solve_subsystems: true
  linear:
    type: DirectSolver
```

## Convergence diagnostics

### Stalled convergence

Residuals stop decreasing but have not reached tolerance.

- Tighten solver tolerances
- Increase maxiter
- Switch from GS to Newton
- Check that DVs and initial values are physically reasonable

### Diverging residuals

Residuals increase each iteration.

- Check DV bounds (physically unreasonable values cause divergence)
- Check material properties (wrong units cause order-of-magnitude errors)
- Try smaller step size (reduce line search alpha for Newton)
- Add relaxation to GS: `solve_subsystems: true` with Newton

### Oscillating residuals

Residuals bounce up and down without converging.

- Add Aitken relaxation to GS
- Reduce solver coupling (try RunOnce for the inner loop as a diagnostic)
- Check for conflicting constraints

## Optimizer selection

### SLSQP

- **When**: smooth problems with analytic derivatives (all OAS problems)
- **Typical options**: `maxiter: 50-200`, `ftol: 1e-9`
- **Pros**: efficient for constrained problems, uses gradient information
- **Cons**: can get stuck in local minima

### COBYLA

- **When**: noisy problems, derivative-free optimization needed
- **Pros**: handles noisy objectives, no derivatives needed
- **Cons**: much slower than SLSQP, poor scaling with many DVs

For all OAS problems, SLSQP is the default choice. Use COBYLA only when
SLSQP consistently fails to converge.

## Aero-only vs aerostructural solver needs

- **Aero-only**: no iterative NL solver needed (the VLM is a direct solve).
  Use `NonlinearBlockGS` with `maxiter: 1` or omit solvers entirely.
- **Aerostructural**: always needs an iterative NL solver because the
  aero and structural disciplines are coupled. Newton + DirectSolver is
  the standard configuration.
