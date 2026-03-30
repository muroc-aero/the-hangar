# Basic Caravan Mission Analysis

Run a basic three-phase mission (climb/cruise/descent) for a Cessna Caravan turboprop.

## Parameters

- **Aircraft**: Caravan template (single turboprop, 675 hp, MTOW 3970 kg)
- **Architecture**: turboprop
- **Mission**: basic (no takeoff), 250 NM at FL180
- **Climb**: 850 ft/min, 104 kn EAS
- **Cruise**: 129 kn EAS at 18,000 ft
- **Descent**: 400 ft/min, 100 kn EAS
- **Nodes**: 11 per phase

## Expected MCP Tool Calls

1. `load_aircraft_template(template="caravan")`
2. `set_propulsion_architecture(architecture="turboprop")`
3. `configure_mission(mission_type="basic", cruise_altitude=18000, mission_range=250, climb_vs=850, climb_Ueas=104, cruise_Ueas=129, descent_vs=400, descent_Ueas=100, num_nodes=11)`
4. `run_mission_analysis()`

## Expected Output

Report fuel burn (kg), OEW (kg), and MTOW (kg). Fuel burn should be ~170 kg for this mission.
