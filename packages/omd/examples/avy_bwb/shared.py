"""Shared constants for the omd-level Aviary BWB sizing parity case.

Identical engineering problem to packages/avy/examples/bwb_sizing/ (the
upstream BWB benchmark deck on the fixed-profile M0.85 / 7750 nmi mission,
SLSQP) through the omd avy/Sizing subprocess factory. The mission comes
from hangar.avy.config.missions_bwb_fixed -- importable in the worker
because hangar-avy is installed in .venv-avy.

Tests skip when .venv-avy is absent (scripts/setup-avy-venv.sh).
"""

DECK = "models/aircraft/blended_wing_body/bwb_simple_FLOPS.csv"
PHASE_INFO_MODULE = "hangar.avy.config.missions_bwb_fixed"
OPTIMIZER = "SLSQP"
MAX_ITER = 60  # the upstream benchmark's budget

TOL_PARITY = dict(rel=1e-6)

# Pinned from Aviary v1.0.1 (same anchors as packages/avy/examples/bwb_sizing).
GOLDEN = dict(
    gross_mass_lbm=785679.46,
    total_fuel_mass_lbm=242073.51,
    operating_mass_lbm=445793.95,
    range_nmi=7750.0,
    final_time_min=994.87,
)
TOL_GOLDEN = dict(rel=2e-3)

METRICS = [
    "gross_mass_lbm",
    "total_fuel_mass_lbm",
    "operating_mass_lbm",
    "range_nmi",
    "final_time_min",
]
