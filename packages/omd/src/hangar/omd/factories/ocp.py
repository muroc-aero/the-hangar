"""OpenConcept mission component factories.

Builds OpenConcept mission analysis problems from plan YAML configs using
upstream openconcept and openmdao APIs directly. No dependency on hangar-ocp.
"""

from __future__ import annotations

import copy
import importlib
from typing import Any

import numpy as np
import openmdao.api as om

from openconcept.aerodynamics import PolarDrag
from openconcept.utilities import (
    AddSubtractComp,
    DictIndepVarComp,
    Integrator,
    LinearInterpolator,
)
from openconcept.mission import (
    BasicMission,
    FullMissionAnalysis,
    IntegratorGroup,
    MissionWithReserve,
)


# ---------------------------------------------------------------------------
# Propulsion architecture registry
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Aircraft templates
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Default mission parameters
# ---------------------------------------------------------------------------

DEFAULT_MISSION_PARAMS: dict = {
    "cruise_altitude_ft": 18000.0,
    "mission_range_NM": 250.0,
    "climb_vs_ftmin": 850.0,
    "climb_Ueas_kn": 104.0,
    "cruise_vs_ftmin": 0.01,
    "cruise_Ueas_kn": 129.0,
    "descent_vs_ftmin": -400.0,
    "descent_Ueas_kn": 100.0,
    "payload_lb": None,
    "climb_hybridization": None,
    "cruise_hybridization": None,
    "descent_hybridization": None,
}

DEFAULT_SOLVER_SETTINGS: dict = {
    "maxiter": 20,
    "atol": 1e-10,
    "rtol": 1e-10,
    "solve_subsystems": True,
}

BASIC_MISSION_PHASES = ["climb", "cruise", "descent"]
FULL_MISSION_PHASES = ["v0v1", "v1vr", "v1v0", "rotate", "climb", "cruise", "descent"]
TAKEOFF_PHASES = ["v0v1", "v1vr", "v1v0", "rotate"]


# ---------------------------------------------------------------------------
# DictIndepVarComp field registration helpers
# ---------------------------------------------------------------------------

_COMMON_FIELDS = [
    "ac|aero|CLmax_TO",
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
    "ac|geom|wing|S_ref",
    "ac|geom|wing|AR",
    "ac|geom|wing|c4sweep",
    "ac|geom|wing|taper",
    "ac|geom|wing|toverc",
    "ac|geom|hstab|S_ref",
    "ac|geom|hstab|c4_to_wing_c4",
    "ac|geom|vstab|S_ref",
    "ac|geom|nosegear|length",
    "ac|geom|maingear|length",
    "ac|weights|MTOW",
    "ac|weights|W_fuel_max",
    "ac|weights|MLW",
    "ac|propulsion|engine|rating",
    "ac|num_passengers_max",
    "ac|q_cruise",
]

_FUSELAGE_FIELDS = [
    "ac|geom|fuselage|S_wet",
    "ac|geom|fuselage|width",
    "ac|geom|fuselage|length",
    "ac|geom|fuselage|height",
]

_PROPELLER_FIELDS = [
    "ac|propulsion|propeller|diameter",
]

_HYBRID_FIELDS = [
    "ac|propulsion|motor|rating",
    "ac|propulsion|generator|rating",
    "ac|weights|W_battery",
]

_MULTI_ENGINE_FIELDS = [
    "ac|num_engines",
]

_OEW_FIELDS = [
    "ac|weights|OEW",
]


def _has_field(data: dict, pipe_path: str) -> bool:
    """Check if a pipe-separated path exists in the nested aircraft data dict."""
    parts = pipe_path.split("|")
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _register_fields(dv_comp: Any, data: dict, fields: list[str]) -> None:
    """Register available fields from the aircraft data dict."""
    for field_path in fields:
        if _has_field(data, field_path):
            dv_comp.add_output_from_dict(field_path)


def _import_class(module_path: str, class_name: str) -> type:
    """Dynamically import a class from a module path."""
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


# ---------------------------------------------------------------------------
# Dynamic aircraft model class factory
# ---------------------------------------------------------------------------


