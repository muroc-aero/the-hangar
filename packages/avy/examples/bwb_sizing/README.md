# bwb_sizing -- Aviary parity example (blended wing body, upstream benchmark)

The upstream BWB benchmark (`aviary/validation_cases/benchmark_tests/
test_bwb_FwFm.py`) brought into the parity lanes: the `bwb_simple_FLOPS`
deck (~875 klb class) on the M0.85 / 7750 nmi transpacific mission.

The upstream benchmark optimizes the mach/altitude profile and requires
SNOPT/IPOPT (SLSQP does not converge it -- verified). Both lanes therefore
run a **fixed-profile adaptation** of the benchmark mission (optimization
flags off, climb pinned 500 ft/M0.3 -> 35000 ft/M0.85), which SLSQP
converges in ~12 s:

- **Lane A** (`lane_a/sizing.py`): raw Aviary Level 1, adapting the
  upstream phase_info inline.
- **Lane B** (`lane_b/sizing.json`): `mission_template="bwb_fixed"`
  (`hangar.avy.config.missions_bwb_fixed`, the same adaptation derived
  programmatically from the upstream module).

Anchoring is two-level: Lane A is pinned to our recorded SLSQP goldens at
`rel=2e-3` AND cross-checked against the **published upstream SNOPT
values** (gross 782,430 lbm / fuel 239,188 lbm) at `rel=2e-2` -- the fixed
profile lands ~0.4% heavier on gross and ~1.2% on fuel, and the test also
asserts it can never *beat* the profile-optimized fuel burn.

Run (inside `.venv-avy`; see `scripts/setup-avy-venv.sh`):

```bash
.venv-avy/bin/python -m pytest packages/avy/examples/bwb_sizing/tests/ -v --rootdir=.
```

## Why there is no GwFm (GASP-mass) example

The GwFm benchmark deck rejects the default mission's aero options (GASP
aero requires its own mission), and its benchmark mission -- plus every
fixed-profile adaptation we tried -- fails to converge under SLSQP
(range collapses to zero). The `bench_GwFm` aircraft template and
`GwFm_bench` mission template remain available for pyoptsparse users; a
parity example follows if/when a CI leg has IPOPT.
