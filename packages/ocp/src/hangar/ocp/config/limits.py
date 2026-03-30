"""Parameter validation bounds for OpenConcept MCP tools."""

from __future__ import annotations

# Wing loading (MTOW / S_ref) in kg/m^2
WING_LOADING_MIN = 30.0
WING_LOADING_MAX = 1000.0

# Power loading (MTOW / engine_total_rating) in kg/hp
POWER_LOADING_MIN = 1.0
POWER_LOADING_MAX = 50.0

# Battery specific energy in Wh/kg
BATTERY_SPEC_ENERGY_MIN = 50.0
BATTERY_SPEC_ENERGY_MAX = 600.0

# Mission parameters
CRUISE_ALTITUDE_MIN_FT = 1000.0
CRUISE_ALTITUDE_MAX_FT = 51000.0
MISSION_RANGE_MIN_NM = 5.0
MISSION_RANGE_MAX_NM = 10000.0

# Climb vertical speed in ft/min
CLIMB_VS_MIN = 100.0
CLIMB_VS_MAX = 6000.0

# Airspeed in knots
AIRSPEED_MIN_KN = 30.0
AIRSPEED_MAX_KN = 600.0

# num_nodes must be 2N+1 for Simpson's rule
NUM_NODES_MIN = 3
NUM_NODES_MAX = 101

# Takeoff field length in ft
TOFL_MAX_FT = 15000.0

# Throttle bound
THROTTLE_MAX = 1.10

# Design variable bounds for optimization
DV_MTOW_LOWER_KG = 500.0
DV_MTOW_UPPER_KG = 200000.0
DV_SREF_LOWER_M2 = 5.0
DV_SREF_UPPER_M2 = 500.0
DV_ENGINE_RATING_LOWER_HP = 10.0
DV_ENGINE_RATING_UPPER_HP = 50000.0
DV_BATTERY_WEIGHT_LOWER_KG = 1.0
DV_BATTERY_WEIGHT_UPPER_KG = 10000.0
DV_HYBRIDIZATION_LOWER = 0.001
DV_HYBRIDIZATION_UPPER = 0.999
