"""Shared constants for the omd-level OAS-in-Aviary wing-mass parity case.

The engineering problem is IDENTICAL to
packages/avy/examples/single_aisle_oas_wing/ -- the advanced single aisle
on upstream's OAS-example mission (fixed profile, 1800 nmi) with the
FLOPS wing weight replaced by the OAS wingbox sub-optimization -- run
through the omd lanes: Lane A imports and runs the per-tool raw-upstream
reference in-process; Lane B feeds the ``external_subsystems`` config
through the native ``avy/Sizing`` factory (the hangar.avy registry builds
the sub-opt inside the AviaryGroup, in the omd process).

Aviary and openaerostruct both live in the workspace venv
(bash scripts/dev-setup.sh); tests skip when aviary is not installed.
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
