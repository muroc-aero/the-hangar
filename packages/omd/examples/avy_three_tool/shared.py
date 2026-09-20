"""Shared constants for the Aviary + OAS + pyCycle three-tool parity case.

The advanced single aisle sized on upstream's OAS-example mission (fixed
profile, 1800 nmi) with two of Aviary's empirical models replaced by
physics tools:

- wing mass: the FLOPS wing weight -> an OpenAeroStruct wingbox
  sub-optimization inside Aviary's pre-mission (Aviary's own external
  subsystem seam; identical to ``avy_oas_wing``);
- engine: the ``turbofan_22k`` file deck -> a pyCycle high-bypass turbofan
  off-design sweep tabulated as an in-memory Aviary EngineDeck. pyCycle
  sets the engine's lapse and SFC over the envelope; Aviary scales the
  deck to the airframe's 22,200 lbf SLS rating exactly as it scales any
  deck (``engine_deck.scale_factor`` in the summary says by how much).

Lane A runs the raw Aviary level-2 sequence with upstream's
``OASWingMassBuilder`` and the pyCycle deck; Lane B threads
``external_subsystems`` and ``engine_deck`` through the native
``avy/Sizing`` factory; Lane C reaches the same config through the omd
plan tools. The pyCycle sweep (80 points, ~4-5 min) is cached under
``<HANGAR_DATA_DIR>/pyc_decks/`` keyed on ENGINE_DECK + pyCycle version,
so the lanes share one deck and only the first run pays for it.
"""

DECK = "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"
PHASE_INFO_MODULE = "hangar.avy.config.missions_oas_wing"
SUBSYSTEM = "oas_wing_mass"
OPTIMIZER = "SLSQP"
MAX_ITER = 60

# The pyCycle engine: the hangar HBTF archetype at its CFM56-class design
# point (5,900 lbf at 35 kft / M 0.8, T4 2857 R), tabular thermo, swept
# over the transport envelope (see hangar.omd.pyc.aviary_deck).
ENGINE_DECK = {
    "provider": "pyc/hbtf",
    "config": {
        "design_alt_ft": 35000.0,
        "design_MN": 0.8,
        "design_Fn_lbf": 5900.0,
        "design_T4_degR": 2857.0,
        "engine_params": {"thermo_method": "TABULAR"},
        "grid": {
            "alt_ft": [0.0, 10000.0, 20000.0, 30000.0, 37000.0],
            "MN": [0.0, 0.25, 0.5, 0.8],
            "throttle": [0.5, 0.7, 0.85, 1.0],
        },
    },
}

TOL_PARITY = dict(rel=1e-6)

# Pinned from Aviary v1.0.1 + OAS v2.12.0 + pyCycle 4.4.1 (this stack).
# The wing mass and block time equal the avy_oas_wing goldens (14539.33 lbm,
# 290.23 min): the OAS sub-opt does not see the engine and the profile is
# fixed. Fuel goes 13812.16 -> 14541.58 lbm and gross 122876.48 -> 129273.59
# lbm: the pyCycle HBTF, scaled x1.370 from its 16,201 lbf SLS to the
# airframe's 22,200 lbf, burns ~5% more than the turbofan_22k deck.
GOLDEN = dict(
    gross_mass_lbm=129273.59,
    total_fuel_mass_lbm=14541.58,
    wing_mass_lbm=14539.33,
    range_nmi=1800.0,
    final_time_min=290.23,
    engine_scale_factor=1.3703,
)
TOL_GOLDEN = dict(rel=2e-3)

METRICS = [
    "gross_mass_lbm",
    "total_fuel_mass_lbm",
    "wing_mass_lbm",
    "range_nmi",
    "final_time_min",
    "engine_scale_factor",
]