def _make_aircraft_model_class(
    architecture: str,
    propulsion_overrides: dict | None = None,
    slots: dict | None = None,
) -> type:
    """Create an om.Group subclass wired for the given propulsion architecture.

    Args:
        slots: Optional dict of slot overrides. Keys are slot names
            ("drag", "propulsion", etc.), values are dicts with
            "provider" (registry name) and "config" (provider config).

    Mirrors the pattern from ocp/aircraft.py but is self-contained.
    """
    arch_info = PROPULSION_ARCHITECTURES[architecture]
    has_fuel = arch_info["has_fuel"]
    has_battery = arch_info["has_battery"]
    num_engines = arch_info["num_engines"]
    prop_class_name = arch_info["prop_class"]
    prop_module = arch_info["prop_module"]
    weight_class_name = arch_info.get("weight_class")
    weight_module = arch_info.get("weight_module")

    PropClass = _import_class(prop_module, prop_class_name)

    WeightClass = None
    if weight_class_name and weight_module:
        WeightClass = _import_class(weight_module, weight_class_name)

    is_cfm56 = prop_class_name == "CFM56"
    is_hybrid = has_battery and has_fuel

    BaseClass = IntegratorGroup if is_cfm56 else om.Group

    class DynamicAircraftModel(BaseClass):
        def initialize(self):
            self.options.declare("num_nodes", default=1)
            self.options.declare("flight_phase", default=None)

        def setup(self):
            nn = self.options["num_nodes"]
            flight_phase = self.options["flight_phase"]

            # Controls (only add IndepVarComp if there are outputs to declare)
            has_controls = (not is_cfm56) or is_hybrid
            if has_controls:
                controls = self.add_subsystem(
                    "controls", om.IndepVarComp(), promotes_outputs=["*"],
                )

                if not is_cfm56:
                    if num_engines == 1:
                        controls.add_output("prop1rpm", val=np.ones((nn,)) * 2000, units="rpm")
                    else:
                        controls.add_output("proprpm", val=np.ones((nn,)) * 2000, units="rpm")

                if is_hybrid:
                    if flight_phase in ["climb", "cruise", "descent"]:
                        controls.add_output("hybridization", val=0.0)
                    else:
                        controls.add_output("hybridization", val=1.0)

                    self.add_subsystem(
                        "hybrid_factor",
                        LinearInterpolator(num_nodes=nn),
                        promotes_inputs=[
                            ("start_val", "hybridization"),
                            ("end_val", "hybridization"),
                        ],
                    )

            # Propulsion
            if is_cfm56:
                self.add_subsystem(
                    "propmodel",
                    PropClass(num_nodes=nn, plot=False),
                    promotes_inputs=["fltcond|*", "throttle"],
                )
                doubler = om.ExecComp(
                    ["thrust=2*thrust_in", "fuel_flow=2*fuel_flow_in"],
                    thrust_in={"val": np.ones((nn,)), "units": "kN"},
                    thrust={"val": np.ones((nn,)), "units": "kN"},
                    fuel_flow={
                        "val": np.ones((nn,)),
                        "units": "kg/s",
                        "tags": [
                            "integrate",
                            "state_name:fuel_used",
                            "state_units:kg",
                            "state_val:1.0",
                            "state_promotes:True",
                        ],
                    },
                    fuel_flow_in={"val": np.ones((nn,)), "units": "kg/s"},
                    has_diag_partials=True,
                )
                self.add_subsystem("doubler", doubler, promotes_outputs=["*"])
                self.connect("propmodel.thrust", "doubler.thrust_in")
                self.connect("propmodel.fuel_flow", "doubler.fuel_flow_in")
            else:
                propulsion_promotes_outputs = ["fuel_flow", "thrust"]
                propulsion_promotes_inputs = ["fltcond|*", "ac|propulsion|*", "throttle"]

                if is_hybrid:
                    propulsion_promotes_inputs.extend([
                        "propulsor_active",
                        "ac|weights*",
                        "duration",
                    ])

                self.add_subsystem(
                    "propmodel",
                    PropClass(num_nodes=nn),
                    promotes_inputs=propulsion_promotes_inputs,
                    promotes_outputs=propulsion_promotes_outputs,
                )

                if num_engines == 1:
                    self.connect("prop1rpm", "propmodel.prop1.rpm")
                else:
                    self.connect("proprpm", ["propmodel.prop1.rpm", "propmodel.prop2.rpm"])

                if is_hybrid:
                    self.connect(
                        "hybrid_factor.vec",
                        "propmodel.hybrid_split.power_split_fraction",
                    )

            # Drag (slot-aware: can substitute VLMDragPolar, AerostructDragPolar, etc.)
            drag_slot = (slots or {}).get("drag")
            if drag_slot is not None:
                from hangar.omd.slots import get_slot_provider
                provider_fn = get_slot_provider(drag_slot["provider"])
                drag_comp, drag_prom_in, drag_prom_out = provider_fn(
                    nn, flight_phase, drag_slot.get("config", {}),
                )
                self.add_subsystem(
                    "drag", drag_comp,
                    promotes_inputs=drag_prom_in,
                    promotes_outputs=drag_prom_out,
                )
            else:
                if flight_phase not in ["v0v1", "v1v0", "v1vr", "rotate"]:
                    cd0_source = "ac|aero|polar|CD0_cruise"
                else:
                    cd0_source = "ac|aero|polar|CD0_TO"

                self.add_subsystem(
                    "drag",
                    PolarDrag(num_nodes=nn),
                    promotes_inputs=[
                        "fltcond|CL",
                        "ac|geom|*",
                        ("CD0", cd0_source),
                        "fltcond|q",
                        ("e", "ac|aero|polar|e"),
                    ],
                    promotes_outputs=["drag"],
                )

            # Empty weight
            if WeightClass is not None:
                self.add_subsystem(
                    "OEW",
                    WeightClass(),
                    promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
                    promotes_outputs=["OEW"],
                )
                if is_hybrid:
                    self.connect("propmodel.propellers_weight", "W_propeller")
                    self.connect("propmodel.eng1.component_weight", "W_engine")
                    self.connect("propmodel.gen1.component_weight", "W_generator")
                    self.connect("propmodel.motors_weight", "W_motors")
                elif num_engines == 1:
                    self.connect("propmodel.prop1.component_weight", "W_propeller")
                    self.connect("propmodel.eng1.component_weight", "W_engine")
                else:
                    self.connect("propmodel.propellers_weight", "W_propeller")
                    self.connect("propmodel.eng1.component_weight", "W_engine")
            elif is_cfm56:
                passthru = om.ExecComp(
                    "OEW=x",
                    x={"val": 1.0, "units": "kg"},
                    OEW={"val": 1.0, "units": "kg"},
                )
                self.add_subsystem(
                    "OEW",
                    passthru,
                    promotes_inputs=[("x", "ac|weights|OEW")],
                    promotes_outputs=["OEW"],
                )

            # Fuel integration (non-CFM56)
            if not is_cfm56 and has_fuel:
                intfuel = self.add_subsystem(
                    "intfuel",
                    Integrator(
                        num_nodes=nn,
                        method="simpson",
                        diff_units="s",
                        time_setup="duration",
                    ),
                    promotes_inputs=["*"],
                    promotes_outputs=["*"],
                )
                intfuel.add_integrand(
                    "fuel_used",
                    rate_name="fuel_flow",
                    val=1.0,
                    units="kg",
                )

            # Weight summation
            self.add_subsystem(
                "weight",
                AddSubtractComp(
                    output_name="weight",
                    input_names=["ac|weights|MTOW", "fuel_used"],
                    units="kg",
                    vec_size=[1, nn],
                    scaling_factors=[1, -1],
                ),
                promotes_inputs=["*"],
                promotes_outputs=["weight"],
            )

    DynamicAircraftModel.__name__ = f"{architecture.title().replace('_', '')}AircraftModel"
    DynamicAircraftModel.__qualname__ = DynamicAircraftModel.__name__
    return DynamicAircraftModel


