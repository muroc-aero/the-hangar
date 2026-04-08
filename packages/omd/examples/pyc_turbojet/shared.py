"""Single source of truth for the turbojet multi-lane example.

All lanes import parameters and tolerances from here.
"""

from hangar.omd.pyc.defaults import (
    DEFAULT_TURBOJET_PARAMS as ENGINE_PARAMS,
    DEFAULT_TURBOJET_DESIGN_GUESSES as DESIGN_GUESSES,
    DEFAULT_TURBOJET_OD_GUESSES as OD_GUESSES,
    DEFAULT_DESIGN_CONDITIONS as DESIGN_POINT,
    TURBOJET_META,
)

OFF_DESIGN_POINTS = [
    dict(name="OD0", alt=0.0, MN=0.000001, Fn_target=11000.0),
    dict(name="OD1", alt=5000.0, MN=0.2, Fn_target=8000.0),
]

ELEMENT_MN = dict(
    inlet_MN=0.60,
    comp_MN=0.02,
    burner_MN=0.02,
    turb_MN=0.4,
)

# Tolerances for parity comparison
TOL_PERFORMANCE = dict(rtol=1e-4)
TOL_OFF_DESIGN = dict(rtol=5e-4)
TOL_FLOW_STATION = dict(rtol=1e-3)
TOL_COMPONENT = dict(rtol=1e-3)
