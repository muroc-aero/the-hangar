# Boeing 737-800 Reserve Mission

Run an airline-style mission with a reserve diversion and loiter for a Boeing
737-800 (twin turbofan, CFM56-7B).

## Parameters

- **Aircraft**: b738 template (twin turbofan, 2x CFM56-7B, MTOW 79,002 kg)
- **Architecture**: twin_turbofan (routes through OpenConcept's CFM56 surrogate)
- **Mission**: with_reserve (climb/cruise/descent + reserve climb/cruise/descent
  + loiter), 2050 NM at FL330
- **Climb**: 1450 ft/min, 225 kn EAS
- **Cruise**: 261 kn EAS at 33,000 ft
- **Descent**: 575 ft/min, 250 kn EAS
- **Reserve**: diversion at 15,000 ft (reserve climb/cruise/descent + loiter use
  the tool defaults)
- **Nodes**: 11 per phase

## Expected MCP Tool Calls

1. `load_aircraft_template(template="b738")`
2. `set_propulsion_architecture(architecture="twin_turbofan")`
3. `configure_mission(mission_type="with_reserve", cruise_altitude=33000, mission_range=2050, climb_vs=1450, climb_Ueas=225, cruise_Ueas=261, descent_vs=575, descent_Ueas=250, reserve_altitude=15000, num_nodes=11)`
4. `run_mission_analysis()`

## Expected Output

Report block fuel (kg), total fuel including reserve (kg), and MTOW (kg).

These are based on the upstream OpenConcept B738 example but will **not** match
it exactly: the MCP tools fly constant per-phase speeds (the upstream script
ramps them) and use GA-default reserve-phase speeds rather than the jet speeds
the upstream B738 uses. Expect the block fuel to land within a few percent of
the upstream value and the reserve total to differ more. This is a real
limitation of the current `configure_mission` API, not a solver problem -- see
`../README.md`.