# ---------------------------------------------------------------------------
# Mission value setter
# ---------------------------------------------------------------------------


def _phase_array(nn: int, value) -> np.ndarray:
    """Convert a mission param value to a (nn,) array.

    Accepts:
        scalar (int/float) -- broadcast to constant array
        [start, end] list  -- expanded via np.linspace
        list/array of length nn -- used as-is
    """
    if isinstance(value, (list, tuple)):
        if len(value) == 2:
            return np.linspace(float(value[0]), float(value[1]), nn)
        return np.array(value, dtype=float)
    return np.ones((nn,)) * float(value)


def _collect_mission_values(
    params: dict,
    phases: list[str],
    num_nodes: int,
    is_hybrid: bool,
    mission_type: str,
) -> dict[str, dict]:
    """Build a dict of {path: {"val": ..., "units": ...}} for deferred set_val.

    This is the declarative equivalent of _set_mission_values -- same data,
    returned as a dict instead of applied to a Problem.

    Phase speed values can be scalars (broadcast to constant arrays) or
    two-element [start, end] lists (expanded via np.linspace). This matches
    the upstream OpenConcept convention where speeds vary across nodes.
    """
    nn = num_nodes
    vals: dict[str, dict] = {}

    if "climb" in phases:
        vals["climb.fltcond|vs"] = {
            "val": _phase_array(nn, params.get("climb_vs_ftmin", 850.0)),
            "units": "ft/min",
        }
        vals["climb.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("climb_Ueas_kn", 104.0)),
            "units": "kn",
        }

    if "cruise" in phases:
        vals["cruise.fltcond|vs"] = {
            "val": _phase_array(nn, params.get("cruise_vs_ftmin", 0.01)),
            "units": "ft/min",
        }
        vals["cruise.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("cruise_Ueas_kn", 129.0)),
            "units": "kn",
        }

    if "descent" in phases:
        vs_raw = params.get("descent_vs_ftmin", -400.0)
        # Negate scalar descent speeds; for [start, end] lists, negate both
        if isinstance(vs_raw, (list, tuple)):
            vs_descent = [-abs(v) for v in vs_raw]
        else:
            vs_descent = -abs(float(vs_raw))
        vals["descent.fltcond|vs"] = {
            "val": _phase_array(nn, vs_descent),
            "units": "ft/min",
        }
        vals["descent.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("descent_Ueas_kn", 100.0)),
            "units": "kn",
        }

    vals["cruise|h0"] = {
        "val": params.get("cruise_altitude_ft", 18000.0),
        "units": "ft",
    }
    vals["mission_range"] = {
        "val": params.get("mission_range_NM", 250.0),
        "units": "NM",
    }

    # Reserve phases
    if mission_type == "with_reserve":
        vals["reserve|h0"] = {
            "val": params.get("reserve_altitude_ft", 15000.0),
            "units": "ft",
        }
        vals["reserve_climb.fltcond|vs"] = {
            "val": _phase_array(nn, params.get("reserve_climb_vs_ftmin", 1500.0)),
            "units": "ft/min",
        }
        vals["reserve_climb.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("reserve_climb_Ueas_kn", 124.0)),
            "units": "kn",
        }
        vals["reserve_cruise.fltcond|vs"] = {
            "val": _phase_array(nn, params.get("reserve_cruise_vs_ftmin", 4.0)),
            "units": "ft/min",
        }
        vals["reserve_cruise.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("reserve_cruise_Ueas_kn", 170.0)),
            "units": "kn",
        }
        rsv_descent_raw = params.get("reserve_descent_vs_ftmin", -600.0)
        if isinstance(rsv_descent_raw, (list, tuple)):
            rsv_descent = [-abs(v) for v in rsv_descent_raw]
        else:
            rsv_descent = -abs(float(rsv_descent_raw))
        vals["reserve_descent.fltcond|vs"] = {
            "val": _phase_array(nn, rsv_descent),
            "units": "ft/min",
        }
        vals["reserve_descent.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("reserve_descent_Ueas_kn", 140.0)),
            "units": "kn",
        }
        vals["loiter.fltcond|vs"] = {
            "val": _phase_array(nn, params.get("loiter_vs_ftmin", 0.0)),
            "units": "ft/min",
        }
        vals["loiter.fltcond|Ueas"] = {
            "val": _phase_array(nn, params.get("loiter_Ueas_kn", 200.0)),
            "units": "kn",
        }

    # Takeoff speed guesses
    if mission_type == "full":
        vals["v0v1.fltcond|Utrue"] = {
            "val": _phase_array(nn, params.get("v0v1_Utrue_kn", 50)),
            "units": "kn",
        }
        vals["v1vr.fltcond|Utrue"] = {
            "val": _phase_array(nn, params.get("v1vr_Utrue_kn", 85)),
            "units": "kn",
        }
        vals["v1v0.fltcond|Utrue"] = {
            "val": _phase_array(nn, params.get("v1v0_Utrue_kn", 85)),
            "units": "kn",
        }
        vals["rotate.fltcond|Utrue"] = {
            "val": _phase_array(nn, params.get("rotate_Utrue_kn", 80)),
            "units": "kn",
        }
        vals["v0v1.throttle"] = {"val": np.ones((nn,))}
        vals["v1vr.throttle"] = {"val": np.ones((nn,))}
        vals["rotate.throttle"] = {"val": np.ones((nn,))}

    # Payload
    payload_lb = params.get("payload_lb")
    if payload_lb is not None:
        vals["payload"] = {"val": payload_lb, "units": "lb"}

    # Hybridization fractions
    if is_hybrid:
        for phase in ("climb", "cruise", "descent"):
            hyb = params.get(f"{phase}_hybridization")
            if hyb is not None and phase in phases:
                vals[f"{phase}.hybridization"] = {"val": hyb}

        spec_energy = params.get("battery_specific_energy")
        if spec_energy is not None:
            vals["ac|propulsion|battery|specific_energy"] = {
                "val": spec_energy,
                "units": "W*h/kg",
            }

    return vals


