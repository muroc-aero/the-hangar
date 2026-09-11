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

# OCP mission parameters -- B738-class mission.
#
# Climb and descent rates decay with altitude, following OpenConcept's own
# B738 examples. A CONSTANT 2000 ft/min climb to FL350 was tried here and is
# outside this aircraft's envelope: top of climb demands 75 kN while the
# engine pair can make 52 kN, so the throttle balance has no root and Newton
# cannot converge however good the solver is. Likewise a constant -1500
# ft/min descent to sea level demands negative thrust at the bottom.
#
# Two-element [start, end] values are expanded with np.linspace over the
# phase's nodes -- the same convention omd's `_phase_array` uses, so Lane A
# and Lane B build identical profiles from identical numbers.
MISSION = dict(
    cruise_altitude_ft=35000.0,
    mission_range_NM=1500.0,
    climb_vs_ftmin=[2300.0, 600.0],
    climb_Ueas_kn=[230.0, 220.0],
    cruise_Ueas_kn=256.0,   # EAS for M0.80 at 35,000 ft (was 460, a TAS value)
    descent_vs_ftmin=[1000.0, 150.0],
    descent_Ueas_kn=250.0,
    num_nodes=3,
)


def phase_array(nn, value):
    """Expand a mission param to a per-node array.

    Mirrors ``hangar.omd.factories.ocp.mission_values._phase_array`` so the
    two lanes cannot drift apart on profile shape.
    """
    import numpy as np

    if isinstance(value, (list, tuple)):
        if len(value) == 2:
            return np.linspace(float(value[0]), float(value[1]), nn)
        return np.array(value, dtype=float)
    return np.ones((nn,)) * float(value)

# OEW from the factory's _B738_DATA
B738_OEW_KG = 41871.0

# The B738 is a twin. pyCycle slot providers model ONE engine, so both lanes
# scale by this; it must match PROPULSION_ARCHITECTURES["twin_turbofan"].
N_ENGINES = 2

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
