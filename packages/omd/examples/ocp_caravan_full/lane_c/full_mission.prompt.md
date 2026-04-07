# Task: Caravan Full Mission with Takeoff

Run a full mission analysis for a Cessna 208 Caravan including
balanced-field takeoff, climb, cruise, and descent.

## Requirements

- Aircraft: Caravan (built-in template)
- Propulsion: single turboprop
- Mission type: full (includes takeoff phase)
- Mission: 250 NM range, 18,000 ft cruise altitude
- Same speed profiles as the basic mission

## Deliverables

1. Create a plan YAML for an `ocp/FullMission` component
2. Run the analysis and report fuel burn, OEW, MTOW, and takeoff
   field length (TOFL)
3. Record a result interpretation decision
4. Compare fuel burn to the basic mission result -- the full mission
   should burn slightly more fuel due to the takeoff phase

Use `/omd-cli-guide` for plan structure and `/ocp-cli-guide` for
mission types and parameters.
