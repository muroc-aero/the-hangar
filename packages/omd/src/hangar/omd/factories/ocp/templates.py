"""Built-in aircraft template data for OpenConcept missions."""

from __future__ import annotations


_CARAVAN_DATA: dict = {
    "ac": {
        "aero": {
            "CLmax_TO": {"value": 2.25},
            "polar": {
                "e": {"value": 0.8},
                "CD0_TO": {"value": 0.033},
                "CD0_cruise": {"value": 0.027},
            },
        },
        "geom": {
            "wing": {
                "S_ref": {"value": 26.0, "units": "m**2"},
                "AR": {"value": 9.69},
                "c4sweep": {"value": 1.0, "units": "deg"},
                "taper": {"value": 0.625},
                "toverc": {"value": 0.19},
            },
            "fuselage": {
                "S_wet": {"value": 490, "units": "ft**2"},
                "width": {"value": 1.7, "units": "m"},
                "length": {"value": 12.67, "units": "m"},
                "height": {"value": 1.73, "units": "m"},
            },
            "hstab": {
                "S_ref": {"value": 6.93, "units": "m**2"},
                "c4_to_wing_c4": {"value": 7.28, "units": "m"},
            },
            "vstab": {"S_ref": {"value": 3.34, "units": "m**2"}},
            "nosegear": {"length": {"value": 0.9, "units": "m"}},
            "maingear": {"length": {"value": 0.92, "units": "m"}},
        },
        "weights": {
            "MTOW": {"value": 3970, "units": "kg"},
            "OEW": {"value": 2145, "units": "kg"},
            "W_fuel_max": {"value": 1018, "units": "kg"},
            "MLW": {"value": 3358, "units": "kg"},
        },
        "propulsion": {
            "engine": {"rating": {"value": 675, "units": "hp"}},
            "propeller": {"diameter": {"value": 2.1, "units": "m"}},
        },
        "num_passengers_max": {"value": 2},
        "q_cruise": {"value": 56.9621, "units": "lb*ft**-2"},
    },
}

_B738_DATA: dict = {
    "ac": {
        "aero": {
            "CLmax_TO": {"value": 2.0},
            "polar": {
                "e": {"value": 0.801},
                "CD0_TO": {"value": 0.03},
                "CD0_cruise": {"value": 0.01925},
            },
        },
        "geom": {
            "wing": {
                "S_ref": {"value": 124.6, "units": "m**2"},
                "AR": {"value": 9.45},
                "c4sweep": {"value": 25.0, "units": "deg"},
                "taper": {"value": 0.159},
                "toverc": {"value": 0.12},
            },
            "hstab": {
                "S_ref": {"value": 32.78, "units": "m**2"},
                "c4_to_wing_c4": {"value": 17.9, "units": "m"},
            },
            "vstab": {"S_ref": {"value": 26.44, "units": "m**2"}},
            "nosegear": {"length": {"value": 3, "units": "ft"}},
            "maingear": {"length": {"value": 4, "units": "ft"}},
        },
        "weights": {
            "MTOW": {"value": 79002, "units": "kg"},
            "OEW": {"value": 41871, "units": "kg"},
            "W_fuel_max": {"value": 21015, "units": "kg"},
            "MLW": {"value": 66349, "units": "kg"},
        },
        "propulsion": {
            "engine": {"rating": {"value": 27000, "units": "lbf"}},
        },
        "num_passengers_max": {"value": 180},
        "q_cruise": {"value": 212.662, "units": "lb*ft**-2"},
    },
}

