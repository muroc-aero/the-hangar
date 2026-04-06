"""Shared constants for the OCP Caravan full mission example."""

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

TOL_FUEL = dict(rtol=1e-4)
TOL_OEW = dict(rtol=0.03)
TOL_TOFL = dict(rtol=0.05)
