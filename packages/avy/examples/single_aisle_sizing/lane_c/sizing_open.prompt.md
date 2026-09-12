# Task: Advanced Single-Aisle Sizing (open prompt)

You have access to an aircraft sizing and mission optimization server.

Size an advanced-technology single-aisle transport for a 1906 nautical-mile
design mission and report the sized takeoff gross mass, the total mission
fuel, the achieved range, and the mission duration.

Engineering context: the aircraft is a ~150-passenger transport with
FLOPS-class empirical mass and aerodynamics methods; the mission is a
standard climb/cruise/descent profile. Use the gradient-based optimizer
that is always available in the environment, with its default iteration
budget. Before trusting any number, confirm the optimization actually
converged -- a non-converged run still returns values.

Report, as a fenced JSON block:

```json
{
  "gross_mass_lbm": <float>,
  "total_fuel_mass_lbm": <float>,
  "range_nmi": <float>,
  "final_time_min": <float>,
  "run_id": "<run id>",
  "friction": ["<any tool-surface problems you hit>"]
}
```

This task deliberately does not name the aircraft template, parameter keys,
or tool workflow. Consult the server's own reference material (tool
descriptions, the `avy://reference` and `avy://workflows` resources, and
error messages) to choose them.
