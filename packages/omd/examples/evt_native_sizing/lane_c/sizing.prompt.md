# Task: Native eVTOL MTOW Sizing

Size an Archer Midnight lift+cruise eVTOL through the omd plan pipeline using
the **native** OpenMDAO formulation of evtolpy (the `evt/Sizing` factory), and
report the sized takeoff mass and mission energy.

## Requirements

- Component type: `evt/Sizing` (the native, gradient-capable path -- this is
  the default; do **not** set `native: false`, which selects the legacy
  finite-difference black box).
- Vehicle config: the vendored AIAA SciTech 2026 case
  `archer-midnight-1500-30`, loaded from
  `packages/evt/examples/abu_scitech_2026/cfg` (set `config_dir` +
  `config_name`; the factory appends `.json`).
- MTOW-closure solver: `newton` (the native model's default, analytic
  complex-step partials).
- Run omd from the repo root so the repo-root-relative `config_dir` resolves.

## Tools

- `omd-cli` for plan authoring, assembly, validation, execution, results
  query, provenance, and plot generation.
- `/omd-cli-guide` skill for plan structure and the decision-logging contract.

## Deliverables

1. Assembled plan and a successful `omd-cli run --mode analysis`.
2. Reported `sized_mtow_kg`, `total_mission_energy_kw_hr`, and `peak_power_kw`
   from the run summary.
3. `decisions.yaml` entries:
   - `formulation_decision` documenting the config case, the native vs
     black-box choice, and the closure solver.
   - `result_interpretation` noting whether the sized MTOW is plausible for a
     ~2-tonne-class eVTOL on this mission.
4. The MTOW-convergence and mass-breakdown plots via `omd-cli plot <run_id>`.
5. Provenance timeline via `omd-cli provenance <plan_id> --format text`.
