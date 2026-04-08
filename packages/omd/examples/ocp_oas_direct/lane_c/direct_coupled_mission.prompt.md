# Task: Caravan Mission with Direct-Coupled VLM Drag

Run a Cessna 208 Caravan basic mission (climb/cruise/descent) using
direct-coupled VLM-based drag instead of the default parabolic polar.
The VLM solver should run at every Newton iteration (true tight coupling),
not via a pre-trained surrogate.

## Requirements

- Aircraft: Caravan (use the built-in template)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Drag model: replace the default PolarDrag with the `oas/vlm-direct`
  slot provider so that drag is computed from a live VLM solve each
  iteration
- VLM mesh: num_x=2, num_y=5, num_twist=4 (coarse for performance)

## Deliverables

1. Create a plan YAML for this analysis using omd-cli
2. Run the plan and report fuel burn, OEW, and MTOW
3. Record a result interpretation decision explaining whether the
   results are physically reasonable and how they compare to the
   surrogate-coupled (`oas/vlm`) result
4. Generate the provenance timeline

## Notes

- Use `/omd-cli-guide` to learn how to author plan YAML files and
  which component types and slot providers are available
- The `oas/vlm-direct` provider runs the full VLM at every iteration,
  so runtime will be longer than `oas/vlm` (surrogate). Expect minutes
  rather than seconds.
- Keep the mesh coarse (num_y=5) to limit per-iteration cost
- The parent Newton solver must have `solve_subsystems=True` for the
  CL-alpha balance to converge
