"""Shared constants for the OCP three-tool coupled mission example.

OCP B738 basic mission with both slots filled:
- Drag: OAS VLM surrogate (VLMDragPolar)
- Propulsion: pyCycle HBTF surrogate (PyCycleSurrogateGroup)

B738 + HBTF is a physically matched combination: a 737-class
narrowbody with a CFM56-class high-bypass turbofan.
"""

# VLM mesh parameters for the drag slot
VLM_CONFIG = dict(
    num_x=2,
    num_y=7,       # must be odd
    num_twist=4,
)

# pyCycle HBTF surrogate config for the propulsion slot
# Uses TABULAR thermo for fast deck generation (~5 min vs ~150 min for CEA)
PYC_SURR_CONFIG = dict(
    archetype="hbtf",
    design_alt=35000.0,     # ft -- typical cruise altitude
    design_MN=0.8,          # cruise Mach
    design_Fn=5900.0,       # lbf per engine -- cruise thrust
    design_T4=2857.0,       # degR
    engine_params={"thermo_method": "TABULAR"},
)

# Direct-coupled HBTF config (for Lane B2)
PYC_DIRECT_CONFIG = dict(
    design_alt=35000.0,
    design_MN=0.8,
    design_Fn=5900.0,
    design_T4=2857.0,
    thermo_method="TABULAR",
)

# OCP mission parameters -- B738-class mission
MISSION = dict(
    cruise_altitude_ft=35000.0,
    mission_range_NM=1500.0,
    climb_vs_ftmin=2000.0,
    climb_Ueas_kn=250.0,
    cruise_Ueas_kn=460.0,
    descent_vs_ftmin=1500.0,
    descent_Ueas_kn=250.0,
    num_nodes=3,
)

# OEW from the factory's _B738_DATA
B738_OEW_KG = 41871.0

# Fields removed by VLM drag slot
VLM_REMOVES_FIELDS = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
]

# Fields removed by pyc/surrogate propulsion slot
PYC_SURR_REMOVES_FIELDS = [
    "ac|propulsion|engine|rating",
]

# Combined removes (union of both slots)
ALL_REMOVES_FIELDS = VLM_REMOVES_FIELDS + PYC_SURR_REMOVES_FIELDS

# Fields added by VLM drag slot
VLM_ADDS_FIELDS = {
    "ac|aero|CD_nonwing": 0.0145,
}

# Tolerances for parity testing
TOL_FUEL = dict(rtol=1e-3)
