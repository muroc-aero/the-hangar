"""OpenConcept mission problem builder and public factory entry points."""

from __future__ import annotations

from hangar.omd.factory_metadata import FactoryMetadata

import copy

import openmdao.api as om

from openconcept.utilities import DictIndepVarComp
from openconcept.mission import (
    BasicMission,
    FullMissionAnalysis,
    MissionWithReserve,
)

from hangar.omd.factories.ocp.architectures import PROPULSION_ARCHITECTURES
from hangar.omd.factories.ocp.templates import AIRCRAFT_TEMPLATES
from hangar.omd.factories.ocp.defaults import (
    DEFAULT_MISSION_PARAMS,
    DEFAULT_SOLVER_SETTINGS,
    BASIC_MISSION_PHASES,
    FULL_MISSION_PHASES,
    _COMMON_FIELDS,
    _FUSELAGE_FIELDS,
    _PROPELLER_FIELDS,
    _HYBRID_FIELDS,
    _MULTI_ENGINE_FIELDS,
    _OEW_FIELDS,
    _register_fields,
)
from hangar.omd.factories.ocp.aircraft_model import _make_aircraft_model_class
from hangar.omd.factories.ocp.mission_values import (
    _collect_mission_values,
    _set_mission_values,
)


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
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a complete OpenMDAO mission problem.

    Args:
        defer_setup: If True, skip prob.setup() and set_val() calls.
            Mission values are put into metadata as
            initial_values_with_units for the materializer to apply.
        slots: Optional dict of slot overrides for the aircraft model.

    Returns (problem, metadata).
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
            if is_cfm56 or (slots and "propulsion" in slots):
                _register_fields(dv_comp, ac_data, _OEW_FIELDS)

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

    prob = om.Problem(reports=False)
    prob.model = AnalysisGroup()

    settings = {**DEFAULT_SOLVER_SETTINGS, **solver_settings}
    for key in ("atol", "rtol", "maxiter"):
        if key in settings:
            settings[key] = float(settings[key])
    settings["maxiter"] = int(settings["maxiter"])
    solver_type = settings.get("solver_type", "newton")

    if solver_type == "nlbgs":
        prob.model.nonlinear_solver = om.NonlinearBlockGS(
            iprint=0,
            maxiter=settings["maxiter"],
            atol=settings["atol"],
            rtol=settings["rtol"],
            use_aitken=settings.get("use_aitken", True),
        )
    else:
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

    var_paths: dict[str, str] = {
        "fuel_burn": "descent.fuel_used_final",
        "OEW": "climb.OEW",
        "MTOW": "ac|weights|MTOW",
    }
    if mission_type == "full":
        var_paths["TOFL"] = "rotate.range_final"

    _slot_subsys_map = {"propulsion": "propmodel", "drag": "drag"}
    if slots:
        from hangar.omd.slots import get_slot_provider
        for slot_name, slot_cfg in slots.items():
            if isinstance(slot_cfg, dict) and "provider" in slot_cfg:
                provider = get_slot_provider(slot_cfg["provider"])
                slot_dvs = getattr(provider, "design_variables", {})
                subsys = _slot_subsys_map.get(slot_name, slot_name)
                first_phase = phases[0] if phases else "climb"
                for short_name, rel_path in slot_dvs.items():
                    if "|" in rel_path:
                        var_paths[short_name] = rel_path
                    else:
                        var_paths[short_name] = f"{first_phase}.{subsys}.{rel_path}"

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
        "var_paths": var_paths,
        "declared_slots": {
            "drag": {"default": "PolarDrag"},
            "propulsion": {"default": architecture},
        },
    }

    if slots:
        metadata["active_slots"] = slots

    if defer_setup:
        metadata["initial_values_with_units"] = _collect_mission_values(
            params, phases, num_nodes, is_hybrid, mission_type,
        )
    else:
        prob.setup(check=False, mode="fwd")
        _set_mission_values(prob, params, phases, num_nodes, is_hybrid, mission_type)
        metadata["_setup_done"] = True

    return prob, metadata


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
) -> tuple[om.Problem, FactoryMetadata]:
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
) -> tuple[om.Problem, FactoryMetadata]:
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
) -> tuple[om.Problem, FactoryMetadata]:
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
