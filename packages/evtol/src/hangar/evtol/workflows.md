# evtol Workflows

## Mission energy/power/mass analysis

```
start_session(notes="eVTOL mission analysis")
load_vehicle_template(template="test_all")
log_decision(decision_type="architecture_choice", reasoning="...")
run_mission_analysis()
log_decision(decision_type="result_interpretation", reasoning="...", prior_call_id=...)
visualize(run_id, "segment_energy")
export_session_graph()
```

`run_mission_analysis` reads the aircraft at the as-configured MTOW (it does not
size). Inspect the cruise vs hover energy split, `totals.total_mission_energy_kw_hr`,
and any validation warnings (battery mass fraction, disk loading).

## MTOW sizing

```
start_session(notes="MTOW sizing")
load_vehicle_template(template="test_all")
run_sizing()
visualize(run_id, "mtow_convergence")
export_session_graph()
```

`run_sizing` runs evtolpy's MTOW iteration starting from the configured initial
MTOW. If the inputs are physically self-inconsistent the iteration diverges and
the tool fails with a USER_INPUT_ERROR naming the likely culprits.

## Overriding parameters

```
load_vehicle_template(template="test_all")
set_power(params={"batt_spec_energy_w_h_p_kg": 280.0})
set_propulsion(params={"rotor_count": 8})
configure_mission(params={"cruise_s": 720.0})
run_mission_analysis()
```

Each setter validates keys against the section schema -- a typo is rejected with
a suggestion rather than silently ignored.

## Parameter sweep

```
load_vehicle_template(template="test_all")
run_parameter_sweep(
    param="power.batt_spec_energy_w_h_p_kg",
    values=[200, 240, 280, 320],
    metric="sized_mtow_kg",
)
visualize(run_id, "sweep")
```

Metrics: `total_mission_energy_kw_hr`, `total_reserve_mission_energy_kw_hr`,
`battery_mass_kg`, `empty_mass_kg`, `cruise_l_p_d`,
`cruise_avg_electric_power_kw`, `disk_loading_kg_p_m2`, `sized_mtow_kg`.
`sized_mtow_kg` converges MTOW per point; points that diverge are recorded with
a null metric rather than aborting the sweep.

## Concluding a study

```
set_requirements(requirements=[
  {"label": "energy budget", "path": "totals.total_mission_energy_kw_hr",
   "operator": "<", "value": 200},
])
run_mission_analysis()
record_conclusion(run_id, narrative="Mission energy is within budget because ...")
```
