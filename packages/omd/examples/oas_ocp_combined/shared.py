"""Shared constants for the OAS + OCP combined example.

Runs an OAS VLM wing analysis at cruise conditions alongside an
OCP Caravan basic mission in a single composite Problem.
"""

# OAS wing geometry (Caravan-like rectangular wing)
WING = dict(
    name="wing",
    wing_type="rect",
    num_x=2,
    num_y=7,
    span=15.87,        # m (Caravan wingspan)
    root_chord=1.64,   # m
    symmetry=True,
    with_viscous=True,
    CD0=0.015,
)

# Flight conditions for the OAS analysis point
FLIGHT = dict(
    velocity=66.4,       # m/s (~129 kn, Caravan cruise)
    alpha=3.0,           # deg
    Mach_number=0.194,
    re=1.0e6,            # 1/m
    rho=1.225,           # kg/m^3 (sea level ISA -- simplified)
)

# OCP mission parameters
AIRCRAFT = dict(template="caravan")
MISSION = dict(
    cruise_altitude_ft=18000.0,
    mission_range_NM=250.0,
    climb_vs_ftmin=850.0,
    climb_Ueas_kn=104.0,
    cruise_Ueas_kn=129.0,
    descent_vs_ftmin=400.0,
    descent_Ueas_kn=100.0,
    num_nodes=11,
)

# Tolerances for parity testing
TOL_CD = dict(rtol=1e-6)
TOL_FUEL = dict(rtol=1e-4)
