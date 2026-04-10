# Three-Tool Coupled Mission Analysis

Run a Boeing 737-800 basic mission (climb/cruise/descent) with:
- OpenAeroStruct VLM surrogate for drag (replacing the default parabolic polar)
- pyCycle HBTF surrogate for propulsion (replacing the default CFM56)

## Aircraft
- Template: b738 (Boeing 737-800, MTOW 79,002 kg, 124.6 m^2 wing)

## Mission
- Cruise altitude: 35,000 ft
- Range: 1,500 NM
- Climb: 2,000 ft/min at 250 KEAS
- Cruise: 460 KEAS
- Descent: 1,500 ft/min at 250 KEAS

## Slots
- Drag: oas/vlm with 2x7 mesh, 4 twist control points
- Propulsion: pyc/surrogate with HBTF archetype, cruise design point
  (35,000 ft, M=0.8, Fn=5900 lbf, T4=2857 degR, TABULAR thermo)

## Solver
- NLBGS with Aitken relaxation (dual-surrogate coupling requires
  derivative-free nonlinear solver)

## Expected outputs
- Total fuel burn (kg)
- Per-phase profiles: altitude, speed, thrust, drag, fuel flow, weight
- OEW and MTOW

Use omd-cli to assemble and run:
```
omd-cli run plan.yaml --mode analysis
omd-cli results <run_id> --summary
```
