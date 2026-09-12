# Task: Physics-Based Wing Mass Sizing (open prompt)

You have an Aviary MCP server (aircraft sizing + mission optimization,
`mcp__Aviary__*` tools).

Size a modern single-aisle transport aircraft on a ~1800 nmi fixed-profile
mission, with the empirical (FLOPS) wing weight estimate replaced by a
physics-based structural wing mass computed by an aerostructural analysis.

Discover the available aircraft templates, external subsystems, and
mission templates from the server's own tool descriptions and listings.
Check the run's validation findings before trusting any number -- the
optimizer can fail to converge without raising -- and record your
decisions in the provenance log as you go, including whether the
physics-based wing mass is plausible for an aircraft of this class.

Report, as a fenced JSON block:

```json
{
  "gross_mass_lbm": <float>,
  "total_fuel_mass_lbm": <float>,
  "wing_mass_lbm": <float>,
  "range_nmi": <float>,
  "final_time_min": <float>,
  "converged": <bool>,
  "run_id": "<run id>",
  "friction": ["<any tool-surface problems you hit>"]
}
```

`wing_mass_lbm` is the physics-based value the sizing used.

This task deliberately does not name the aircraft template, the subsystem,
the mission template, or the tool workflow. Consult the server's own
reference material (tool descriptions, the `avy://reference` and
`avy://workflows` resources, and error messages) to choose them.
