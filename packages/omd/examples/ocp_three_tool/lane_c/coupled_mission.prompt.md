# Task: Three-Tool B738 Mission Analysis

Run a Boeing 737-800 basic mission (climb / cruise / descent) through
the omd plan pipeline with both an OAS VLM surrogate for drag (in
place of the default parabolic polar) and a pyCycle HBTF surrogate for
propulsion (in place of the default CFM56).

## Requirements

- Component type: `ocp/BasicMission`
- Aircraft: built-in template `b738` (MTOW 79,002 kg, 124.6 m^2 wing)
- Drag slot: `oas/vlm`, 2 × 7 mesh, 4 twist control points
- Propulsion slot: `pyc/surrogate` with the HBTF archetype, design at
  35,000 ft, M = 0.8, Fn = 5,900 lbf, T4 = 2,857 °R, TABULAR thermo
- Mission: 1,500 NM range, 35,000 ft cruise
- Climb: 2,000 ft/min at 250 KEAS
- Cruise: 460 KEAS
- Descent: 1,500 ft/min at 250 KEAS

## Tools

- `omd-cli` for plan authoring, assembly, execution, results query,
  and provenance.
- `/omd-cli-guide` skill for plan structure and the decision-logging
  contract. Load `slots-and-fidelity.md` for slot composition (drag +
  propulsion together; dual-surrogate caveats), `ocp-specifics.md` for
  OCP solver tuning, and `pycycle-specifics.md` for the HBTF design
  point and thermo settings.

## Deliverables

1. Assembled plan under `hangar_studies/<plan-id>/` and a successful
   `omd-cli run --mode analysis`.
2. Reported `fuel_burn_kg`, `OEW_kg`, `MTOW_kg`, and per-phase
   profiles (altitude, speed, thrust, drag, fuel flow, weight).
3. `decisions.yaml` entries:
   - `formulation_decision` documenting both slot choices, the mesh /
     design-point fidelity, and the nonlinear-solver choice required
     by composing two surrogates.
   - `result_interpretation` covering whether fuel burn and OEW / MTOW
     are consistent with a 737-800 on a 1,500 NM mission.
4. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
