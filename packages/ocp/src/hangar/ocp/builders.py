"""Build OpenMDAO problems from OCP session state.

Assembles analysis groups with DictIndepVarComp, mission profiles, and
solver configuration -- mirroring what each OpenConcept example does in
its ``AnalysisGroup`` and ``configure_problem()`` functions.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import openmdao.api as om

from openconcept.utilities import DictIndepVarComp
from openconcept.mission import BasicMission, FullMissionAnalysis, MissionWithReserve

from hangar.ocp.aircraft import make_aircraft_model_class
from hangar.ocp.config.defaults import (
    DEFAULT_MISSION_PARAMS,
    DEFAULT_SOLVER_SETTINGS,
    PROPULSION_ARCHITECTURES,
    FULL_MISSION_PHASES,
    BASIC_MISSION_PHASES,
    TAKEOFF_PHASES,
)


# ---------------------------------------------------------------------------
# DictIndepVarComp field registration
# ---------------------------------------------------------------------------

# Common fields that all aircraft data dicts should have
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

# Fields only present for architectures with fuselage weight models
_FUSELAGE_FIELDS = [
    "ac|geom|fuselage|S_wet",
    "ac|geom|fuselage|width",
    "ac|geom|fuselage|length",
    "ac|geom|fuselage|height",
]

# Fields for propeller-based architectures
_PROPELLER_FIELDS = [
    "ac|propulsion|propeller|diameter",
]

# Fields for hybrid architectures
_HYBRID_FIELDS = [
    "ac|propulsion|motor|rating",
    "ac|propulsion|generator|rating",
    "ac|weights|W_battery",
]

# Fields for multi-engine architectures
_MULTI_ENGINE_FIELDS = [
    "ac|num_engines",
]

# Fields for B738-style with OEW in data
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


def build_mission_problem(
    aircraft_data: dict,
    architecture: str,
    mission_type: str,
    mission_params: dict,
    num_nodes: int,
    solver_settings: dict,
    propulsion_overrides: dict | None = None,
) -> tuple[om.Problem, dict]:
    """Build a complete OpenMDAO problem from the session configuration.

    Parameters
    ----------
    aircraft_data
        The OpenConcept aircraft data dict (``{"ac": {...}}``).
    architecture
        Propulsion architecture key.
    mission_type
        One of "full", "basic", "with_reserve".
    mission_params
        Mission parameters (cruise altitude, range, phase speeds, etc.).
    num_nodes
        Number of analysis nodes per phase.
    solver_settings
        Newton solver configuration.
    propulsion_overrides
        Optional propulsion parameter overrides.

    Returns
    -------
    tuple[om.Problem, dict]
        The ready-to-run problem and a metadata dict with phase names,
        output paths, and configuration details.
    """
    arch_info = PROPULSION_ARCHITECTURES[architecture]
    is_hybrid = arch_info["has_battery"] and arch_info["has_fuel"]
    is_cfm56 = arch_info["prop_class"] == "CFM56"

    # Create the dynamic aircraft model class
    AircraftModelClass = make_aircraft_model_class(architecture, propulsion_overrides)

    # Select mission profile class
    if mission_type == "basic":
        MissionClass = BasicMission
        phases = list(BASIC_MISSION_PHASES)
    elif mission_type == "with_reserve":
        MissionClass = MissionWithReserve
        phases = ["climb", "cruise", "descent",
                  "reserve_climb", "reserve_cruise", "reserve_descent", "loiter"]
    else:  # "full"
        MissionClass = FullMissionAnalysis
        phases = list(FULL_MISSION_PHASES)

    # Build the analysis group
    ac_data = copy.deepcopy(aircraft_data)

    class AnalysisGroup(om.Group):
        def setup(self):
            # Register aircraft data as independent variables
            dv_comp = self.add_subsystem(
                "dv_comp",
                DictIndepVarComp(ac_data),
                promotes_outputs=["*"],
            )

            # Register common fields
            _register_fields(dv_comp, ac_data, _COMMON_FIELDS)

            # Register architecture-specific fields
            if not is_cfm56:
                _register_fields(dv_comp, ac_data, _PROPELLER_FIELDS)
            _register_fields(dv_comp, ac_data, _FUSELAGE_FIELDS)
            if is_hybrid:
                _register_fields(dv_comp, ac_data, _HYBRID_FIELDS)
            if arch_info["num_engines"] > 1:
                _register_fields(dv_comp, ac_data, _MULTI_ENGINE_FIELDS)
            if is_cfm56:
                _register_fields(dv_comp, ac_data, _OEW_FIELDS)

            # Battery specific energy (if hybrid, add as explicit output)
            if is_hybrid:
                spec_energy = 300  # default Wh/kg
                if propulsion_overrides and "battery_specific_energy" in propulsion_overrides:
                    spec_energy = propulsion_overrides["battery_specific_energy"]
                dv_comp.add_output(
                    "ac|propulsion|battery|specific_energy",
                    val=spec_energy,
                    units="W*h/kg",
                )

            # Mission data for hybrid (SOC target)
            if is_hybrid:
                mission_data = self.add_subsystem(
                    "mission_data_comp",
                    om.IndepVarComp(),
                    promotes_outputs=["*"],
                )
                mission_data.add_output("batt_soc_target", val=0.1, units=None)

            # Add mission analysis
            self.add_subsystem(
                "analysis",
                MissionClass(num_nodes=num_nodes, aircraft_model=AircraftModelClass),
                promotes_inputs=["*"],
                promotes_outputs=["*"],
            )

            # Add weight margins for hybrid (from HybridTwin.py pattern)
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

                # Mixed objective (fuel burn + MTOW/100)
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

    # Solver setup
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

    prob.setup(check=False, mode="fwd")

    # Set mission parameters
    params = {**DEFAULT_MISSION_PARAMS, **mission_params}
    _set_mission_values(prob, params, phases, num_nodes, is_hybrid, mission_type)

    # Build metadata
    metadata = {
        "architecture": architecture,
        "mission_type": mission_type,
        "phases": phases,
        "num_nodes": num_nodes,
        "has_fuel": arch_info["has_fuel"],
        "has_battery": arch_info["has_battery"],
        "is_hybrid": is_hybrid,
        "is_cfm56": is_cfm56,
        "has_takeoff": mission_type == "full",
        "has_reserve": mission_type == "with_reserve",
    }

    return prob, metadata


def _set_mission_values(
    prob: om.Problem,
    params: dict,
    phases: list[str],
    num_nodes: int,
    is_hybrid: bool,
    mission_type: str,
) -> None:
    """Set mission parameter values on the problem."""
    nn = num_nodes

    # Phase speeds and vertical speeds
    if "climb" in phases:
        prob.set_val(
            "climb.fltcond|vs",
            np.ones((nn,)) * params.get("climb_vs_ftmin", 850.0),
            units="ft/min",
        )
        prob.set_val(
            "climb.fltcond|Ueas",
            np.ones((nn,)) * params.get("climb_Ueas_kn", 104.0),
            units="kn",
        )

    if "cruise" in phases:
        prob.set_val(
            "cruise.fltcond|vs",
            np.ones((nn,)) * params.get("cruise_vs_ftmin", 0.01),
            units="ft/min",
        )
        prob.set_val(
            "cruise.fltcond|Ueas",
            np.ones((nn,)) * params.get("cruise_Ueas_kn", 129.0),
            units="kn",
        )

    if "descent" in phases:
        vs_descent = params.get("descent_vs_ftmin", -400.0)
        # Ensure descent vs is negative
        if vs_descent > 0:
            vs_descent = -vs_descent
        prob.set_val(
            "descent.fltcond|vs",
            np.ones((nn,)) * vs_descent,
            units="ft/min",
        )
        prob.set_val(
            "descent.fltcond|Ueas",
            np.ones((nn,)) * params.get("descent_Ueas_kn", 100.0),
            units="kn",
        )

    # Cruise altitude and range
    prob.set_val("cruise|h0", params.get("cruise_altitude_ft", 18000.0), units="ft")
    prob.set_val("mission_range", params.get("mission_range_NM", 250.0), units="NM")

    # Reserve phases (MissionWithReserve)
    if mission_type == "with_reserve":
        reserve_alt = params.get("reserve_altitude_ft", 15000.0)
        prob.set_val("reserve|h0", reserve_alt, units="ft")

        reserve_climb_vs = params.get("reserve_climb_vs_ftmin", 1500.0)
        reserve_climb_Ueas = params.get("reserve_climb_Ueas_kn", 124.0)
        reserve_cruise_Ueas = params.get("reserve_cruise_Ueas_kn", 170.0)
        reserve_descent_vs = params.get("reserve_descent_vs_ftmin", -600.0)
        reserve_descent_Ueas = params.get("reserve_descent_Ueas_kn", 140.0)
        loiter_Ueas = params.get("loiter_Ueas_kn", 200.0)

        prob.set_val("reserve_climb.fltcond|vs", np.ones((nn,)) * reserve_climb_vs, units="ft/min")
        prob.set_val("reserve_climb.fltcond|Ueas", np.ones((nn,)) * reserve_climb_Ueas, units="kn")
        prob.set_val("reserve_cruise.fltcond|vs", np.ones((nn,)) * 4.0, units="ft/min")
        prob.set_val("reserve_cruise.fltcond|Ueas", np.ones((nn,)) * reserve_cruise_Ueas, units="kn")
        prob.set_val("reserve_descent.fltcond|vs", np.ones((nn,)) * reserve_descent_vs, units="ft/min")
        prob.set_val("reserve_descent.fltcond|Ueas", np.ones((nn,)) * reserve_descent_Ueas, units="kn")
        prob.set_val("loiter.fltcond|vs", np.zeros((nn,)), units="ft/min")
        prob.set_val("loiter.fltcond|Ueas", np.ones((nn,)) * loiter_Ueas, units="kn")

    # Takeoff speed guesses (FullMissionAnalysis)
    if mission_type == "full":
        prob.set_val("v0v1.fltcond|Utrue", np.ones((nn,)) * 40, units="kn")
        prob.set_val("v1vr.fltcond|Utrue", np.ones((nn,)) * 70, units="kn")
        prob.set_val("v1v0.fltcond|Utrue", np.ones((nn,)) * 60, units="kn")
        prob.set_val("rotate.fltcond|Utrue", np.ones((nn,)) * 80, units="kn")

        # Full throttle during takeoff
        prob.set_val("v0v1.throttle", np.ones((nn,)))
        prob.set_val("v1vr.throttle", np.ones((nn,)))
        prob.set_val("rotate.throttle", np.ones((nn,)))

    # Payload (for hybrid/reserve missions)
    payload_lb = params.get("payload_lb")
    if payload_lb is not None:
        try:
            prob.set_val("payload", payload_lb, units="lb")
        except KeyError:
            pass

    # Hybridization fractions
    if is_hybrid:
        climb_hyb = params.get("climb_hybridization")
        cruise_hyb = params.get("cruise_hybridization")
        descent_hyb = params.get("descent_hybridization")

        if cruise_hyb is not None and "cruise" in phases:
            prob.set_val("cruise.hybridization", cruise_hyb)
        if climb_hyb is not None and "climb" in phases:
            prob.set_val("climb.hybridization", climb_hyb)
        if descent_hyb is not None and "descent" in phases:
            prob.set_val("descent.hybridization", descent_hyb)

    # Battery specific energy override
    spec_energy = params.get("battery_specific_energy")
    if spec_energy is not None:
        try:
            prob.set_val(
                "ac|propulsion|battery|specific_energy",
                spec_energy,
                units="W*h/kg",
            )
        except KeyError:
            pass
