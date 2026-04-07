# Task: Series-Hybrid Electric Mission

Run a full mission analysis for a King Air C90GT with a twin
series-hybrid electric propulsion architecture.

## Requirements

- Aircraft: King Air C90GT (built-in template "kingair")
- Propulsion: twin_series_hybrid
- Mission type: full (includes takeoff)
- Mission: 250 NM range, 28,000 ft cruise altitude
- Hybrid config: 50 kg battery weight, appropriate motor/generator
  ratings for the King Air power class

## Deliverables

1. Create a plan YAML for an `ocp/FullMission` component with the
   hybrid propulsion architecture
2. Run the analysis and report fuel burn, OEW, MTOW, and TOFL
3. Record a result interpretation decision: does the hybrid
   architecture reduce fuel burn compared to a conventional twin
   turboprop? What is the weight penalty from the battery/motors?
4. Generate mission profile and weight breakdown plots

Use `/omd-cli-guide` for plan structure and `/ocp-cli-guide` for
hybrid propulsion architecture configuration (battery_weight,
motor_rating, generator_rating fields).
