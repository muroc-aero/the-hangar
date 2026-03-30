"""Shared constants for Caravan mission demonstration.

Single source of truth for parameters used across Lane A (raw OpenConcept),
Lane B (MCP / ocp-cli), and the parity tests.
"""

# ── Aircraft data ────────────────────────────────────────────────────────
# Cessna 208 Caravan (from openconcept/examples/aircraft_data/caravan.py)
AIRCRAFT = dict(
    CLmax_TO=2.25,
    e=0.8,
    CD0_TO=0.033,
    CD0_cruise=0.027,
    S_ref=26.0,         # m^2
    AR=9.69,
    c4sweep=1.0,        # deg
    taper=0.625,
    toverc=0.19,
    MTOW=3970,          # kg
    W_fuel_max=1018,    # kg
    MLW=3358,           # kg
    engine_rating=675,  # hp
    propeller_diameter=2.1,  # m
)

# ── Mission parameters ──────────────────────────────────────────────────
MISSION_BASIC = dict(
    mission_type="basic",
    cruise_altitude_ft=18000.0,
    mission_range_NM=250.0,
    climb_vs_ftmin=850.0,
    climb_Ueas_kn=104.0,
    cruise_Ueas_kn=129.0,
    descent_vs_ftmin=400.0,  # positive; tool negates internally
    descent_Ueas_kn=100.0,
    num_nodes=11,
)

MISSION_FULL = dict(
    **{k: v for k, v in MISSION_BASIC.items() if k != "mission_type"},
    mission_type="full",
)

# ── Hybrid trade study parameters ───────────────────────────────────────
HYBRID_AIRCRAFT = dict(
    template="kingair",
)

HYBRID_MISSION = dict(
    mission_type="full",
    cruise_altitude_ft=29000.0,
    mission_range_NM=500.0,
    climb_vs_ftmin=1500.0,
    climb_Ueas_kn=124.0,
    cruise_Ueas_kn=170.0,
    descent_vs_ftmin=600.0,
    descent_Ueas_kn=140.0,
    num_nodes=11,
    cruise_hybridization=0.058,
    payload_lb=1000.0,
)

HYBRID_PROPULSION = dict(
    architecture="twin_series_hybrid",
    battery_specific_energy=450,  # Wh/kg
)

SWEEP_VALUES = [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]

# ── Tolerances for parity tests ─────────────────────────────────────────
TOL_FUEL = dict(rtol=1e-4)          # Fuel burn (kg)
TOL_OEW = dict(rtol=0.03)           # OEW (structural fudge causes ~2.7% diff in some paths)
TOL_SCALARS = dict(rtol=1e-3)       # General scalar results
TOL_TOFL = dict(rtol=0.05)          # TOFL (different reference points possible)
