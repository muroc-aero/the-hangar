# Example: Architecture Comparison

Compare turboprop vs hybrid for the same mission on the same airframe.

## Interactive mode (Python)

```python
call("start_session", notes="Architecture comparison")
call("load_aircraft_template", template="kingair")

# Run A: Twin turboprop baseline
call("set_propulsion_architecture", architecture="twin_turboprop")
call("configure_mission", mission_range=250, num_nodes=11)
a = call("run_mission_analysis", run_name="turboprop_baseline")
fuel_a = a["results"]["fuel_burn_kg"]

# Run B: Series hybrid
call("set_propulsion_architecture", architecture="twin_series_hybrid",
     battery_specific_energy=400)
call("configure_mission", mission_range=250, cruise_hybridization=0.1,
     num_nodes=11)
b = call("run_mission_analysis", run_name="hybrid_10pct")
fuel_b = b["results"]["fuel_burn_kg"]

print(f"Turboprop: {fuel_a:.0f} kg")
print(f"Hybrid:    {fuel_b:.0f} kg")
print(f"Savings:   {(fuel_a - fuel_b) / fuel_a * 100:.1f}%")

call("export_session_graph")
```

## Script mode (JSON)

```json
[
  {"tool": "start_session", "args": {"notes": "Architecture comparison"}},
  {"tool": "load_aircraft_template", "args": {"template": "kingair"}},
  {"tool": "set_propulsion_architecture", "args": {"architecture": "twin_turboprop"}},
  {"tool": "configure_mission", "args": {"mission_range": 250, "num_nodes": 11}},
  {"tool": "run_mission_analysis", "args": {"run_name": "turboprop_baseline"}},
  {"tool": "set_propulsion_architecture", "args": {
    "architecture": "twin_series_hybrid", "battery_specific_energy": 400
  }},
  {"tool": "configure_mission", "args": {
    "mission_range": 250, "cruise_hybridization": 0.1, "num_nodes": 11
  }},
  {"tool": "run_mission_analysis", "args": {"run_name": "hybrid_10pct"}},
  {"tool": "export_session_graph", "args": {}}
]
```

```bash
ocp-cli --pretty --save-to comparison.json run-script arch_compare.json
```
