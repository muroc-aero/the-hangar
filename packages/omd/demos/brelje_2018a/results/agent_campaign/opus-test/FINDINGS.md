# Agent test arm `opus-test` (2026-09-28)

One seed, six cells per figure, run unsandboxed with
`stats/agent_campaign.py run --arm opus-test --cells 300,400 300,700
500,450 500,650 700,600 800,300 --workers 3` (default model, 150-turn cap).
Cells span the truth regimes: all-electric, mixed, fuel-dominant and the
switch point. Every design is effect-graded by re-scoring the named run's
design variables in upstream HybridTwin (`upstream_truth.rescore_design`).

12 runs, 1.64 h wall clock, $31.18 in total ($1.05-4.34 per cell,
33-103 turns).

| cell | fig 5 (truth) | fig 5 agent | fig 6 (truth) | fig 6 agent |
|---|---|---|---|---|
| 300 / 400 | 95.92 | 49.89, infeasible | 0.5140 | 0.5608, feasible, +9.1 % |
| 300 / 700 | 41.90 | 40.16, infeasible | 0.2634 | 0.4171, infeasible |
| 500 / 450 | 324.9 | no report, no feasible run | 0.6596 | 0.6596, matched |
| 500 / 650 | 155.6 | 155.64, matched | 0.4297 | 0.2750, infeasible |
| 700 / 600 | 491.1 | 347.2, infeasible | 0.6641 | 0.5487, infeasible |
| 800 / 300 | 664.0 | 570.3, infeasible | 0.7190 | 0.7519, feasible, +4.6 % |

(fig 5 objective: fuel + MTOW/100 in kg; fig 6: DOC in $/nmi.)

Feasible and at the truth optimum: 2/12. Feasible but in a worse local
optimum: 2/12. Infeasible in upstream: 7/12. No gradable run: 1/12.

## Why the designs are infeasible

All seven infeasible designs violate one constraint, the MTOW margin, by
520-970 lb. Their objectives are *below* truth: they are lighter aircraft
than the paper problem allows. The cause is the paper's hybrid-variant
structural weight factor (2.0 instead of the stock 1.6). In upstream the
margin uses the cruise-phase OEW (`analysis.cruise.acmodel.OEW.const.
structural_fudge`), and the agents could not reliably set it through omd:

- `operating_points` and `aircraft_data` entries for
  `ac|weights|structural_fudge`, propeller diameter and engine rating pass
  `validate_plan` and are then silently ignored at run time.
- `initial_values` silently accepts unknown names, and does not apply in
  analysis mode, so the agents had to find the path by probing.
- Agents that set it on all eight phases (`analysis.<phase>.acmodel.OEW.
  const.structural_fudge`) produced feasible designs; agents that set only
  `climb.OEW.structural_fudge`, or could not set it at all, optimized the
  stock airframe and the upstream re-score rejects the result.

So in this test the failure mode is tool discoverability of one input, not
the MDO itself: where the problem was posed correctly the agents matched
truth or found the other local optimum.

Other repeated friction (from the agents' JSON reports):

- `run_plan` in optimize mode exceeds the 60 s MCP client timeout; the run
  continues server-side and is found via `get_provenance` and polled.
- `get_results(summary=true)` returns about 310k characters and cannot be
  read; there is no final-case-only option.
- `plan_add_dv` accepts nonexistent DV names; there is no constraint
  builder tool, so constraints are written as raw YAML.
- `include_cost_model` coefficients cannot be inspected, so fig 6 agents
  could not confirm the cost model matches the paper's.
- Unscaled SLSQP stalls on the cost objective; agents that added `ref`
  scaling reached better optima.
- A spurious "1 driver iteration" warning fires at `recording_level=minimal`.

Statistics: `stats/fig5/summary.md`, `stats/fig6/summary.md` (from
`collect_stats.py --agent opus-test=... --agent-fig opus-test=<fig>`).
