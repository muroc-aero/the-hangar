# Task: Caravan Mission with pyCycle Turbojet Propulsion

Run a Cessna 208 Caravan basic mission (climb/cruise/descent) using
a pyCycle turbojet for propulsion instead of the default turboprop.
The turbojet model should use a surrogate trained from pyCycle
design + off-design sweeps.

## Requirements

- Aircraft: Caravan (use the built-in template)
- Propulsion: replace default turboprop with `pyc/turbojet` slot provider
- Mission: 250 NM range, 18,000 ft cruise altitude
- Turbojet config: design at 18,000 ft, Mach 0.35, 4000 lbf, T4=2370 degR

## Deliverables

1. Create a plan YAML for this analysis using omd-cli
2. Run the plan and report fuel burn, OEW, and MTOW
3. Record a result interpretation decision noting this is a slot
   mechanism demonstration, not a physical design
4. Generate the provenance timeline

## Notes

- The turbojet is not realistic for a Caravan; the point is demonstrating
  that the propulsion slot system works just like the drag slot
- The pyCycle surrogate trains at startup (~30-60 seconds)
- Use TABULAR thermo method for faster training
