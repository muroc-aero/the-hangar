"""Default parameters for Aviary sizing runs."""

# The pip-installable optimizer. IPOPT/SNOPT (pyoptsparse) are accepted when
# present but are never the default -- see runner.check_optimizer_available.
DEFAULT_OPTIMIZER = "SLSQP"

DEFAULT_MAX_ITER = 50

DEFAULT_MISSION_METHOD = "energy_state"

DEFAULT_TEMPLATE = "advanced_single_aisle"
