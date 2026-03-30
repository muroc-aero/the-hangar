# All Three Mission Analyses

Run all three demonstration missions in sequence and compare results.

## Step 1: Basic Caravan Mission

1. `start_session(notes="Caravan demonstration")`
2. `load_aircraft_template(template="caravan")`
3. `set_propulsion_architecture(architecture="turboprop")`
4. `configure_mission(mission_type="basic", cruise_altitude=18000, mission_range=250, num_nodes=11)`
5. `run_mission_analysis(run_name="basic_caravan")`
6. `log_decision(decision_type="result_interpretation", reasoning="...")`

## Step 2: Full Caravan Mission (with takeoff)

7. `configure_mission(mission_type="full", cruise_altitude=18000, mission_range=250, num_nodes=11)`
8. `run_mission_analysis(run_name="full_caravan")`
9. `log_decision(decision_type="result_interpretation", reasoning="Compare fuel burn to basic mission")`

## Step 3: Hybrid Twin Mission

10. `load_aircraft_template(template="kingair")`
11. `set_propulsion_architecture(architecture="twin_series_hybrid", battery_specific_energy=450)`
12. `configure_mission(mission_type="full", cruise_altitude=29000, mission_range=500, cruise_hybridization=0.058, payload=1000, num_nodes=11)`
13. `run_mission_analysis(run_name="hybrid_twin")`
14. `log_decision(decision_type="result_interpretation", reasoning="Hybrid performance vs conventional")`

## Step 4: Wrap Up

15. `export_session_graph()`

## Expected Output

Compare fuel burn, OEW, and TOFL across all three configurations. The hybrid should show different tradeoffs (battery weight vs fuel savings).
