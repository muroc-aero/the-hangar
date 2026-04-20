"""Mission parameter value collection and application for OpenConcept missions."""

from __future__ import annotations

import numpy as np
import openmdao.api as om


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

    Phase speed values can be scalars (broadcast to constant arrays) or
    two-element [start, end] lists (expanded via np.linspace).
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

    payload_lb = params.get("payload_lb")
    if payload_lb is not None:
        vals["payload"] = {"val": payload_lb, "units": "lb"}

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
