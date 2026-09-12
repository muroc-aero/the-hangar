# Task: Aviary Single-Aisle Sizing (open prompt)

Using the omd plan tools, size an advanced-technology single-aisle
transport (~150 passengers, FLOPS-class empirical methods) for a 1906
nautical-mile design mission, and report the sized takeoff gross mass,
total mission fuel, achieved range, and mission duration.

Engineering context: the analysis couples aircraft sizing with a
climb/cruise/descent trajectory optimization -- a single run solves both,
so an analysis-mode plan run is sufficient. The run takes tens of seconds.
Before trusting any number, confirm the embedded optimization actually
converged; a non-converged run still returns values.

Report as a fenced JSON block:

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

This task deliberately does not name the component type, config keys, or
tool workflow. Consult the server's own reference material
(`omd://reference`, tool descriptions, and error messages) to choose them.
