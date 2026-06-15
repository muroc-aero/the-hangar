# Example: MTOW sizing and a battery sensitivity sweep

Goal: converge the vehicle's maximum takeoff weight, then see how sized MTOW
responds to battery specific energy.

## Sizing (MTOW convergence)

`sizing.json`:

```json
[
  {"tool": "start_session", "args": {"notes": "test_all sizing"}},
  {"tool": "load_vehicle_template", "args": {"template": "test_all"}},
  {"tool": "run_sizing", "args": {"run_name": "baseline_mtow"}},
  {"tool": "visualize", "args": {"run_id": "$prev.run_id", "plot_type": "mtow_convergence", "output": "file"}},
  {"tool": "export_session_graph", "args": {}}
]
```

```bash
evt-cli --pretty run-script sizing.json
```

Expected (test_all baseline):

```
results.sized_mtow_kg = 4076.0876  kg
results.iterations    = 37
results.converged     = true
```

Always check `results.converged` and the `mtow.converged` validation finding.
A diverging iteration fails the tool outright (evtolpy's safeguard); a
returned-but-not-converged result is flagged as an error finding -- never a
silent pass. Divergence usually means self-inconsistent inputs (wingspan, rotor
count/diameter, battery/EPU scaling, or mission energy).

## Battery specific-energy sweep on sized MTOW

```bash
evt-cli load-vehicle-template --template test_all
evt-cli --pretty run-parameter-sweep \
    --param power.batt_spec_energy_w_h_p_kg \
    --values '[200, 260, 320]' \
    --metric sized_mtow_kg
evt-cli plot latest sweep
```

`sized_mtow_kg` converges MTOW at each point (slower than the other metrics).
Sized MTOW falls as battery specific energy rises (less battery mass for the
same energy), so the curve should decrease monotonically. Points that diverge
are recorded with a null metric and an `error` note rather than aborting the
sweep -- inspect `results.points` for any nulls.

## Other useful sweeps

```bash
# Cruise duration vs total mission energy (no sizing -- fast)
evt-cli run-parameter-sweep --param mission.cruise_s \
    --values '[500, 600, 700, 800]' --metric total_mission_energy_kw_hr

# Rotor diameter vs disk loading
evt-cli run-parameter-sweep --param propulsion.rotor_diameter_m \
    --values '[1.8, 2.0, 2.2, 2.4]' --metric disk_loading_kg_p_m2
```
