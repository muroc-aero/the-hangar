# avy workflows

Step-by-step recipes for common Aviary tasks. Always begin with
`start_session` and end with `export_session_graph`.

## 1. Baseline sizing

```
start_session(notes="Baseline single-aisle sizing")
load_aircraft_template(template="advanced_single_aisle")
log_decision(decision_type="architecture_choice", reasoning="...")
run_sizing()                       # default energy_state mission
# check validation.checks: optimizer.success MUST pass
log_decision(decision_type="result_interpretation", prior_call_id=..., reasoning="...")
visualize(run_id, "mission_profile")
export_session_graph()
```

## 2. Sizing to a requirement

```
start_session(notes="Sizing vs MTOW requirement")
set_requirements([{"label": "MTOW", "path": "performance.gross_mass_lbm",
                   "operator": "<", "value": 175000}])
load_aircraft_template(template="large_single_aisle_FLOPS")
configure_mission(target_range_nm=2500)
run_sizing(run_name="2500 nmi design mission")
record_conclusion(run_id, narrative="...")
export_session_graph()
```

## 3. Design-range sensitivity (two designs)

```
start_session(notes="Range sensitivity")
load_aircraft_template(template="advanced_single_aisle", name="short")
load_aircraft_template(template="advanced_single_aisle", name="long")
configure_mission(aircraft_name="short", target_range_nm=1500)
configure_mission(aircraft_name="long",  target_range_nm=2500)
run_sizing(aircraft_name="short", run_name="1500 nmi")
run_sizing(aircraft_name="long",  run_name="2500 nmi")
# compare performance.gross_mass_lbm / total_fuel_mass_lbm across the two envelopes
log_decision(decision_type="result_interpretation", reasoning="...")
export_session_graph()
```

## 4. Deck-variable override study

```
start_session(notes="Aspect ratio study")
load_aircraft_template(template="advanced_single_aisle")
run_sizing(run_name="baseline")
define_aircraft(overrides={"aircraft:wing:aspect_ratio": 12.0})
run_sizing(run_name="AR 12")
visualize(run_id, "mass_breakdown")
export_session_graph()
```

## 5. Off-design missions from a sized aircraft

```
start_session(notes="Off-design study")
load_aircraft_template(template="advanced_single_aisle")
run_sizing(run_name="design mission")
run_off_design(mission_type="max_range", run_name="ferry-ish: how far at design TOGM")
run_off_design(mission_type="min_fuel", mission_range_nm=1200,
               run_name="short leg: fuel for 1200 nmi")
# compare results.performance vs results.design_point in each envelope
log_decision(decision_type="result_interpretation", reasoning="...")
export_session_graph()
```

## 6. Payload-range diagram

```
start_session(notes="Payload-range")
load_aircraft_template(template="advanced_single_aisle")
run_payload_range(run_name="PR diagram")
visualize(run_id, "payload_range")
export_session_graph()
```

## Failure playbook

- `optimizer.success` finding failed: increase `max_iter`, simplify the
  mission (fewer segments, no takeoff/landing), or check deck overrides for
  inconsistent inputs. The returned numbers are the last iterate, NOT a
  converged design.
- `Unknown Aviary variable` from define_aircraft: use the exact
  `aircraft:...`/`mission:...` metadata names; the error lists close matches.
- `IPOPT/SNOPT requires pyoptsparse`: use SLSQP, or install pyoptsparse via
  build_pyoptsparse in the avy venv.
- 2DOF template rejected: only energy_state missions run through this server
  today; pick a FLOPS/energy_state template.
