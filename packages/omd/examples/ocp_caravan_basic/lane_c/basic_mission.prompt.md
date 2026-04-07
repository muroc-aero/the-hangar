# Task: Caravan Basic Mission Analysis

Run a three-phase mission analysis (climb/cruise/descent) for a
Cessna 208 Caravan turboprop using omd-cli.

## Requirements

- Aircraft: Caravan (use the built-in template)
- Propulsion: single turboprop
- Mission: 250 NM range, 18,000 ft cruise altitude
- Climb: 850 ft/min at 104 kn
- Cruise: 129 kn
- Descent: 400 ft/min at 100 kn
- 11 analysis nodes per phase

## Deliverables

1. Create a plan YAML for an `ocp/BasicMission` component
2. Run the analysis and report fuel burn, OEW, and MTOW
3. Record a result interpretation decision: is the fuel burn
   reasonable for a Caravan on a 250 NM mission?
4. Generate mission profile and weight breakdown plots

Use `/omd-cli-guide` to learn the plan structure and `/ocp-cli-guide`
for OpenConcept-specific configuration (aircraft templates, propulsion
architectures, mission parameters).