def _set_mission_values(
    prob: om.Problem,
    params: dict,
    phases: list[str],
    num_nodes: int,
    is_hybrid: bool,
    mission_type: str,
) -> None:
    """Set mission parameter values on the problem after setup."""
    vals = _collect_mission_values(params, phases, num_nodes, is_hybrid, mission_type)
    for path, spec in vals.items():
        try:
            units = spec.get("units") if isinstance(spec, dict) else None
            val = spec.get("val") if isinstance(spec, dict) else spec
            if units:
                prob.set_val(path, val, units=units)
            else:
                prob.set_val(path, val)
        except (KeyError, Exception):
            pass


# ---------------------------------------------------------------------------
# Problem builder
# ---------------------------------------------------------------------------


def _build_mission_problem(
    aircraft_data: dict,
    architecture: str,
    mission_type: str,
    mission_params: dict,
    num_nodes: int,
    solver_settings: dict,
    propulsion_overrides: dict | None = None,
    defer_setup: bool = False,
    slots: dict | None = None,
) -> tuple[om.Problem, dict]:
    """Build a complete OpenMDAO mission problem.

    Args:
        defer_setup: If True, skip prob.setup() and set_val() calls.
            The model Group is returned with solvers configured but
            not settled. Mission values are put into metadata as
            initial_values_with_units for the materializer to apply.
            Used by the multi-component materializer.
        slots: Optional dict of slot overrides for the aircraft model.
            Keys are slot names ("drag"), values have "provider" and "config".

    Returns (problem, metadata). When defer_setup=False (default),
    setup is called and _setup_done=True. When defer_setup=True,
    setup is NOT called and _setup_done is NOT set.
    """
    arch_info = PROPULSION_ARCHITECTURES[architecture]
    is_hybrid = arch_info["has_battery"] and arch_info["has_fuel"]
    is_cfm56 = arch_info["prop_class"] == "CFM56"

    AircraftModelClass = _make_aircraft_model_class(architecture, propulsion_overrides, slots)

    if mission_type == "basic":
        MissionClass = BasicMission
        phases = list(BASIC_MISSION_PHASES)
    elif mission_type == "with_reserve":
        MissionClass = MissionWithReserve
        phases = ["climb", "cruise", "descent",
                  "reserve_climb", "reserve_cruise", "reserve_descent", "loiter"]
    else:
        MissionClass = FullMissionAnalysis
        phases = list(FULL_MISSION_PHASES)

    ac_data = copy.deepcopy(aircraft_data)

    class AnalysisGroup(om.Group):
        def setup(self):
            dv_comp = self.add_subsystem(
                "dv_comp",
                DictIndepVarComp(ac_data),
                promotes_outputs=["*"],
            )

            # Collect fields to remove/add based on active slot providers
            _fields_to_remove: set[str] = set()
            _fields_to_add: dict[str, dict] = {}
            if slots:
                from hangar.omd.slots import get_slot_provider
                for _slot_cfg in slots.values():
                    _prov = get_slot_provider(_slot_cfg["provider"])
                    if hasattr(_prov, "removes_fields"):
                        _fields_to_remove.update(_prov.removes_fields)
                    if hasattr(_prov, "adds_fields"):
                        _fields_to_add.update(_prov.adds_fields)

            _common = [f for f in _COMMON_FIELDS if f not in _fields_to_remove]
            _register_fields(dv_comp, ac_data, _common)

            if not is_cfm56:
                _propeller = [f for f in _PROPELLER_FIELDS if f not in _fields_to_remove]
                _register_fields(dv_comp, ac_data, _propeller)
            _fuselage = [f for f in _FUSELAGE_FIELDS if f not in _fields_to_remove]
            _register_fields(dv_comp, ac_data, _fuselage)
            if is_hybrid:
                _hybrid = [f for f in _HYBRID_FIELDS if f not in _fields_to_remove]
                _register_fields(dv_comp, ac_data, _hybrid)
            if arch_info["num_engines"] > 1:
                _register_fields(dv_comp, ac_data, _MULTI_ENGINE_FIELDS)
            if is_cfm56:
                _register_fields(dv_comp, ac_data, _OEW_FIELDS)

            # Add fields from slot providers
            for _field_path, _field_spec in _fields_to_add.items():
                dv_comp.add_output(
                    _field_path,
                    val=_field_spec.get("value", 0.0),
                    units=_field_spec.get("units"),
                )

            if is_hybrid:
                spec_energy = 300
                if propulsion_overrides and "battery_specific_energy" in propulsion_overrides:
                    spec_energy = propulsion_overrides["battery_specific_energy"]
                dv_comp.add_output(
                    "ac|propulsion|battery|specific_energy",
                    val=spec_energy,
                    units="W*h/kg",
                )

            if is_hybrid:
                mission_data = self.add_subsystem(
                    "mission_data_comp",
                    om.IndepVarComp(),
                    promotes_outputs=["*"],
                )
                mission_data.add_output("batt_soc_target", val=0.1, units=None)

            self.add_subsystem(
                "analysis",
                MissionClass(num_nodes=num_nodes, aircraft_model=AircraftModelClass),
                promotes_inputs=["*"],
                promotes_outputs=["*"],
            )

            if is_hybrid:
                self.add_subsystem(
                    "margins",
                    om.ExecComp(
                        "MTOW_margin = MTOW - OEW - total_fuel - W_battery - payload",
                        MTOW_margin={"units": "lbm", "val": 100},
                        MTOW={"units": "lbm", "val": 10000},
                        OEW={"units": "lbm", "val": 5000},
                        total_fuel={"units": "lbm", "val": 1000},
                        W_battery={"units": "lbm", "val": 1000},
                        payload={"units": "lbm", "val": 1000},
                    ),
                    promotes_inputs=["payload"],
                )
                self.connect("cruise.OEW", "margins.OEW")
                self.connect("descent.fuel_used_final", "margins.total_fuel")
                self.connect("ac|weights|MTOW", "margins.MTOW")
                self.connect("ac|weights|W_battery", "margins.W_battery")

                self.add_subsystem(
                    "aug_obj",
                    om.ExecComp(
                        "mixed_objective = fuel_burn + MTOW / 100",
                        mixed_objective={"units": "kg"},
                        fuel_burn={"units": "kg"},
                        MTOW={"units": "kg"},
                    ),
                    promotes_outputs=["mixed_objective"],
                )
                self.connect("ac|weights|MTOW", "aug_obj.MTOW")
                self.connect("descent.fuel_used_final", "aug_obj.fuel_burn")

    # Create and configure problem
    prob = om.Problem(reports=False)
    prob.model = AnalysisGroup()

    settings = {**DEFAULT_SOLVER_SETTINGS, **solver_settings}
    prob.model.nonlinear_solver = om.NewtonSolver(
        iprint=0,
        solve_subsystems=settings["solve_subsystems"],
    )
    prob.model.linear_solver = om.DirectSolver()
    prob.model.nonlinear_solver.options["maxiter"] = settings["maxiter"]
    prob.model.nonlinear_solver.options["atol"] = settings["atol"]
    prob.model.nonlinear_solver.options["rtol"] = settings["rtol"]
    prob.model.nonlinear_solver.linesearch = om.BoundsEnforceLS(
        bound_enforcement="scalar",
        print_bound_enforce=False,
    )

    params = {**DEFAULT_MISSION_PARAMS, **mission_params}

    metadata = {
        "component_family": "ocp",
        "architecture": architecture,
        "mission_type": mission_type,
        "phases": phases,
        "num_nodes": num_nodes,
        "has_fuel": arch_info["has_fuel"],
        "has_battery": arch_info["has_battery"],
        "is_hybrid": is_hybrid,
        "has_takeoff": mission_type == "full",
        "has_reserve": mission_type == "with_reserve",
    }

    if defer_setup:
        # Deferred setup path: collect mission values as metadata
        # instead of calling prob.set_val(). The materializer or
        # outer Problem handles setup and value application.
        metadata["initial_values_with_units"] = _collect_mission_values(
            params, phases, num_nodes, is_hybrid, mission_type,
        )
    else:
        # Normal path: setup + set values immediately
        prob.setup(check=False, mode="fwd")
        _set_mission_values(prob, params, phases, num_nodes, is_hybrid, mission_type)
        metadata["_setup_done"] = True

    return prob, metadata


