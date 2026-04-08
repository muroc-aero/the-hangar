# Three-Tool Coupled Mission Analysis

Run a Cessna 208 Caravan basic mission (climb/cruise/descent) with:
- OpenAeroStruct VLM surrogate for drag (replacing the default parabolic polar)
- pyCycle turbojet surrogate for propulsion (replacing the default turboprop)

## Aircraft
- Template: caravan (Cessna 208 Caravan, MTOW 3970 kg, 26 m^2 wing)

## Mission
- Cruise altitude: 18,000 ft
- Range: 250 NM
- Climb: 850 ft/min at 104 KEAS
- Cruise: 129 KEAS
- Descent: 400 ft/min at 100 KEAS

## Slots
- Drag: oas/vlm with 2x7 mesh, 4 twist control points
- Propulsion: pyc/surrogate with turbojet archetype, SLS design point
  (Fn=4000 lbf, T4=2370 degR)

## Expected outputs
- Total fuel burn (kg)
- Per-phase profiles: altitude, speed, thrust, drag, fuel flow, weight
- OEW and MTOW

Use omd-cli to assemble and run:
```
omd-cli run plan.yaml --mode analysis
omd-cli results <run_id> --summary
```
