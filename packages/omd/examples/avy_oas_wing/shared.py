"""Shared constants for the omd-level OAS-in-Aviary wing-mass parity case.

The engineering problem is IDENTICAL to
packages/avy/examples/single_aisle_oas_wing/ -- the advanced single aisle
on upstream's OAS-example mission (fixed profile, 1800 nmi) with the
FLOPS wing weight replaced by the OAS wingbox sub-optimization -- run
through the omd lanes: Lane A subprocess-runs the per-tool raw-upstream
reference in .venv-avy; Lane B feeds the ``external_subsystems`` config
through the ``avy/Sizing`` subprocess factory (the sub-opt runs inside
the worker, where openaerostruct lives).

All lanes need .venv-avy with openaerostruct installed
(scripts/setup-avy-venv.sh); tests skip when it is absent.
"""

DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"
PHASE_INFO_MODULE = "hangar.avy.config.missions_oas_wing"
SUBSYSTEM = "oas_wing_mass"
OPTIMIZER = "SLSQP"
MAX_ITER = 60

TOL_PARITY = dict(rel=1e-6)

# Pinned from Aviary v1.0.1 + OAS v2.12.0 (same anchors as the per-tool
# example -- one engineering problem, one set of goldens).
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