# ---------------------------------------------------------------------------
# Public factory entry points
# ---------------------------------------------------------------------------


def _load_aircraft_data(config: dict) -> dict:
    """Load aircraft data from template name or inline config."""
    template_name = config.get("aircraft_template")
    if template_name:
        if template_name not in AIRCRAFT_TEMPLATES:
            available = ", ".join(sorted(AIRCRAFT_TEMPLATES.keys()))
            raise ValueError(
                f"Unknown aircraft template '{template_name}'. "
                f"Available: {available}"
            )
        return copy.deepcopy(AIRCRAFT_TEMPLATES[template_name]["data"])

    aircraft_data = config.get("aircraft_data")
    if aircraft_data:
        return copy.deepcopy(aircraft_data)

    raise ValueError(
        "OCP factory requires either 'aircraft_template' or 'aircraft_data' in config"
    )


def _resolve_architecture(config: dict) -> str:
    """Resolve propulsion architecture from config or template default."""
    arch = config.get("architecture")
    if arch:
        if arch not in PROPULSION_ARCHITECTURES:
            available = ", ".join(sorted(PROPULSION_ARCHITECTURES.keys()))
            raise ValueError(
                f"Unknown propulsion architecture '{arch}'. "
                f"Available: {available}"
            )
        return arch

    template_name = config.get("aircraft_template")
    if template_name and template_name in AIRCRAFT_TEMPLATES:
        return AIRCRAFT_TEMPLATES[template_name]["default_architecture"]

    return "turboprop"


