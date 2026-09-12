# Example: Baseline Sizing Sortie

Size the advanced single-aisle on its design mission and interpret the
result. Script mode (`sizing_sortie.json`):

```json
[
  {"tool": "start_session", "args": {"notes": "Baseline single-aisle sizing"}},
  {"tool": "load_aircraft_template", "args": {"template": "advanced_single_aisle"}},
  {"tool": "log_decision", "args": {"decision_type": "architecture_choice",
    "reasoning": "advanced_single_aisle: FLOPS methods, energy_state mission, canonical docs example"}},
  {"tool": "configure_mission", "args": {"target_range_nm": 1906}},
  {"tool": "run_sizing", "args": {"run_name": "baseline 1906 nmi"}},
  {"tool": "export_session_graph", "args": {}}
]
```

```bash
.venv-avy/bin/avy-cli run-script sizing_sortie.json
```

Reading the run_sizing envelope:

- `validation.passed` -- MUST be true; if false, read the
  `optimizer.success` finding's remediation and re-run with a higher
  `max_iter` or a simpler mission.
- `results.performance.gross_mass_lbm` -- the sizing headline
  (~116,400 lbm for this case).
- `results.performance.total_fuel_mass_lbm` -- mission + reserve fuel
  (~13,800 lbm).
- `results.performance.range_nmi` -- must match the 1906 nmi target when
  converged (the `range.target` finding checks this).

Then visualize:

```bash
.venv-avy/bin/avy-cli visualize --run-id <run_id> --plot-type mission_profile --output file
.venv-avy/bin/avy-cli visualize --run-id <run_id> --plot-type mass_breakdown --output file
```
