# Hybrid Twin Mission Analysis

Run a series-hybrid electric twin turboprop mission (King Air C90GT airframe).

## Parameters

- **Aircraft**: King Air C90GT template (twin turboprop, hybrid-ready)
- **Architecture**: twin_series_hybrid with 450 Wh/kg battery
- **Mission**: full (with takeoff), 500 NM at FL290
- **Climb**: 1500 ft/min, 124 kn EAS
- **Cruise**: 170 kn EAS at 29,000 ft, hybridization = 0.058
- **Descent**: 600 ft/min, 140 kn EAS
- **Payload**: 1000 lb
- **Nodes**: 11 per phase

## Expected MCP Tool Calls

1. `load_aircraft_template(template="kingair")`
2. `set_propulsion_architecture(architecture="twin_series_hybrid", battery_specific_energy=450)`
3. `configure_mission(mission_type="full", cruise_altitude=29000, mission_range=500, climb_vs=1500, climb_Ueas=124, cruise_Ueas=170, descent_vs=600, descent_Ueas=140, num_nodes=11, cruise_hybridization=0.058, payload=1000)`
4. `run_mission_analysis()`

## Expected Output

Report fuel burn (kg), OEW (kg), MTOW (kg), TOFL (ft), battery SOC at end of mission, and MTOW margin. Battery SOC should be positive (not over-discharged).
