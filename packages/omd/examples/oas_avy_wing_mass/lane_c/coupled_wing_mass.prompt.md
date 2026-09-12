# Task: OAS Wing Mass -> Aviary Sizing via omd (closed prompt)

Compose a two-tool analysis through the omd plan tools: an OpenAeroStruct
aerostructural wing computes a structural wing mass, which drives an
Aviary sizing as a deck override on `aircraft:wing:mass`.

## Requirements

- Component `wingbox`, type `oas/AerostructPoint`: rect tube wing --
  span 35.0 m, root chord 4.2 m, num_x 2 / num_y 7, symmetry, tube FEM
  (E 7.0e10, G 3.0e10, yield 5.0e8, mrho 2780,
  thickness_cp [0.015, 0.02, 0.015]), with_viscous.
- Component `sizing`, type `avy/Sizing`: deck
  `models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv`,
  phase_info_module `aviary.models.missions.energy_state_default`,
  SLSQP / max_iter 50, and
  `override_inputs: {wing_mass_override_lbm: {var: aircraft:wing:mass,
  units: lbm, initial: 15000.0}}`.
- Connection: `wingbox.wing.structural_mass` ->
  `sizing.wing_mass_override_lbm` (units convert kg -> lbm on the
  connection).
- Operating point: velocity 231.5, alpha 3.0, Mach_number 0.785,
  re 1.0e6, rho 0.38.
- Solver: NewtonSolver (maxiter 20, atol 1e-6) + DirectSolver targeted at
  `wingbox.AS_point_0.coupled`.
- Run mode `analysis`; the sizing subprocess adds ~15 s.

## Tools

Only the `mcp__omd__*` tools: `start_session` -> author the plan
(builder tools or `write_plan`) -> `validate_plan` -> `run_plan` ->
verify `converged == 1.0` -> `log_decision` -> `export_session_graph`.

## Deliverables

Report, as a fenced JSON block:

```json
{
  "structural_mass_kg": <number>,
  "wing_mass_lbm": <number>,
  "gross_mass_lbm": <number>,
  "total_fuel_mass_lbm": <number>,
  "range_nmi": <number>,
  "converged": <number>
}
```

`wing_mass_lbm` must equal `structural_mass_kg / 0.45359237` -- that
equality is the whole point of the exercise.