def build_ocp_basic_mission(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, dict]:
    """Build an OpenConcept basic mission (climb/cruise/descent)."""
    config = dict(component_config)
    defer_setup = config.pop("_defer_setup", False)
    slots = config.get("slots")
    ac_data = _load_aircraft_data(config)
    architecture = _resolve_architecture(config)
    num_nodes = config.get("num_nodes", 11)
    mission_params = config.get("mission_params", {})
    solver_settings = config.get("solver_settings", {})
    propulsion_overrides = config.get("propulsion_overrides")

    return _build_mission_problem(
        aircraft_data=ac_data,
        architecture=architecture,
        mission_type="basic",
        mission_params=mission_params,
        num_nodes=num_nodes,
        solver_settings=solver_settings,
        propulsion_overrides=propulsion_overrides,
        defer_setup=defer_setup,
        slots=slots,
    )


def build_ocp_full_mission(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, dict]:
    """Build an OpenConcept full mission with balanced-field takeoff."""
    config = dict(component_config)
    defer_setup = config.pop("_defer_setup", False)
    slots = config.get("slots")
    ac_data = _load_aircraft_data(config)
    architecture = _resolve_architecture(config)
    num_nodes = config.get("num_nodes", 11)
    mission_params = config.get("mission_params", {})
    solver_settings = config.get("solver_settings", {})
    propulsion_overrides = config.get("propulsion_overrides")

    return _build_mission_problem(
        aircraft_data=ac_data,
        architecture=architecture,
        mission_type="full",
        mission_params=mission_params,
        num_nodes=num_nodes,
        solver_settings=solver_settings,
        propulsion_overrides=propulsion_overrides,
        defer_setup=defer_setup,
        slots=slots,
    )


def build_ocp_mission_with_reserve(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, dict]:
    """Build an OpenConcept mission with reserve + loiter phases."""
    config = dict(component_config)
    defer_setup = config.pop("_defer_setup", False)
    slots = config.get("slots")
    ac_data = _load_aircraft_data(config)
    architecture = _resolve_architecture(config)
    num_nodes = config.get("num_nodes", 11)
    mission_params = config.get("mission_params", {})
    solver_settings = config.get("solver_settings", {})
    propulsion_overrides = config.get("propulsion_overrides")

    return _build_mission_problem(
        aircraft_data=ac_data,
        architecture=architecture,
        mission_type="with_reserve",
        mission_params=mission_params,
        num_nodes=num_nodes,
        solver_settings=solver_settings,
        propulsion_overrides=propulsion_overrides,
        defer_setup=defer_setup,
        slots=slots,
    )
