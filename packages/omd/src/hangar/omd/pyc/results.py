"""Result extraction from solved pyCycle problems.

Pulls performance metrics, flow station data, and component details from
an OpenMDAO problem containing a pyCycle cycle model.
"""

from __future__ import annotations

from typing import Any

import openmdao.api as om


def _scalar(val) -> float:
    """Coerce an array-like to a Python float."""
    try:
        return float(val[0])
    except (IndexError, TypeError):
        return float(val)


def _safe_get(prob: om.Problem, path: str, units: str | None = None) -> float | None:
    """Get a value from the problem, returning None on KeyError."""
    try:
        if units:
            return _scalar(prob.get_val(path, units=units))
        return _scalar(prob[path])
    except (KeyError, RuntimeError):
        return None


# ---------------------------------------------------------------------------
# Flow station extraction
# ---------------------------------------------------------------------------

_FLOW_VARS = [
    ("tot:P", "psia"),
    ("tot:T", "degR"),
    ("tot:h", "Btu/lbm"),
    ("tot:S", "Btu/(lbm*degR)"),
    ("stat:P", "psia"),
    ("stat:W", "lbm/s"),
    ("stat:MN", None),
    ("stat:V", "ft/s"),
    ("stat:area", "inch**2"),
]


def extract_flow_stations(
    prob: om.Problem,
    point: str,
    station_names: list[str],
) -> dict[str, dict[str, float | None]]:
    """Extract flow station properties for named stations.

    Parameters
    ----------
    prob : om.Problem
        Solved pyCycle problem.
    point : str
        Point name prefix (e.g. "DESIGN" or "" for single-point).
    station_names : list[str]
        Element flow station names (e.g. ["fc.Fl_O", "comp.Fl_O"]).

    Returns
    -------
    dict mapping station name -> {var: value}.
    """
    stations = {}
    for fs_name in station_names:
        prefix = f"{point}.{fs_name}" if point else fs_name
        data: dict[str, float | None] = {}
        for var, units in _FLOW_VARS:
            path = f"{prefix}:{var}"
            data[var] = _safe_get(prob, path)
        stations[fs_name] = data
    return stations


# ---------------------------------------------------------------------------
# Component extraction
# ---------------------------------------------------------------------------

def extract_compressor(prob: om.Problem, point: str, name: str) -> dict:
    """Extract compressor performance."""
    prefix = f"{point}.{name}" if point else name
    return {
        "PR": _safe_get(prob, f"{prefix}.PR"),
        "eff": _safe_get(prob, f"{prefix}.eff"),
        "Wc": _safe_get(prob, f"{prefix}.Wc"),
        "Nc": _safe_get(prob, f"{prefix}.Nc"),
        "pwr": _safe_get(prob, f"{prefix}.power", units="hp"),
        "trq": _safe_get(prob, f"{prefix}.trq", units="ft*lbf"),
        "map_RlineMap": _safe_get(prob, f"{prefix}.map.RlineMap"),
    }


def extract_turbine(prob: om.Problem, point: str, name: str) -> dict:
    """Extract turbine performance."""
    prefix = f"{point}.{name}" if point else name
    return {
        "PR": _safe_get(prob, f"{prefix}.PR"),
        "eff": _safe_get(prob, f"{prefix}.eff"),
        "Wp": _safe_get(prob, f"{prefix}.Wp"),
        "Np": _safe_get(prob, f"{prefix}.Np"),
        "pwr": _safe_get(prob, f"{prefix}.power", units="hp"),
        "trq": _safe_get(prob, f"{prefix}.trq", units="ft*lbf"),
    }


def extract_burner(prob: om.Problem, point: str, name: str) -> dict:
    """Extract burner data."""
    prefix = f"{point}.{name}" if point else name
    return {
        "FAR": _safe_get(prob, f"{prefix}.Fl_I:FAR"),
        "Wfuel": _safe_get(prob, f"{prefix}.Wfuel"),
        "dPqP": _safe_get(prob, f"{prefix}.dPqP"),
    }


def extract_shaft(prob: om.Problem, point: str, name: str) -> dict:
    """Extract shaft data."""
    prefix = f"{point}.{name}" if point else name
    return {
        "Nmech": _safe_get(prob, f"{prefix}.Nmech", units="rpm"),
        "pwr_net": _safe_get(prob, f"{prefix}.pwr_net", units="hp"),
    }


def extract_nozzle(prob: om.Problem, point: str, name: str) -> dict:
    """Extract nozzle data."""
    prefix = f"{point}.{name}" if point else name
    return {
        "Fg": _safe_get(prob, f"{prefix}.Fg", units="lbf"),
        "PR": _safe_get(prob, f"{prefix}.PR"),
        "Cv": _safe_get(prob, f"{prefix}.Cv"),
        "throat_area": _safe_get(prob, f"{prefix}.Throat:stat:area"),
    }


# ---------------------------------------------------------------------------
# Full result extraction
# ---------------------------------------------------------------------------

def extract_cycle_results(
    prob: om.Problem,
    point: str,
    archetype_meta: dict,
) -> dict[str, Any]:
    """Extract full results from a solved cycle point.

    Parameters
    ----------
    prob : om.Problem
        Solved pyCycle problem.
    point : str
        Point name prefix (e.g. "DESIGN", "OD0", or "" for single-point).
    archetype_meta : dict
        Archetype metadata (elements, flow_stations, compressors, etc.).

    Returns
    -------
    dict with keys: performance, flow_stations, components.
    """
    prefix = f"{point}." if point else ""

    # Performance
    performance = {
        "Fn": _safe_get(prob, f"{prefix}perf.Fn", units="lbf"),
        "Fg": _safe_get(prob, f"{prefix}perf.Fg", units="lbf"),
        "TSFC": _safe_get(prob, f"{prefix}perf.TSFC"),
        "OPR": _safe_get(prob, f"{prefix}perf.OPR"),
        "Wfuel": _safe_get(prob, f"{prefix}perf.Wfuel_0"),
        "ram_drag": _safe_get(prob, f"{prefix}inlet.F_ram", units="lbf"),
        "mass_flow": _safe_get(prob, f"{prefix}inlet.Fl_O:stat:W"),
    }

    # Flow stations
    flow_stations = extract_flow_stations(
        prob, point, archetype_meta.get("flow_stations", [])
    )

    # Components
    components: dict[str, Any] = {}
    for comp_name in archetype_meta.get("compressors", []):
        components[comp_name] = extract_compressor(prob, point, comp_name)
    for turb_name in archetype_meta.get("turbines", []):
        components[turb_name] = extract_turbine(prob, point, turb_name)
    for burn_name in archetype_meta.get("burners", []):
        components[burn_name] = extract_burner(prob, point, burn_name)
    for shaft_name in archetype_meta.get("shafts", []):
        components[shaft_name] = extract_shaft(prob, point, shaft_name)
    for nozz_name in archetype_meta.get("nozzles", []):
        components[nozz_name] = extract_nozzle(prob, point, nozz_name)

    return {
        "performance": performance,
        "flow_stations": flow_stations,
        "components": components,
    }
