# Example: Deck-Override Trade Study

Compare wing aspect ratios by overriding the deck variable and resizing.

```json
[
  {"tool": "start_session", "args": {"notes": "Aspect ratio trade"}},
  {"tool": "load_aircraft_template", "args": {"template": "advanced_single_aisle", "name": "base"}},
  {"tool": "run_sizing", "args": {"aircraft_name": "base", "run_name": "AR 11.56 (deck)"}},
  {"tool": "load_aircraft_template", "args": {"template": "advanced_single_aisle", "name": "highAR"}},
  {"tool": "define_aircraft", "args": {"aircraft_name": "highAR",
    "overrides": {"aircraft:wing:aspect_ratio": 13.0}}},
  {"tool": "run_sizing", "args": {"aircraft_name": "highAR", "run_name": "AR 13.0"}},
  {"tool": "log_decision", "args": {"decision_type": "result_interpretation",
    "reasoning": "AR 13 trades ~360 lbm mission fuel for a small wing-mass penalty; gross mass nearly unchanged"}},
  {"tool": "export_session_graph", "args": {}}
]
```

Notes:

- Load a **separate named aircraft** per variant rather than mutating one:
  overrides accumulate on an aircraft across `define_aircraft` calls.
- Override values: bare numbers use the metadata default units; pass
  `[value, "units"]` to be explicit, e.g.
  `{"aircraft:design:gross_mass": [150000, "lbm"]}`.
- Unknown names error with close matches -- e.g. misspelling
  `aspect_ratioo` suggests `aircraft:wing:aspect_ratio`.
- For 1-D sweeps over a deck variable, prefer the study layer
  (`hangar.avy.study_runner` registers the `avy` runner; see
  `hangar-study`).
