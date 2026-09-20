"""Shared constants for the omd-level Aviary single-aisle sizing parity case.

Single source of truth across Lane A (the per-tool avy Lane A script,
imported and run in-process), Lane B (the omd plan through the native
avy/Sizing factory, mode=optimize), and Lane C (the omd tool surface).
The engineering problem is IDENTICAL to
packages/avy/examples/single_aisle_sizing/ -- same deck, same default
energy_state mission at 1906 nmi, SLSQP/50 -- so the goldens are the
same numbers.

Aviary lives in the workspace venv (bash scripts/dev-setup.sh); tests
skip when it is not installed.
"""

DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"
PHASE_INFO_MODULE = "aviary.models.missions.energy_state_default"
TARGET_RANGE_NM = 1906.0
OPTIMIZER = "SLSQP"
MAX_ITER = 50

# B/C build the same AviaryGroup Lane A's script drives -> round-off.
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
