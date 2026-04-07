"""Shared constants for the OCP + OAS coupled mission example.

OCP Caravan basic mission with OAS VLM drag in the loop via the
slot system. VLMDragPolar replaces PolarDrag in each flight phase.
"""

# VLM mesh parameters for the drag slot
VLM_CONFIG = dict(
    num_x=2,
    num_y=7,       # must be odd
    num_twist=4,
)

# OCP mission parameters (same Caravan profile as uncoupled example)
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

# Fields removed from aircraft data when VLM replaces PolarDrag
VLM_REMOVES_FIELDS = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
]

# Fields added for VLM
VLM_ADDS_FIELDS = {
    "ac|aero|CD_nonwing": 0.0145,
}

# Tolerances for parity testing (relaxed -- VLM adds solver noise)
TOL_FUEL = dict(rtol=1e-3)
