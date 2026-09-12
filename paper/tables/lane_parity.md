<!-- generated from paper/results/lane_parity.jsonl at 2026-07-17T00:23:31+00:00 (git ac32a6f, pytest exit 0) Lane C (agent): effect-graded values from the sandboxed claude-opus-5 arm over 3 seeds, worst seed per metric, so the column bounds agreement; per-seed pass rates are in sandboxed_evals. A case the arm has not run shows -- rather than a value from another run. -->
| Example | Tools | Metric | Lane A | Lane B | rel diff B | Lane C (scripted) | rel diff C | Lane C (agent) | rel diff agent |
|---|---|---|---|---|---|---|---|---|---|
| Paraboloid analysis | OpenMDAO | f_xy | 39 | 39 | 0 | 39 | 0 | 39 | 0 |
| Paraboloid optimization | OpenMDAO/SLSQP | x | 6.66667 | -- | -- | -- | -- | 6.66667 | 3.7e-08 |
|  |  | y | -7.33333 | -- | -- | -- | -- | -7.33333 | 5.3e-08 |
|  |  | f_xy | -27.3333 | -27.3333 | 0 | -27.3333 | 0 | -27.3333 | 4.4e-15 |
| Rect wing VLM analysis | OAS | CL | 0.452177 | 0.452177 | 0 | 0.452177 | 0 | 0.452177 | 0 |
|  |  | CD | 0.0350873 | 0.0350873 | 0 | 0.0350873 | 0 | 0.0341362 | 2.7e-02 |
| Rect wing aerostructural | OAS (tube FEM) | CL | 0.480648 | 0.480648 | 0 | 0.480648 | 0 | 0.480648 | 0 |
|  |  | CD | 0.0359044 | 0.0359044 | 0 | 0.0359044 | 0 | 0.0359044 | 0 |
| Caravan 3-phase mission | OCP | fuel_burn_kg | 171.309 | 171.309 | 0 | 171.309 | 0 | 171.309 | 7.9e-07 |
|  |  | OEW_kg | 2267.46 | 2267.46 | 0 | 2267.46 | 0 | 2267.46 | 0 |
|  |  | MTOW_kg | 3970 | 3970 | 0 | 3970 | 0 | 3970 | 0 |
| Caravan full mission (BFL) | OCP | fuel_burn_kg | 172.321 | 172.321 | 0 | 172.321 | 0 | 172.321 | 0 |
|  |  | OEW_kg | 2267.46 | 2267.46 | 0 | 2267.46 | 0 | 2267.46 | 0 |
|  |  | MTOW_kg | 3970 | 3970 | 0 | 3970 | 0 | 3970 | 0 |
| King Air series-hybrid mission | OCP | fuel_burn_kg | 391.894 | 391.894 | 0 | 391.894 | 0 | 391.894 | 0 |
|  |  | OEW_kg | 2969.39 | 2969.39 | 0 | 2969.39 | 0 | 2969.39 | 0 |
|  |  | MTOW_kg | 4581 | 4581 | 0 | 4581 | 0 | 4581 | 0 |
| Wing + mission, uncoupled composite | OAS + OCP | wing_CL | 0.269813 | 0.269813 | 0 | 0.269813 | 0 | 0.269813 | 0 |
|  |  | wing_CD | 0.027667 | 0.027667 | 0 | 0.027667 | 0 | 0.027667 | 1.3e-16 |
|  |  | fuel_burn_kg | 171.309 | 171.309 | 0 | 171.309 | 0 | 171.309 | 7.9e-07 |
|  |  | OEW_kg | 2267.46 | 2267.46 | 0 | 2267.46 | 0 | 2267.46 | 0 |
|  |  | MTOW_kg | 3970 | 3970 | 0 | 3970 | 0 | 3970 | 0 |
| Mission w/ VLM drag slot | OCP + OAS | fuel_burn_kg | 136.923 | 136.923 | 0 | 136.923 | 0 | 136.923 | 0 |
|  |  | OEW_kg | 2267.46 | 2267.46 | 0 | 2267.46 | 0 | 2267.46 | 0 |
|  |  | MTOW_kg | 3970 | 3970 | 0 | 3970 | 0 | 3970 | 0 |
| Mission w/ direct-coupled VLM drag | OCP + OAS | fuel_burn_kg | 135.177 | 135.177 | 0 | 135.177 | 0 | 135.177 | 1.2e-06 |
|  |  | OEW_kg | 2267.46 | 2267.46 | 0 | 2267.46 | 0 | 2267.46 | 0 |
|  |  | MTOW_kg | 3970 | 3970 | 0 | 3970 | 0 | 3970 | 0 |
| Turbojet design point | pyCycle | Fn | 11800 | 11800 | 0 | 11800 | 0 | 11800 | 0 |
|  |  | TSFC | 0.782231 | 0.782231 | 0 | 0.782231 | 0 | 0.782231 | 0 |
|  |  | OPR | 13.5 | 13.5 | 0 | 13.5 | 0 | 13.5 | 0 |
| Archer Midnight eVTOL sizing | evt (native) | sized_mtow_kg | 2019.47 | 2019.47 | 0 | 2019.47 | 0 | 2019.47 | 0 |
|  |  | total_mission_energy_kw_hr | 65.9496 | 65.9496 | 0 | 65.9496 | 0 | 65.9496 | 0 |
|  |  | peak_power_kw | 846.521 | 846.521 | 0 | 846.521 | 0 | 846.521 | 0 |
| B738 three-tool mission | OCP + OAS + pyCycle | fuel_burn_kg | 2449.7 | 2449.7 | 3.9e-15 | 2449.7 | 1.2e-14 | -- | -- |
|  |  | OEW_kg | 41871 | 41871 | 0 | 41871 | 0 | -- | -- |
|  |  | MTOW_kg | 79002 | 79002 | 0 | 79002 | 0 | -- | -- |
