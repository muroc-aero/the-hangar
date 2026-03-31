# Example: Hybrid Design Optimization

## Interactive mode (Python)

```python
call("start_session", notes="Hybrid optimization")
call("load_aircraft_template", template="kingair")
call("set_propulsion_architecture", architecture="twin_series_hybrid",
     battery_specific_energy=450)
call("configure_mission", mission_type="full", cruise_altitude=29000,
     mission_range=500, payload=1000, num_nodes=11)

# Log DV selection decision
call("log_decision",
     decision_type="dv_selection",
     reasoning="Optimize MTOW, wing area, engine/motor/gen ratings, battery, hybridization",
     selected_action="8 DVs with wide bounds for exploratory optimization")

result = call("run_optimization",
     objective="mixed_objective",
     design_variables=[
         {"name": "ac|weights|MTOW", "lower": 4000, "upper": 5700},
         {"name": "ac|geom|wing|S_ref", "lower": 15, "upper": 40},
         {"name": "ac|propulsion|engine|rating", "lower": 1, "upper": 3000},
         {"name": "ac|propulsion|motor|rating", "lower": 450, "upper": 3000},
         {"name": "ac|propulsion|generator|rating", "lower": 1, "upper": 3000},
         {"name": "ac|weights|W_battery", "lower": 20, "upper": 2250},
         {"name": "ac|weights|W_fuel_max", "lower": 500, "upper": 3000},
         {"name": "cruise.hybridization", "lower": 0.001, "upper": 0.999},
     ],
     constraints=[
         {"name": "margins.MTOW_margin", "lower": 0.0},
         {"name": "descent.propmodel.batt1.SOC_final", "lower": 0.0},
         {"name": "climb.throttle", "upper": 1.05},
     ],
     max_iterations=200)

# Log convergence assessment
call("log_decision",
     decision_type="convergence_assessment",
     reasoning=f"Converged: {result['results']['optimization_successful']}, "
               f"iters: {result['results'].get('num_iterations')}",
     selected_action="accept results" if result['results']['optimization_successful']
                     else "increase iterations",
     prior_call_id=result["_provenance"]["call_id"])

call("export_session_graph")
```

## Script mode (JSON)

```json
[
  {"tool": "start_session", "args": {"notes": "Hybrid optimization"}},
  {"tool": "load_aircraft_template", "args": {"template": "kingair"}},
  {"tool": "set_propulsion_architecture", "args": {
    "architecture": "twin_series_hybrid", "battery_specific_energy": 450
  }},
  {"tool": "configure_mission", "args": {
    "mission_type": "full", "cruise_altitude": 29000, "mission_range": 500,
    "payload": 1000, "num_nodes": 11
  }},
  {"tool": "run_optimization", "args": {
    "objective": "mixed_objective",
    "design_variables": [
      {"name": "ac|weights|MTOW", "lower": 4000, "upper": 5700},
      {"name": "cruise.hybridization", "lower": 0.001, "upper": 0.999}
    ],
    "constraints": [
      {"name": "margins.MTOW_margin", "lower": 0.0},
      {"name": "descent.propmodel.batt1.SOC_final", "lower": 0.0}
    ],
    "max_iterations": 200
  }},
  {"tool": "export_session_graph", "args": {}}
]
```

```bash
ocp-cli --pretty run-script hybrid_opt.json
```
