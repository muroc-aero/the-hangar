# OpenConcept MCP Server -- Workflow Guide

## Workflow 1: Basic Turboprop Mission Analysis

1. `start_session(notes="Caravan mission analysis")`
2. `load_aircraft_template("caravan")`
3. `set_propulsion_architecture("turboprop")`
4. `configure_mission(cruise_altitude=18000, mission_range=250)`
5. `run_mission_analysis()`
6. `log_decision(decision_type="result_interpretation", reasoning="...")`
7. `export_session_graph()`

## Workflow 2: Hybrid-Electric Trade Study

1. `start_session(notes="Hybrid trade study")`
2. `load_aircraft_template("kingair")`
3. `set_propulsion_architecture("twin_series_hybrid", battery_specific_energy=450)`
4. `configure_mission(cruise_altitude=29000, mission_range=500, cruise_hybridization=0.05, payload=1000)`
5. `run_mission_analysis(run_name="baseline")` -- baseline
6. `run_parameter_sweep(parameter="hybridization", values=[0.0, 0.05, 0.1, 0.15, 0.2, 0.3])`
7. `log_decision(decision_type="result_interpretation", reasoning="optimal hybridization is...")`
8. `export_session_graph()`

## Workflow 3: Design Optimization

1. `start_session(notes="Hybrid optimization")`
2. `load_aircraft_template("kingair")`
3. `set_propulsion_architecture("twin_series_hybrid", battery_specific_energy=450)`
4. `configure_mission(cruise_altitude=29000, mission_range=500, payload=1000)`
5. `log_decision(decision_type="dv_selection", reasoning="...")`
6. `run_optimization(objective="mixed_objective", design_variables=[...], constraints=[...])`
7. `log_decision(decision_type="convergence_assessment", reasoning="...")`
8. `export_session_graph()`

## Workflow 4: Architecture Comparison

1. `start_session(notes="Architecture comparison")`
2. `load_aircraft_template("kingair")`

**Run A: Turboprop baseline**
3. `set_propulsion_architecture("twin_turboprop")`
4. `configure_mission(mission_range=250)`
5. `run_mission_analysis(run_name="turboprop_baseline")`

**Run B: Hybrid**
6. `set_propulsion_architecture("twin_series_hybrid")`
7. `configure_mission(mission_range=250, cruise_hybridization=0.1)`
8. `run_mission_analysis(run_name="hybrid_10pct")`

**Compare**
9. `log_decision(decision_type="result_interpretation", reasoning="comparing fuel burn...")`
10. `export_session_graph()`
