# Example: Off-Design Missions from a Sized Aircraft

Fly the sized single-aisle on missions it was NOT designed for. Both
off-design tools fly from the last converged `run_sizing` of the aircraft
when the configuration still matches; without one (as below, where no
run_sizing precedes them) they re-run the sizing internally first (~2x
wall-clock).

```json
[
  {"tool": "start_session", "args": {"notes": "Off-design study"}},
  {"tool": "load_aircraft_template", "args": {"template": "advanced_single_aisle"}},
  {"tool": "run_off_design", "args": {"mission_type": "max_range",
    "run_name": "how far at design TOGM"}},
  {"tool": "run_off_design", "args": {"mission_type": "min_fuel",
    "mission_range_nm": 1200, "run_name": "fuel for a 1200 nmi leg"}},
  {"tool": "export_session_graph", "args": {}}
]
```

Reading the envelopes:

- `results.performance` describes the OFF-DESIGN mission (its range, its
  fuel); `results.design_point` carries the sizing headline metrics for
  comparison -- check `design_point.optimizer_success` too.
- `max_range`: fixed fuel/gross mass, the optimizer maximizes range --
  "how far can this airplane fly at design TOGM?"
- `min_fuel`: fixed range (via `mission_range_nm`), minimizes fuel -- "how
  little fuel does a 1200 nmi leg take?" Expect slightly MORE fuel than an
  aircraft freshly resized for 1200 nmi (the airframe is the heavier
  1906-design one).

Payload-range diagram (sizing + 2 more off-design missions, ~3x):

```bash
avy-cli run-payload-range --run-name "PR diagram"
avy-cli visualize --run-id <run_id> --plot-type payload_range --output file
```

`results.payload_range.points` has the four classic points: max payload @
zero range, the design mission, max fuel + payload, and ferry range.
