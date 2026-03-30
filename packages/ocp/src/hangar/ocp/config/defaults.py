"""Default mission parameters, solver settings, and propulsion architecture registry."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Default mission parameters (Caravan-like single turboprop mission)
# ---------------------------------------------------------------------------

DEFAULT_MISSION_PARAMS: dict = {
    "mission_type": "full",
    "cruise_altitude_ft": 18000.0,
    "mission_range_NM": 250.0,
    # Climb
    "climb_vs_ftmin": 850.0,
    "climb_Ueas_kn": 104.0,
    # Cruise
    "cruise_vs_ftmin": 0.01,
    "cruise_Ueas_kn": 129.0,
    # Descent
    "descent_vs_ftmin": -400.0,
    "descent_Ueas_kn": 100.0,
    # Payload (only used for hybrid/reserve missions)
    "payload_lb": None,
    # Hybridization fractions (only used for hybrid architectures)
    "climb_hybridization": None,
    "cruise_hybridization": None,
    "descent_hybridization": None,
}

# ---------------------------------------------------------------------------
# Default solver settings
# ---------------------------------------------------------------------------

DEFAULT_SOLVER_SETTINGS: dict = {
    "maxiter": 20,
    "atol": 1e-10,
    "rtol": 1e-10,
    "solve_subsystems": True,
}

# ---------------------------------------------------------------------------
# Propulsion architecture registry
# ---------------------------------------------------------------------------
# Each entry maps an architecture name to its OpenConcept class info.
# Fields:
#   prop_class  : propulsion system class name
#   prop_module : module path for the propulsion system
#   weight_class: empty weight model class name (None = manual)
#   weight_module: module path for the weight model
#   required_ac_fields: aircraft data fields that must be present
#   has_fuel    : whether the architecture burns fuel
#   has_battery : whether the architecture uses batteries
#   num_engines : number of engines (for weight/connection logic)

PROPULSION_ARCHITECTURES: dict[str, dict] = {
    "turboprop": {
        "prop_class": "TurbopropPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "SingleTurboPropEmptyWeight",
        "weight_module": "openconcept.weights",
        "required_ac_fields": [
            "ac|propulsion|engine|rating",
            "ac|propulsion|propeller|diameter",
        ],
        "has_fuel": True,
        "has_battery": False,
        "num_engines": 1,
    },
    "twin_turboprop": {
        "prop_class": "TwinTurbopropPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "SingleTurboPropEmptyWeight",
        "weight_module": "openconcept.weights",
        "required_ac_fields": [
            "ac|propulsion|engine|rating",
            "ac|propulsion|propeller|diameter",
        ],
        "has_fuel": True,
        "has_battery": False,
        "num_engines": 2,
    },
    "series_hybrid": {
        "prop_class": "SingleSeriesHybridElectricPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "TwinSeriesHybridEmptyWeight",
        "weight_module": "openconcept.weights",
        "required_ac_fields": [
            "ac|propulsion|engine|rating",
            "ac|propulsion|propeller|diameter",
            "ac|propulsion|motor|rating",
            "ac|propulsion|generator|rating",
            "ac|weights|W_battery",
        ],
        "has_fuel": True,
        "has_battery": True,
        "num_engines": 1,
    },
    "twin_series_hybrid": {
        "prop_class": "TwinSeriesHybridElectricPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "TwinSeriesHybridEmptyWeight",
        "weight_module": "openconcept.weights",
        "required_ac_fields": [
            "ac|propulsion|engine|rating",
            "ac|propulsion|propeller|diameter",
            "ac|propulsion|motor|rating",
            "ac|propulsion|generator|rating",
            "ac|weights|W_battery",
        ],
        "has_fuel": True,
        "has_battery": True,
        "num_engines": 2,
    },
    "twin_turbofan": {
        "prop_class": "CFM56",
        "prop_module": "openconcept.propulsion",
        "weight_class": None,
        "weight_module": None,
        "required_ac_fields": [
            "ac|propulsion|engine|rating",
        ],
        "has_fuel": True,
        "has_battery": False,
        "num_engines": 2,
    },
}


# ---------------------------------------------------------------------------
# Mission phase lists by mission type
# ---------------------------------------------------------------------------

FULL_MISSION_PHASES = ["v0v1", "v1vr", "v1v0", "rotate", "climb", "cruise", "descent"]
BASIC_MISSION_PHASES = ["climb", "cruise", "descent"]
TAKEOFF_PHASES = ["v0v1", "v1vr", "v1v0", "rotate"]
