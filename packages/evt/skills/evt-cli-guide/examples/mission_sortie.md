# Example: mission energy / power / mass analysis

Goal: load the reference eVTOL and read its per-segment energy, per-segment
electric power, and component mass breakdown at the as-configured MTOW.

## Script mode (recommended for reproducibility)

`mission.json`:

```json
[
  {"tool": "start_session", "args": {"notes": "test_all mission analysis"}},
  {"tool": "load_vehicle_template", "args": {"template": "test_all"}},
  {"tool": "run_mission_analysis", "args": {"run_name": "baseline"}},
  {"tool": "visualize", "args": {"run_id": "$prev.run_id", "plot_type": "segment_energy", "output": "file"}},
  {"tool": "visualize", "args": {"run_id": "$2.run_id", "plot_type": "mass_breakdown", "output": "file"}},
  {"tool": "export_session_graph", "args": {}}
]
```

```bash
evt-cli --pretty run-script mission.json --save-to mission_out.json
```

## Expected headline numbers (test_all baseline)

```
results.energy_kw_hr.cruise               = 124.289885  kW*hr
results.totals.total_mission_energy_kw_hr = 166.77776   kW*hr
```

The `validation` block should report all checks passing (non-negative segment
energies, total-energy consistency, battery mass fraction within the typical
eVTOL window, plausible disk loading).

## One-shot equivalent

```bash
evt-cli load-vehicle-template --template test_all
evt-cli --pretty run-mission-analysis
evt-cli plot latest segment_power
```

## Overriding parameters first

```json
[
  {"tool": "load_vehicle_template", "args": {"template": "test_all"}},
  {"tool": "set_power", "args": {"params": {"batt_spec_energy_w_h_p_kg": 280.0}}},
  {"tool": "configure_mission", "args": {"params": {"cruise_s": 720.0}}},
  {"tool": "run_mission_analysis", "args": {}}
]
```

A longer cruise (`cruise_s`) raises cruise and total energy; a higher battery
specific energy lowers battery mass for the same energy. Unknown keys are
rejected with a typo suggestion -- use the exact schema keys from `commands.md`.
