"""Shared constants for the blended-wing-body sizing parity example.

Single source of truth across Lane A (raw Aviary Level 1) and Lane B (MCP
tool-call script). Derived from the upstream BWB benchmark
(``aviary/validation_cases/benchmark_tests/test_bwb_FwFm.py``): same deck,
same M0.85 / 7750 nmi transpacific mission, with the mach/altitude
optimization turned off (fixed profile) so SLSQP converges it -- the
upstream benchmark itself requires SNOPT/IPOPT.

Both lanes build the identical fixed-profile mission: Lane A adapts the
upstream phase_info inline; Lane B uses mission_template='bwb_fixed'
(hangar.avy.config.missions_bwb_fixed applies the same adaptation).
"""

TEMPLATE = "bwb_FLOPS"
DECK = "models/aircraft/blended_wing_body/bwb_simple_FLOPS.csv"

MISSION_TEMPLATE = "bwb_fixed"
# The fixed-profile adaptation (must match hangar.avy.config.missions_bwb_fixed)
CLIMB_MACH_FINAL = 0.85
CLIMB_ALT_FINAL_FT = 35000.0

OPTIMIZER = "SLSQP"
MAX_ITER = 60  # the upstream benchmark's budget

TOL_PARITY = dict(rel=1e-6)
TOL_RANGE = dict(rel=1e-6)

# Pinned from Aviary v1.0.1 under SLSQP with the fixed profile.
GOLDEN = dict(
    gross_mass_lbm=785679.46,
    total_fuel_mass_lbm=242073.51,
    operating_mass_lbm=445793.95,
    range_nmi=7750.0,
    final_time_min=994.87,
)
TOL_GOLDEN = dict(rel=2e-3)

# The published upstream benchmark values (test_bwb_FwFm.py, SNOPT,
# mach/altitude-OPTIMIZED profile). Our fixed-profile SLSQP solution should
# land close but slightly heavier -- not optimizing the profile costs a
# little fuel. This anchors Lane A to the upstream benchmark itself, one
# level stronger than our own recorded goldens.
UPSTREAM_SNOPT = dict(
    gross_mass_lbm=782430.3,
    total_fuel_mass_lbm=239188.4,
    operating_mass_lbm=445429.9,
    range_nmi=7750.0,
)
TOL_UPSTREAM = dict(rel=0.02)

METRICS = [
    "gross_mass_lbm",
    "total_fuel_mass_lbm",
    "operating_mass_lbm",
    "range_nmi",
    "final_time_min",
]