_KINGAIR_DATA: dict = {
    "ac": {
        "aero": {
            "CLmax_TO": {"value": 1.52},
            "polar": {
                "e": {"value": 0.80},
                "CD0_TO": {"value": 0.040},
                "CD0_cruise": {"value": 0.022},
            },
        },
        "geom": {
            "wing": {
                "S_ref": {"value": 27.308, "units": "m**2"},
                "AR": {"value": 8.5834},
                "c4sweep": {"value": 1.0, "units": "deg"},
                "taper": {"value": 0.397},
                "toverc": {"value": 0.19},
            },
            "fuselage": {
                "S_wet": {"value": 41.3, "units": "m**2"},
                "width": {"value": 1.6, "units": "m"},
                "length": {"value": 10.79, "units": "m"},
                "height": {"value": 1.9, "units": "m"},
            },
            "hstab": {
                "S_ref": {"value": 8.08, "units": "m**2"},
                "c4_to_wing_c4": {"value": 5.33, "units": "m"},
            },
            "vstab": {"S_ref": {"value": 3.4, "units": "m**2"}},
            "nosegear": {"length": {"value": 0.95, "units": "m"}},
            "maingear": {"length": {"value": 0.88, "units": "m"}},
        },
        "weights": {
            "MTOW": {"value": 4581, "units": "kg"},
            "OEW": {"value": 2585, "units": "kg"},
            "W_fuel_max": {"value": 1166, "units": "kg"},
            "MLW": {"value": 4355, "units": "kg"},
            "W_battery": {"value": 100, "units": "kg"},
        },
        "propulsion": {
            "engine": {"rating": {"value": 750, "units": "hp"}},
            "propeller": {"diameter": {"value": 2.28, "units": "m"}},
            "motor": {"rating": {"value": 527.2, "units": "hp"}},
            "generator": {"rating": {"value": 1083.7, "units": "hp"}},
        },
        "num_passengers_max": {"value": 8},
        "q_cruise": {"value": 98, "units": "lb*ft**-2"},
        "num_engines": {"value": 2},
    },
}

_TBM850_DATA: dict = {
    "ac": {
        "aero": {
            "CLmax_TO": {"value": 1.7},
            "polar": {
                "e": {"value": 0.78},
                "CD0_TO": {"value": 0.03},
                "CD0_cruise": {"value": 0.0205},
            },
        },
        "geom": {
            "wing": {
                "S_ref": {"value": 18.0, "units": "m**2"},
                "AR": {"value": 8.95},
                "c4sweep": {"value": 1.0, "units": "deg"},
                "taper": {"value": 0.622},
                "toverc": {"value": 0.16},
            },
            "fuselage": {
                "S_wet": {"value": 392, "units": "ft**2"},
                "width": {"value": 4.58, "units": "ft"},
                "length": {"value": 27.39, "units": "ft"},
                "height": {"value": 5.555, "units": "ft"},
            },
            "hstab": {
                "S_ref": {"value": 47.5, "units": "ft**2"},
                "c4_to_wing_c4": {"value": 17.9, "units": "ft"},
            },
            "vstab": {"S_ref": {"value": 31.36, "units": "ft**2"}},
            "nosegear": {"length": {"value": 3, "units": "ft"}},
            "maingear": {"length": {"value": 4, "units": "ft"}},
        },
        "weights": {
            "MTOW": {"value": 3353, "units": "kg"},
            "OEW": {"value": 2073, "units": "kg"},
            "W_fuel_max": {"value": 2000, "units": "lb"},
            "MLW": {"value": 7000, "units": "lb"},
        },
        "propulsion": {
            "engine": {"rating": {"value": 850, "units": "hp"}},
            "propeller": {"diameter": {"value": 2.31, "units": "m"}},
        },
        "num_passengers_max": {"value": 6},
        "q_cruise": {"value": 135.4, "units": "lb*ft**-2"},
    },
}

AIRCRAFT_TEMPLATES: dict[str, dict] = {
    "caravan": {"data": _CARAVAN_DATA, "default_architecture": "turboprop"},
    "b738": {"data": _B738_DATA, "default_architecture": "twin_turbofan"},
    "kingair": {"data": _KINGAIR_DATA, "default_architecture": "twin_turboprop"},
    "tbm850": {"data": _TBM850_DATA, "default_architecture": "turboprop"},
}
