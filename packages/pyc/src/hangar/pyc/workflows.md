# pyCycle MCP Server -- Workflow Guide

## Workflow 1: Design-Point Sizing

1. `start_session(notes="Turbojet design point")`
2. `create_engine(archetype="turbojet", comp_PR=13.5, comp_eff=0.83, turb_eff=0.86)`
3. `log_decision(decision_type="archetype_selection", reasoning="...")`
4. `run_design_point(alt=0, MN=0.000001, Fn_target=11800, T4_target=2370)`
5. `log_decision(decision_type="result_interpretation", reasoning="...", prior_call_id=...)`
6. `visualize(run_id, "performance_summary")`
7. `export_session_graph()`

## Workflow 2: Design + Off-Design (Throttle Hook)

1. `start_session(notes="Off-design study")`
2. `create_engine(archetype="turbojet")`
3. `run_design_point(alt=0, MN=0.000001, Fn_target=11800, T4_target=2370)`
4. `run_off_design(alt=0, MN=0.000001, Fn_target=11000)` -- part power
5. `run_off_design(alt=35000, MN=0.8, Fn_target=4000)` -- cruise
6. `visualize(run_id, "design_vs_offdesign")`
7. `log_decision(decision_type="result_interpretation", reasoning="TSFC trend with throttle...")`
8. `export_session_graph()`

## Workflow 3: Component Sensitivity Comparison

1. `start_session(notes="comp_PR sensitivity")`
2. `create_engine(archetype="turbojet", name="baseline", comp_PR=13.5)`
3. `create_engine(archetype="turbojet", name="high_pr", comp_PR=16.0)`
4. `run_design_point(engine_name="baseline", run_name="PR 13.5")`
5. `run_design_point(engine_name="high_pr", run_name="PR 16.0")`
6. Compare TSFC/OPR between the two run envelopes
7. `log_decision(decision_type="result_interpretation", reasoning="...")`
8. `export_session_graph()`

## Tips

* SLS conditions: `alt=0, MN=0.000001` (near-zero Mach, never exactly 0).
* Keep `T4_target` below ~3600 degR (material limits).
* `thermo_method="TABULAR"` is ~10x faster than CEA with similar accuracy for Jet-A.
* Check `validation.passed` in every envelope before trusting results.
