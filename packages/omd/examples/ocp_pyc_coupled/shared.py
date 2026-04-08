"""Shared constants for the OCP + pyCycle coupled mission example.

OCP Caravan basic mission with pyCycle turbojet propulsion via the
slot system. The pyCycle turbojet replaces the default turboprop
propulsion model.

Note: a turbojet is not realistic for a Caravan, but this example
demonstrates the propulsion slot mechanism. The absolute values are
not physically meaningful for this airframe.
"""

# pyCycle turbojet config for the propulsion slot
PYC_CONFIG = dict(
    design_alt=18000.0,    # ft -- match cruise altitude
    design_MN=0.35,        # match Caravan cruise Mach
    design_Fn=4000.0,      # lbf -- sized for Caravan-class drag
    design_T4=2370.0,      # degR
    thermo_method="TABULAR",
    engine_params={},
)

# OCP mission parameters (same Caravan profile)
MISSION = dict(
    cruise_altitude_ft=18000.0,
    mission_range_NM=250.0,
    climb_vs_ftmin=850.0,
    climb_Ueas_kn=104.0,
    cruise_Ueas_kn=129.0,
    descent_vs_ftmin=400.0,
    descent_Ueas_kn=100.0,
    num_nodes=3,     # kept small due to pyCycle per-node cost
)

# Fields removed from aircraft data when pyCycle replaces turboprop
PYC_REMOVES_FIELDS = [
    "ac|propulsion|engine|rating",
    "ac|propulsion|propeller|diameter",
]

# No additional fields needed for pyCycle slot
PYC_ADDS_FIELDS = {}

# Tolerances for parity testing (Lane A vs Lane B)
TOL_FUEL = dict(rtol=1e-3)
