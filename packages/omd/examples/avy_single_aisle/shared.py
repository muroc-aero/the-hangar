"""Shared constants for the omd-level Aviary single-aisle sizing parity case.

Single source of truth across Lane A (the per-tool avy Lane A script,
executed in .venv-avy), Lane B (the omd plan through the avy/Sizing
subprocess factory), and Lane C (the omd tool surface). The engineering
problem is IDENTICAL to packages/avy/examples/single_aisle_sizing/ --
same deck, same default energy_state mission at 1906 nmi, SLSQP/50 --
so the goldens are the same numbers.

All lanes need the isolated Aviary venv (scripts/setup-avy-venv.sh);
tests skip when .venv-avy is absent.
"""

DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"
PHASE_INFO_MODULE = "aviary.models.missions.energy_state_default"
TARGET_RANGE_NM = 1906.0
OPTIMIZER = "SLSQP"
MAX_ITER = 50

# B/C run the same subprocess worker Lane A's script mirrors -> round-off.
TOL_PARITY = dict(rel=1e-6)

# Pinned from Aviary v1.0.1 (same anchors as the per-tool example).
GOLDEN = dict(
    gross_mass_lbm=116423.45,
    total_fuel_mass_lbm=13813.96,
    range_nmi=1906.0,
    final_time_min=300.69,
)
TOL_GOLDEN = dict(rel=2e-3)

METRICS = ["gross_mass_lbm", "total_fuel_mass_lbm", "range_nmi", "final_time_min"]
