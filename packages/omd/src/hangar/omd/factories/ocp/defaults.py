"""Default mission parameters, solver settings, phase lists, and DictIndepVarComp field lists."""

from __future__ import annotations

from typing import Any

from hangar.omd.factory_metadata import VarSpec


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


# Single source of truth for common DictIndepVarComp fields. The
# FactoryContract in ``factories/ocp/builder.py`` derives ``produces``
# from this mapping so that adding a field here auto-extends the
# contract for the next ``composition_policy: auto`` run. Units are
# ``None`` for fields whose units vary by template (e.g. gear lengths
# are ``ft`` in b738 but ``m`` elsewhere); the contract-integrity
# validator only checks units that are pinned here.
_COMMON_FIELD_SPECS: dict[str, VarSpec] = {
    "ac|aero|CLmax_TO": VarSpec(default=2.0, semantic_tag="geometry"),
    "ac|aero|polar|e": VarSpec(default=0.78, semantic_tag="geometry"),
    "ac|aero|polar|CD0_TO": VarSpec(default=0.03, semantic_tag="geometry"),
    "ac|aero|polar|CD0_cruise": VarSpec(
        default=0.018, semantic_tag="geometry",
    ),
    "ac|geom|wing|S_ref": VarSpec(
        units="m**2", default=124.6, semantic_tag="geometry",
    ),
    "ac|geom|wing|AR": VarSpec(default=9.45, semantic_tag="geometry"),
    "ac|geom|wing|c4sweep": VarSpec(
        units="deg", default=25.0, semantic_tag="geometry",
    ),
    "ac|geom|wing|taper": VarSpec(default=0.159, semantic_tag="geometry"),
    "ac|geom|wing|toverc": VarSpec(default=0.12, semantic_tag="geometry"),
    "ac|geom|hstab|S_ref": VarSpec(
        units="m**2", default=32.8, semantic_tag="geometry",
    ),
    "ac|geom|hstab|c4_to_wing_c4": VarSpec(
        units="m", default=17.9, semantic_tag="geometry",
    ),
    "ac|geom|vstab|S_ref": VarSpec(
        units="m**2", default=26.4, semantic_tag="geometry",
    ),
    # Gear lengths vary between ft and m across templates -- leave units unset.
    "ac|geom|nosegear|length": VarSpec(default=1.3, semantic_tag="geometry"),
    "ac|geom|maingear|length": VarSpec(default=1.8, semantic_tag="geometry"),
    "ac|weights|MTOW": VarSpec(
        units="kg", default=79002.0, semantic_tag="weight",
    ),
    "ac|weights|W_fuel_max": VarSpec(
        units="kg", default=20826.0, semantic_tag="weight",
    ),
    "ac|weights|MLW": VarSpec(
        units="kg", default=66360.0, semantic_tag="weight",
    ),
    "ac|propulsion|engine|rating": VarSpec(
        units="lbf", default=27000.0, semantic_tag="propulsion",
    ),
    "ac|num_passengers_max": VarSpec(
        default=189, semantic_tag="mission_param",
    ),
    # q_cruise units differ between templates (imperial vs SI).
    "ac|q_cruise": VarSpec(default=7500.0, semantic_tag="mission_param"),
}

_COMMON_FIELDS = list(_COMMON_FIELD_SPECS.keys())

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
