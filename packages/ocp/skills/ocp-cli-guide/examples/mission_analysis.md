# Example: Turboprop Mission Analysis

## Interactive mode (Python)

```python
call("load_aircraft_template", template="caravan")
call("set_propulsion_architecture", architecture="turboprop")
call("configure_mission", mission_type="basic", cruise_altitude=18000,
     mission_range=250, num_nodes=11)

result = call("run_mission_analysis")
r = result["results"]
print(f"Fuel burn: {r['fuel_burn_kg']:.1f} kg")
print(f"OEW: {r['OEW_kg']:.0f} kg")
```

## One-shot mode (bash)

```bash
ocp-cli load-aircraft-template --template caravan
ocp-cli set-propulsion-architecture --architecture turboprop
ocp-cli configure-mission --mission-type basic --cruise-altitude 18000 \
        --mission-range 250 --num-nodes 11
ocp-cli --pretty run-mission-analysis
```

## Script mode (JSON)

```json
[
  {"tool": "load_aircraft_template", "args": {"template": "caravan"}},
  {"tool": "set_propulsion_architecture", "args": {"architecture": "turboprop"}},
  {"tool": "configure_mission", "args": {
    "mission_type": "basic", "cruise_altitude": 18000,
    "mission_range": 250, "num_nodes": 11
  }},
  {"tool": "run_mission_analysis", "args": {"run_name": "caravan_basic"}}
]
```

```bash
ocp-cli --pretty run-script caravan_mission.json
```

## Full mission with takeoff

Change `mission_type` to `"full"` to include balanced-field takeoff analysis:

```bash
ocp-cli configure-mission --mission-type full --cruise-altitude 18000 \
        --mission-range 250 --num-nodes 11
ocp-cli --pretty run-mission-analysis
```

The response will include `TOFL_ft` (takeoff field length) and `stall_speed_kn`.
