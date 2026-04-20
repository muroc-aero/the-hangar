"""Default mission parameters, solver settings, phase lists, and DictIndepVarComp field lists."""

from __future__ import annotations

from typing import Any


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
    "solver_type": "newton",
    "maxiter": 20,
    "atol": 1e-10,
    "rtol": 1e-10,
    "solve_subsystems": True,
    "use_aitken": True,
}

BASIC_MISSION_PHASES = ["climb", "cruise", "descent"]
FULL_MISSION_PHASES = ["v0v1", "v1vr", "v1v0", "rotate", "climb", "cruise", "descent"]
TAKEOFF_PHASES = ["v0v1", "v1vr", "v1v0", "rotate"]


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
