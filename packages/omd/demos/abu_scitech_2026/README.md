# AIAA SciTech 2026 eVTOL case study -- omd reproduction

Reproduces the non-ABU case study from `packages/evt/examples/abu_scitech_2026`
through the **omd** pipeline, using the `evt/Sizing` factory (a black-box
OpenMDAO wrapper around evtolpy). Same 18 vendored configs (3 vehicles x 2
altitudes x 3 ranges), same numbers, driven declaratively as an omd study.

## Layout

- `plan/base_plan.yaml` -- one `evt/Sizing` component. `config_dir` points at the
  evt example's `cfg/` dir; `config_name` selects a vendored config (overridden
  per case by the study).
- `study/abu_study.yaml` -- single matrix axis over the 18 case names, bound to
  `components[evtol].config.config_name`.
- `compare_to_golden.py` -- checks the study's per-case outputs against the
  Lane-A ground truth (`../../../evt/examples/abu_scitech_2026/results/case_study_grid.csv`).

## Run (from the repo root)

```bash
omd-cli study review packages/omd/demos/abu_scitech_2026/study/abu_study.yaml
omd-cli study run    packages/omd/demos/abu_scitech_2026/study/abu_study.yaml --max-cases 3   # pilot
omd-cli study run    packages/omd/demos/abu_scitech_2026/study/abu_study.yaml --yes           # all 18
python packages/omd/demos/abu_scitech_2026/compare_to_golden.py
```

Per-run plots (`segment_energy`, `segment_power`, `mass_breakdown`,
`mtow_convergence`) are available on any single run:

```bash
omd-cli run  packages/omd/demos/abu_scitech_2026/plan/base_plan.yaml --mode analysis
omd-cli plot <run_id> --type all
```

## Fidelity

- **Mission energy and peak power**: reproduce the grid exactly (read at the
  as-configured MTOW, matching evtolpy's `log_mission_segment_*` scripts and the
  paper's own method). `compare_to_golden.py` reports max relative delta 0.000%.
- **Sized MTOW**: matches the Lane-A grid (same `_iterate_mtow` loop). The
  standalone example documents an upstream resizing-loop drift vs the paper;
  that drift is upstream, not in this wrapper.
- **Joby S4 60-mile (1500 and 3000 ft)**: evtolpy's MTOW loop diverges upstream.
  These two cases fail with an explicit divergence error rather than passing
  silently -- the same behavior the evt lanes record as `converged=False`.

## Notes

`evt/Sizing` is a black box: evtolpy is gradient-free, so the component declares
finite-difference partials. For gradient-based coupled MDO, see the native
OpenMDAO rewrite plan in `packages/evt/docs/native-openmdao-rewrite-upstream-plan.md`.
