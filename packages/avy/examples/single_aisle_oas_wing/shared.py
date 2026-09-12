"""Shared constants for the OAS-in-Aviary wing-mass parity example.

The engineering problem: the advanced single aisle sized on upstream's
OAS-example mission (3 fixed-profile phases, 1800 nmi), with the empirical
FLOPS wing weight replaced by an OpenAeroStruct wingbox sub-optimization
(upstream Aviary's own external-subsystem integration).

Lane A: raw upstream -- OASWingMassBuilder + the Level-3 sequence with the
example's post-setup set_val block. Lane B: the hangar tool surface
(add_external_subsystem + run_sizing), whose builder feeds the identical
values through an IndepVarComp instead. Same component, same numbers.

The coupled and precompute subsystem modes are *exactly* equivalent for
this subsystem (feed-forward topology, measured bit-identical -- see
docs/aviary-oas-integration-plan.md WP1), so both are asserted against the
same Lane A oracle.
"""

TEMPLATE = "advanced_single_aisle"
DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"

# The mission upstream pairs with the OAS example (single copy lives in
# hangar.avy.config.missions_oas_wing; Lane A imports it from there too).
MISSION_TEMPLATE = "oas_wing_example"
TARGET_RANGE_NM = 1800.0

OPTIMIZER = "SLSQP"
MAX_ITER = 60

TOL_PARITY = dict(rel=1e-6)
TOL_RANGE = dict(rel=1e-6)

# Golden anchors recorded from Aviary v1.0.1 + OAS v2.12.0 (SLSQP,
# converged, 9 outer iterations, single nested sub-opt).
GOLDEN = dict(
    gross_mass_lbm=122876.48,
    total_fuel_mass_lbm=13812.16,
    wing_mass_lbm=14539.33,
    range_nmi=1800.0,
    final_time_min=290.23,
)
TOL_GOLDEN = dict(rel=2e-3)

METRICS = [
    "gross_mass_lbm",
    "total_fuel_mass_lbm",
    "wing_mass_lbm",
    "range_nmi",
    "final_time_min",
]

# The integration must actually move the wing mass: the OAS wingbox and
# the FLOPS estimate for this deck differ by well over this margin.
MIN_WING_MASS_CONTRAST_REL = 0.03
