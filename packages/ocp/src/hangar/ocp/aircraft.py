"""Dynamic aircraft model class factory.

Generates ``om.Group`` subclasses at runtime that wire up the selected
propulsion system, drag model, weight model, and integrators -- mirroring
what each OpenConcept example does in its hand-written ``AirplaneModel`` class.
"""

from __future__ import annotations

import importlib
from typing import Any

import numpy as np
import openmdao.api as om

from openconcept.aerodynamics import PolarDrag
from openconcept.utilities import AddSubtractComp, Integrator, LinearInterpolator
from openconcept.mission import IntegratorGroup

from hangar.ocp.config.defaults import PROPULSION_ARCHITECTURES


def _import_class(module_path: str, class_name: str) -> type:
    """Dynamically import a class from a module path."""
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def make_aircraft_model_class(
    architecture: str,
    propulsion_overrides: dict | None = None,
) -> type:
    """Create an ``om.Group`` subclass wired for the given propulsion architecture.

    Parameters
    ----------
    architecture
        Key in ``PROPULSION_ARCHITECTURES`` (e.g. "turboprop", "twin_series_hybrid").
    propulsion_overrides
        Optional overrides (not currently used at class-creation time, but
        reserved for future per-component configuration).

    Returns
    -------
    type
        A dynamically created ``om.Group`` subclass that OpenConcept mission
        analysis can instantiate with ``aircraft_model=<returned class>``.
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

    # CFM56 is a special case: it's a single-engine empirical turbofan model
    is_cfm56 = prop_class_name == "CFM56"
    is_hybrid = has_battery and has_fuel

    # Determine the base class: CFM56 (B738) uses IntegratorGroup for tag-based
    # integration; everything else uses om.Group with explicit Integrator.
    if is_cfm56:
        BaseClass = IntegratorGroup
    else:
        BaseClass = om.Group

    class DynamicAircraftModel(BaseClass):
        """Dynamically generated aircraft model for OpenConcept mission analysis."""

        def initialize(self):
            self.options.declare("num_nodes", default=1)
            self.options.declare("flight_phase", default=None)

        def setup(self):
            nn = self.options["num_nodes"]
            flight_phase = self.options["flight_phase"]

            # ---- Controls ----
            controls = self.add_subsystem("controls", om.IndepVarComp(), promotes_outputs=["*"])

            if is_cfm56:
                # CFM56 doesn't need RPM control
                pass
            else:
                # Propeller RPM control
                if num_engines == 1:
                    controls.add_output("prop1rpm", val=np.ones((nn,)) * 2000, units="rpm")
                else:
                    controls.add_output("proprpm", val=np.ones((nn,)) * 2000, units="rpm")

            # Hybridization control for hybrid architectures
            if is_hybrid:
                if flight_phase in ["climb", "cruise", "descent"]:
                    controls.add_output("hybridization", val=0.0)
                else:
                    # Takeoff phases use battery backup
                    controls.add_output("hybridization", val=1.0)

                self.add_subsystem(
                    "hybrid_factor",
                    LinearInterpolator(num_nodes=nn),
                    promotes_inputs=[
                        ("start_val", "hybridization"),
                        ("end_val", "hybridization"),
                    ],
                )

            # ---- Propulsion ----
            if is_cfm56:
                propulsion_promotes_inputs = ["fltcond|*", "throttle"]
                self.add_subsystem(
                    "propmodel",
                    PropClass(num_nodes=nn, plot=False),
                    promotes_inputs=propulsion_promotes_inputs,
                )

                # Double thrust and fuel_flow for twin engines
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

                # Connect RPM and hybridization
                if num_engines == 1:
                    self.connect("prop1rpm", "propmodel.prop1.rpm")
                else:
                    self.connect("proprpm", ["propmodel.prop1.rpm", "propmodel.prop2.rpm"])

                if is_hybrid:
                    self.connect(
                        "hybrid_factor.vec",
                        "propmodel.hybrid_split.power_split_fraction",
                    )

            # ---- Drag ----
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

            # ---- Empty Weight ----
            if WeightClass is not None:
                self.add_subsystem(
                    "OEW",
                    WeightClass(),
                    promotes_inputs=["*", ("P_TO", "ac|propulsion|engine|rating")],
                    promotes_outputs=["OEW"],
                )
                # Connect component weights from propulsion to weight model
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
                # B738 pattern: pass-through OEW from aircraft data
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

            # ---- Fuel Integration (non-CFM56 architectures) ----
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

            # ---- Weight Summation ----
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

    # Give it a descriptive name for debugging
    DynamicAircraftModel.__name__ = f"{architecture.title().replace('_', '')}AircraftModel"
    DynamicAircraftModel.__qualname__ = DynamicAircraftModel.__name__

    return DynamicAircraftModel
