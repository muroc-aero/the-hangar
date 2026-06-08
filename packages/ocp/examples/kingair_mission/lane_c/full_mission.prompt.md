# Full King Air C90GT Mission with Takeoff

Run a full mission with balanced-field takeoff analysis for a Beechcraft King
Air C90GT (twin turboprop).

## Parameters

- **Aircraft**: kingair template (twin turboprop, 2x PT6A, MTOW 4581 kg)
- **Architecture**: twin_turboprop
- **Mission**: full (with balanced-field takeoff), 1000 NM at FL290
- **Climb**: 1500 ft/min, 124 kn EAS
- **Cruise**: 170 kn EAS at 29,000 ft
- **Descent**: 600 ft/min, 140 kn EAS
- **Payload**: 1000 lb
- **Calibration**: structural_fudge 1.67, takeoff_throttle 0.75 (matches the
  upstream OpenConcept King Air example; the prop rpm of 1900 comes from the
  template automatically)
- **Nodes**: 11 per phase

## Expected MCP Tool Calls

1. `load_aircraft_template(template="kingair")`
2. `set_propulsion_architecture(architecture="twin_turboprop")`
3. `configure_mission(mission_type="full", cruise_altitude=29000, mission_range=1000, climb_vs=1500, climb_Ueas=124, cruise_Ueas=170, descent_vs=600, descent_Ueas=140, payload=1000, structural_fudge=1.67, takeoff_throttle=0.75, num_nodes=11)`
4. `run_mission_analysis()`

## Expected Output

Report fuel burn (kg), OEW (kg), MTOW (kg), and TOFL (ft). These should match
the upstream OpenConcept King Air example:

- OEW ~2935 kg
- Fuel burn ~756 kg
- TOFL ~3055 ft
