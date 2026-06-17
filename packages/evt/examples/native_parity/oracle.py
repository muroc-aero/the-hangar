"""Oracle helper for the native-evt parity suite.

Builds the evtolpy black-box ``Aircraft`` for a config and exposes every
quantity the native model must reproduce, so a component or the full sizing
group can be diffed against it to floating point. This is the single source of
golden values; tests and development scripts both import it.
"""

from __future__ import annotations

from typing import Any

from hangar.evt import builders
from hangar.evt.config.defaults import get_template
from hangar.evt.results import MASS_COMPONENTS, SEGMENT_KEYS


def baseline_config() -> dict:
    """The ``test_all`` lift+cruise baseline config (deep copy)."""
    return get_template("test_all")


def build(cfg: dict):
    """Build a fresh evtolpy ``Aircraft`` from a 5-section config."""
    return builders.build_aircraft(cfg)


# Scalar oracle quantities by domain. Geometry/propulsion/aero are read at the
# as-configured MTOW; mission energy/mass too (the sizing loop is separate).
GEOMETRY_PROPS = (
    "wing_area_m2",
    "wing_root_chord_m",
    "wing_mac_m",
    "wing_aspect_ratio",
    "horiz_tail_area_m2",
    "vert_tail_area_m2",
    "fuselage_fineness_ratio",
    "fuselage_wetted_area_m2",
)

AERO_PROPS = (
    "fuselage_cruise_reynolds",
    "fuselage_cf",
    "fuselage_cd0",
    "cruise_cl",
    "induced_drag_cdi",
    "cruise_cd",
    "cruise_l_p_d",
    "total_drag_coef",
)

# Propulsion: disk_area lives on the propulsion sub-object.
PROPULSION_PROPS = (
    "disk_loading_kg_p_m2",
    "over_torque_factor",
    "rotor_solidity",
)


def scalar(ac, name: str) -> float:
    return float(getattr(ac, name))


def disk_area(ac) -> float:
    return float(ac.propulsion.disk_area_m2)


def geometry(ac) -> dict[str, float]:
    return {p: scalar(ac, p) for p in GEOMETRY_PROPS}


def propulsion(ac) -> dict[str, float]:
    out = {p: scalar(ac, p) for p in PROPULSION_PROPS}
    out["disk_area_m2"] = disk_area(ac)
    return out


def aero(ac) -> dict[str, float]:
    return {p: scalar(ac, p) for p in AERO_PROPS}


def segment_energy(ac) -> dict[str, float]:
    return {k: scalar(ac, f"{k}_energy_kw_hr") for k in SEGMENT_KEYS}


def segment_power(ac) -> dict[str, float]:
    return {k: scalar(ac, f"{k}_avg_electric_power_kw") for k in SEGMENT_KEYS}


def masses(ac) -> dict[str, float]:
    return {attr: scalar(ac, attr) for attr, _ in MASS_COMPONENTS}


def totals(ac) -> dict[str, float]:
    return {
        "total_mission_energy_kw_hr": scalar(ac, "total_mission_energy_kw_hr"),
        "total_reserve_mission_energy_kw_hr": scalar(
            ac, "total_reserve_mission_energy_kw_hr"
        ),
        "empty_mass_kg": scalar(ac, "empty_mass_kg"),
        "battery_mass_kg": scalar(ac, "battery_mass_kg"),
    }


def all_scalars(ac) -> dict[str, Any]:
    """Every scalar oracle quantity for a one-shot diff."""
    out: dict[str, Any] = {}
    out.update(geometry(ac))
    out.update(propulsion(ac))
    out.update(aero(ac))
    out.update(totals(ac))
    return out
