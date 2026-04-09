# Three-Tool Direct-Coupled Mission Analysis

Run a Boeing 737-800 basic mission (climb/cruise/descent) with both
drag and propulsion slots using direct-coupled providers that run their
full solvers at every Newton iteration.

## Aircraft
- Template: b738 (Boeing 737-800, MTOW 79,002 kg, 124.6 m^2 wing)

## Mission
- Cruise altitude: 35,000 ft
- Range: 1,500 NM
- Climb: 2,000 ft/min at 250 KEAS
- Cruise: 460 KEAS
- Descent: 1,500 ft/min at 250 KEAS

## Slots
- Drag: oas/vlm-direct with 2x5 mesh, 4 twist control points
  (full VLM solver at every Newton iteration, analytic partials)
- Propulsion: pyc/hbtf with direct-coupled HBTF dual-spool turbofan
  (design point: 35,000 ft, M=0.8, Fn=5900 lbf, T4=2857 degR, CEA thermo)

## Expected outputs
- Total fuel burn (kg)
- Per-phase profiles: altitude, speed, thrust, drag, fuel flow, weight
- OEW and MTOW

Use omd-cli to run:
```
omd-cli run plan.yaml --mode analysis
omd-cli results <run_id> --summary
```
