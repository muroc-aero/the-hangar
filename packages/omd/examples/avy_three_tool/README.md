# avy_three_tool -- Aviary + OAS + pyCycle coupled sizing

The three-tool composition that runs today (the OpenConcept one,
`ocp_three_tool`, is deactivated pending PR #88). The advanced single
aisle is sized on upstream's OAS-example mission (fixed profile, 1800
nmi) with two of Aviary's empirical models replaced by physics tools:

| Slot | Aviary default | Replaced by | Seam |
|------|----------------|-------------|------|
| Wing mass | FLOPS wing weight | OpenAeroStruct wingbox sub-optimization in Aviary's pre-mission | `external_subsystems: [{name: oas_wing_mass}]` (Aviary `SubsystemBuilder`, hangar.avy registry) |
| Engine | `turbofan_22k.csv` file deck | pyCycle high-bypass turbofan off-design sweep, tabulated as an in-memory Aviary `EngineDeck` | `engine_deck: {provider: pyc/hbtf, ...}` (`hangar.omd.pyc.aviary_deck`) |

pyCycle sets the engine's lapse and SFC over the envelope; Aviary reads
the reference SLS thrust off the pyCycle table and scales the deck to the
airframe's 22,200 lbf rating exactly as it scales any file deck
(`engine_deck.scale_factor` in the summary). Everything sits inside one
`AviaryGroup`, inside one omd problem, under one SLSQP driver.

Lanes:

- **A** -- `lane_a/coupled_sizing.py`: raw Aviary level-2 sequence,
  upstream's `OASWingMassBuilder` with the upstream example's `set_val`
  block verbatim, the pyCycle deck from `hangar.omd.pyc.aviary_deck`.
- **B** -- `lane_b/coupled_sizing/plan.yaml`: the same problem as an
  `avy/Sizing` component (`external_subsystems` + `engine_deck`).
- **C** -- `lane_c/coupled_sizing.prompt.md`: closed prompt for the omd
  plan tools; scripted parity in `examples/tests/test_parity_lane_c.py`.

The pyCycle sweep is 80 points at ~3 s each and is cached under
`<HANGAR_DATA_DIR>/pyc_decks/` keyed on the engine spec + pyCycle version,
so the first lane pays ~4-5 min and the others load it. The sizing itself
takes ~2 min per lane (nested wingbox sub-opt). Tests skip when `aviary`
is not installed (`bash scripts/dev-setup.sh`).

Deck hygiene, because it bit once: pyCycle's HBTF reports whatever its
balances hold when a Newton solve stalls (stale guesses, 1e14 lbf), so the
sweep now runs the cycle solvers with `err_on_non_converge` and drops
those points, Mach 0 is evaluated as pyCycle's 1e-6 static convention,
and a deck whose thrust is not strictly increasing with throttle at any
flight condition is refused before Aviary sees it (the flight-idle
extrapolation would otherwise divide by zero). Conditions the archetype
cannot converge (Mach 0.25 above 30 kft) simply drop out of the table.

```bash
uv run python packages/omd/examples/avy_three_tool/lane_a/coupled_sizing.py
uv run omd-cli run packages/omd/examples/avy_three_tool/lane_b/coupled_sizing/plan.yaml --mode optimize
uv run pytest packages/omd/examples/tests/test_parity.py -k AvyThreeTool -v -s
```
