"""Dynamic aircraft model class factory for OpenConcept missions."""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from openconcept.aerodynamics import PolarDrag
from openconcept.utilities import Integrator, LinearInterpolator, AddSubtractComp
from openconcept.mission import IntegratorGroup

from hangar.omd.factories.ocp.architectures import (
    PROPULSION_ARCHITECTURES,
    _import_class,
)


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

    # When a propulsion slot replaces CFM56, the slot provides standard
    # thrust/fuel_flow outputs.  Use om.Group (not IntegratorGroup) and
    # add the normal fuel integrator so fuel_used_final is available.
    propulsion_slot = (slots or {}).get("propulsion")
    if is_cfm56 and propulsion_slot is not None:
        is_cfm56 = False

    BaseClass = IntegratorGroup if is_cfm56 else om.Group

    class DynamicAircraftModel(BaseClass):
        def initialize(self):
            self.options.declare("num_nodes", default=1)
            self.options.declare("flight_phase", default=None)

        def setup(self):
            nn = self.options["num_nodes"]
            flight_phase = self.options["flight_phase"]

            # Controls (only add IndepVarComp if there are outputs to declare)
            _need_rpm = (not is_cfm56) and not (slots or {}).get("propulsion")
            has_controls = _need_rpm or is_hybrid
            if has_controls:
                controls = self.add_subsystem(
                    "controls", om.IndepVarComp(), promotes_outputs=["*"],
                )

                if _need_rpm:
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

            # Propulsion (slot-aware: can substitute pyCycle turbojet, etc.)
            propulsion_slot = (slots or {}).get("propulsion")
            if propulsion_slot is not None:
                from hangar.omd.slots import get_slot_provider
                prop_provider_fn = get_slot_provider(propulsion_slot["provider"])
                prop_comp, prop_prom_in, prop_prom_out = prop_provider_fn(
                    nn, flight_phase, propulsion_slot.get("config", {}),
                )
                self.add_subsystem(
                    "propmodel", prop_comp,
                    promotes_inputs=prop_prom_in,
                    promotes_outputs=prop_prom_out,
                )
            elif is_cfm56:
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
            drag_source = (slots or {}).get("drag_source", "internal")
            drag_slot = (slots or {}).get("drag")
            if drag_source == "external":
                pass  # no drag component; expects external connection
            elif drag_slot is not None:
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
            weight_slot = (slots or {}).get("weight")
            if weight_slot is not None:
                from hangar.omd.slots import get_slot_provider as _get_wt_provider
                wt_provider_fn = _get_wt_provider(weight_slot["provider"])
                wt_comp, wt_prom_in, wt_prom_out = wt_provider_fn(
                    nn, flight_phase, weight_slot.get("config", {}),
                )
                self.add_subsystem(
                    "OEW", wt_comp,
                    promotes_inputs=wt_prom_in,
                    promotes_outputs=wt_prom_out,
                )
            elif propulsion_slot is not None:
                # Propulsion slot providers don't expose W_engine/W_propeller.
                # Use OEW passthrough (same as CFM56 path).
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
            elif WeightClass is not None:
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
