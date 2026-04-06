"""Shared constants for the OCP hybrid twin mission example."""

AIRCRAFT = dict(template="kingair")

MISSION = dict(
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

PROPULSION = dict(
    architecture="twin_series_hybrid",
    battery_specific_energy=450,
)

TOL_FUEL = dict(rtol=1e-4)
TOL_OEW = dict(rtol=0.05)
TOL_TOFL = dict(rtol=0.05)
