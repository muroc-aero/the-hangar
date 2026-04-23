# Lane C: agent prompt for Brelje 2018a hybrid MDO

Assemble and run an omd plan that reproduces one grid cell of Brelje
2018a Fig 5 (minimum fuel-burn MDO) at a King Air C90GT series-hybrid
aircraft with `mission_range_NM=500` and `battery_specific_energy=450`.

## What to build

1.  A single-component `ocp/FullMission` plan using the `kingair`
    template with `twin_series_hybrid` propulsion and `num_nodes: 11`.
    Set mission params to match: cruise 29000 ft, climb 1500 ft/min at
    124 kn, cruise at 170 kn, descent 600 ft/min at 140 kn, 1000 lb
    payload.
2.  10 design variables with the Brelje paper bounds:
    - `ac|weights|MTOW` kg in [4000, 5700]
    - `ac|geom|wing|S_ref` m^2 in [15, 40]
    - `ac|propulsion|engine|rating` hp in [1, 3000]
    - `ac|propulsion|motor|rating` hp in [450, 3000]
    - `ac|propulsion|generator|rating` hp in [1, 3000]
    - `ac|weights|W_battery` kg in [20, 2250]
    - `ac|weights|W_fuel_max` kg in [500, 3000]
    - `cruise.hybridization` in [0.001, 0.999]
    - `climb.hybridization` in [0.001, 0.999]
    - `descent.hybridization` in [0.01, 1.0]
3.  Scalar constraints:
    - `margins.MTOW_margin >= 0`
    - `rotate.range_final <= 1357` (BFL 4452 ft)
    - `v0v1.Vstall_eas <= 42` (Vstall <= 81.6 kn)
    - `descent.propmodel.batt1.SOC_final >= 0`
    - `engineoutclimb.gamma >= 0.02`
4.  Vector constraints (length = num_nodes):
    - `climb.throttle <= 1.05`
    - Component sizing margins for `eng1`, `gen1`, `batt1` on `climb`,
      `cruise`, `descent` <= 1.0
    - `v0v1.propmodel.batt1.component_sizing_margin <= 1.0`
5.  Objective: `mixed_objective` (fuel + MTOW/100 kg, wired by the
    factory for hybrid architectures).
6.  Optimizer: SLSQP, 150 iterations, tol 1e-6.

## Then

Run with `omd-cli run <plan.yaml> --mode optimize`.  Expect the
optimizer to converge at MTOW on its upper bound (5700 kg), BFL and
Vstall active at their upper bounds, and cruise hybridization around
70%.  The converged `mixed_objective` should be near 233 kg.

For Fig 6, set `include_cost_model: true` on the mission component
config, change the objective to `doc_per_nmi`, and rerun.
