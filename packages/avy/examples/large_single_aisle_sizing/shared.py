"""Shared constants for the large single-aisle (737-class) sizing parity example.

Single source of truth across Lane A (raw Aviary Level 1) and Lane B (MCP
tool-call script). A second airframe/deck exercising the same wrapper paths
as single_aisle_sizing: the large_single_aisle_1 FLOPS deck (the aircraft
behind the upstream FwFm benchmark family) on the default energy_state
mission with a 2500 nmi range constraint.
"""

TEMPLATE = "large_single_aisle_FLOPS"
DECK = "models/aircraft/large_single_aisle_1/large_single_aisle_1_FLOPS.csv"

TARGET_RANGE_NM = 2500.0

OPTIMIZER = "SLSQP"
MAX_ITER = 50

TOL_PARITY = dict(rel=1e-6)
TOL_RANGE = dict(rel=1e-6)

# Pinned from Aviary v1.0.1 (SLSQP, default energy_state mission @ 2500 nmi).
GOLDEN = dict(
    gross_mass_lbm=162887.82,
    total_fuel_mass_lbm=28602.23,
    range_nmi=2500.0,
    final_time_min=385.24,
)
TOL_GOLDEN = dict(rel=2e-3)

METRICS = ["gross_mass_lbm", "total_fuel_mass_lbm", "range_nmi", "final_time_min"]
