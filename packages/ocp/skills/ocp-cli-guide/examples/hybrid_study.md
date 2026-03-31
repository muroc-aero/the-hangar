# Example: Hybrid-Electric Trade Study

## Interactive mode (Python)

```python
call("start_session", notes="Hybrid design study")

# Load hybrid-ready aircraft
call("load_aircraft_template", template="kingair")
call("set_propulsion_architecture", architecture="twin_series_hybrid",
     battery_specific_energy=450)

# Configure mission
call("configure_mission", mission_type="full", cruise_altitude=29000,
     mission_range=500, cruise_hybridization=0.05, payload=1000,
     num_nodes=11)

# Baseline analysis
result = call("run_mission_analysis", run_name="baseline")
print(f"Fuel: {result['results']['fuel_burn_kg']:.0f} kg")

# Sweep hybridization fraction
sweep = call("run_parameter_sweep",
             parameter="hybridization",
             values=[0.0, 0.05, 0.1, 0.15, 0.2, 0.3])
for pt in sweep["results"]["sweep_results"]:
    print(f"  hyb={pt['hybridization']:.2f} -> fuel={pt.get('fuel_burn_kg', 'N/A')} kg")

call("export_session_graph")
```

## One-shot mode (bash)

```bash
ocp-cli load-aircraft-template --template kingair
ocp-cli set-propulsion-architecture --architecture twin_series_hybrid \
        --battery-specific-energy 450
ocp-cli configure-mission --mission-type full --cruise-altitude 29000 \
        --mission-range 500 --cruise-hybridization 0.05 --payload 1000 \
        --num-nodes 11
ocp-cli --pretty run-mission-analysis --run-name baseline
ocp-cli --pretty run-parameter-sweep \
        --parameter hybridization --values '[0.0, 0.05, 0.1, 0.15, 0.2, 0.3]'
```

## Script mode (JSON)

```json
[
  {"tool": "start_session", "args": {"notes": "Hybrid trade study"}},
  {"tool": "load_aircraft_template", "args": {"template": "kingair"}},
  {"tool": "set_propulsion_architecture", "args": {
    "architecture": "twin_series_hybrid", "battery_specific_energy": 450
  }},
  {"tool": "configure_mission", "args": {
    "mission_type": "full", "cruise_altitude": 29000, "mission_range": 500,
    "cruise_hybridization": 0.05, "payload": 1000, "num_nodes": 11
  }},
  {"tool": "run_mission_analysis", "args": {"run_name": "baseline"}},
  {"tool": "run_parameter_sweep", "args": {
    "parameter": "hybridization",
    "values": [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]
  }},
  {"tool": "export_session_graph", "args": {}}
]
```

```bash
ocp-cli --pretty --save-to hybrid_study.json run-script hybrid_trade.json
```
