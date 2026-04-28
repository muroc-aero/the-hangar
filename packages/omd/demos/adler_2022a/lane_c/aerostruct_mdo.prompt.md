# Lane C prompt: Adler 2022a aerostructural MDO

You are reproducing Adler & Martins (2022a, "Aerostructural wing
design optimization considering full mission analysis"). The full demo
already exists at `packages/omd/demos/adler_2022a/`; use it as a
reference. Your job is to re-create the four `lane_b` plans from
scratch (without reading them) using the omd-cli-guide skill, then
run the coarse sweep, render the figures, and compare against the
paper.

## Plan inventory (write each YAML by hand)

Four plans, all under `lane_b/<method>/plan.yaml`:

1. **mission_based**: `ocp/BasicMission` with the B738 template,
   `twin_turbofan` architecture, and four slots:
   - `drag` -> `oas/aerostruct` with surface grid `num_y=7, num_x=3,
     num_twist=4, num_toverc=4, num_skin=4, num_spar=4`.
   - `propulsion` -> `pyc/surrogate` with HBTF archetype designed at
     `(35,000 ft, M=0.78, Fn=5900 lbf, T4=2857 R)`.
   - `weight` -> `ocp/parametric-weight` with `use_wing_weight: true`.
   - `maneuver` -> `oas/maneuver` with `load_factor=2.5, mach=0.78,
     altitude_ft=20000`.
   - Cruise at 35,000 ft, M=0.78. NLBGS solver (dual-surrogate
     coupling).
   - Objective: `descent.fuel_used_final`.
   - Constraint: `failure_maneuver <= 0`.
2. **single_point**: `oas/AerostructBreguet` with `mode:
   single_cruise_breguet`, one cruise flight point at (M=0.78,
   35,000 ft, weight_fraction=0.5). Supply `MTOW_kg`,
   `tsfc_g_per_kN_s`, `orig_W_wing_kg`, `payload_kg`, and the
   `maneuver` block explicitly (the factory has no aircraft
   defaults).
3. **multipoint**: same component, `mode: averaged_cruise_breguet`,
   five flight points (Mach 0.78 +/- 0.01, altitude 35000 +/- 1000 ft).
4. **single_point_plus_climb**: same component, `mode:
   cruise_plus_climb_breguet`, two flight points (climb halfway around
   M=0.55 / 17,500 ft / gamma=3 deg, cruise at M=0.78 / 35,000 ft).

The paper's three "method" names map to the three Bréguet modes:
``single_point`` -> ``single_cruise_breguet``,
``multipoint`` -> ``averaged_cruise_breguet``,
``single_point_plus_climb`` -> ``cruise_plus_climb_breguet``.

All four share 14 wingbox DVs (AR <= 10.4, sweep, taper, twist 4 cps
with tip locked, t/c 4 cps >= 0.03, skin/spar 4 cps each >= 3 mm) and
the constraint `2_5g_KS_failure <= 0` (the Bréguet variants alias
this from `failure_maneuver`).

Use SLSQP with `maxiter=150, tol=1e-6`.

## Run

```bash
uv run omd-cli validate <each plan>
uv run python sweep.py --grid coarse --workers 4
uv run python plotting.py --figures all
uv run python compare.py --figures all
```

## What "done" looks like

- All four plans validate.
- `sweep.py --grid coarse` produces a 16-row CSV with all cells
  converged (warm-start with `retry_failed.py` if any fail).
- `plotting.py` produces fig7.png, fig9.png, fig10.png, fig11.png,
  fig12.png, fig13.png in `figures/reproduced/`.
- `compare.py` produces side-by-side comparison PNGs and the trend in
  Fig 7 (mission-based < multipoint < single point on short missions)
  is reproduced.

If you hit convergence problems, consult
`packages/omd/CLAUDE.md` known-failure-mode notes and the
`oas-known-squawks` skill.
