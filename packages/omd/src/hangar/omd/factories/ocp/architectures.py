"""Propulsion architecture registry for OpenConcept missions."""

from __future__ import annotations

import importlib


PROPULSION_ARCHITECTURES: dict[str, dict] = {
    "turboprop": {
        "prop_class": "TurbopropPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "SingleTurboPropEmptyWeight",
        "weight_module": "openconcept.weights",
        "has_fuel": True,
        "has_battery": False,
        "num_engines": 1,
    },
    "twin_turboprop": {
        "prop_class": "TwinTurbopropPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "SingleTurboPropEmptyWeight",
        "weight_module": "openconcept.weights",
        "has_fuel": True,
        "has_battery": False,
        "num_engines": 2,
    },
    "series_hybrid": {
        "prop_class": "SingleSeriesHybridElectricPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "TwinSeriesHybridEmptyWeight",
        "weight_module": "openconcept.weights",
        "has_fuel": True,
        "has_battery": True,
        "num_engines": 1,
    },
    "twin_series_hybrid": {
        "prop_class": "TwinSeriesHybridElectricPropulsionSystem",
        "prop_module": "openconcept.propulsion",
        "weight_class": "TwinSeriesHybridEmptyWeight",
        "weight_module": "openconcept.weights",
        "has_fuel": True,
        "has_battery": True,
        "num_engines": 2,
    },
    "twin_turbofan": {
        "prop_class": "CFM56",
        "prop_module": "openconcept.propulsion",
        "weight_class": None,
        "weight_module": None,
        "has_fuel": True,
        "has_battery": False,
        "num_engines": 2,
    },
}


def _import_class(module_path: str, class_name: str) -> type:
    """Dynamically import a class from a module path."""
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)
