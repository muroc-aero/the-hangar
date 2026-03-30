"""Extract results from solved OpenConcept mission problems."""

from __future__ import annotations

from typing import Any

import numpy as np
import openmdao.api as om


def _scalar(val: Any) -> float:
    """Convert OpenMDAO output (may be ndarray) to a plain float."""
    if isinstance(val, np.ndarray):
        return float(val.flat[0])
    return float(val)


def _safe_get(prob: om.Problem, path: str, units: str | None = None) -> float | None:
    """Get a value from the problem, returning None if the path doesn't exist."""
    try:
        if units:
            return _scalar(prob.get_val(path, units=units))
        return _scalar(prob.get_val(path))
    except KeyError:
        return None


def extract_mission_results(prob: om.Problem, metadata: dict) -> dict:
    """Extract key performance results from a solved mission problem.

    Returns a dict with fuel burn, OEW, TOFL, battery SOC, phase breakdown, etc.
    """
    results: dict = {}
    phases = metadata["phases"]

    # Fuel burn
    if metadata["has_fuel"]:
        fuel_burn = _safe_get(prob, "descent.fuel_used_final", "kg")
        if fuel_burn is None:
            fuel_burn = _safe_get(prob, "descent.fuel_used_final")
        results["fuel_burn_kg"] = fuel_burn

    # Operating empty weight
    oew = _safe_get(prob, "climb.OEW", "kg")
    if oew is None:
        oew = _safe_get(prob, "cruise.OEW", "kg")
    results["OEW_kg"] = oew

    # MTOW (from aircraft data)
    results["MTOW_kg"] = _safe_get(prob, "ac|weights|MTOW", "kg")

    # Takeoff field length (full mission only)
    if metadata.get("has_takeoff"):
        tofl = _safe_get(prob, "rotate.range_final", "ft")
        if tofl is None:
            tofl = _safe_get(prob, "v1vr.range_final", "ft")
        results["TOFL_ft"] = tofl

        stall = _safe_get(prob, "v0v1.Vstall_eas", "kn")
        results["stall_speed_kn"] = stall

    # Battery state of charge (hybrid/electric)
    if metadata.get("has_battery"):
        soc = _safe_get(prob, "descent.propmodel.batt1.SOC_final")
        results["battery_SOC_final"] = soc

    # MTOW margin (hybrid)
    if metadata.get("is_hybrid"):
        margin = _safe_get(prob, "margins.MTOW_margin", "lb")
        results["MTOW_margin_lb"] = margin

    # Phase-by-phase results
    phase_results = {}
    for phase in ["climb", "cruise", "descent"]:
        if phase not in phases:
            continue
        pr: dict = {}
        fuel = _safe_get(prob, f"{phase}.fuel_used_final", "kg")
        if fuel is not None:
            pr["fuel_used_kg"] = fuel
        dur = _safe_get(prob, f"{phase}.duration", "s")
        if dur is not None:
            pr["duration_s"] = dur
        if phase_results or pr:
            phase_results[phase] = pr

    if phase_results:
        results["phase_results"] = phase_results

    # Reserve fuel (with_reserve mission)
    if metadata.get("has_reserve"):
        total_fuel = _safe_get(prob, "loiter.fuel_used_final", "kg")
        if total_fuel is not None:
            results["total_fuel_with_reserve_kg"] = total_fuel

    return results


def extract_trajectory_data(prob: om.Problem, metadata: dict) -> dict:
    """Extract time-series trajectory data for visualization.

    Returns per-phase arrays of range, altitude, airspeed, fuel_used,
    throttle, vertical speed, and optionally battery SOC.
    """
    phases = metadata["phases"]
    nn = metadata["num_nodes"]
    trajectory: dict = {}

    for phase in phases:
        phase_data: dict = {}

        # Range
        rng = _safe_get_array(prob, f"{phase}.range", "NM", nn)
        if rng is not None:
            phase_data["range_NM"] = rng.tolist()

        # Altitude
        alt = _safe_get_array(prob, f"{phase}.fltcond|h", "ft", nn)
        if alt is not None:
            phase_data["altitude_ft"] = alt.tolist()

        # Airspeed
        eas = _safe_get_array(prob, f"{phase}.fltcond|Ueas", "kn", nn)
        if eas is not None:
            phase_data["airspeed_kn"] = eas.tolist()

        # Fuel used
        fuel = _safe_get_array(prob, f"{phase}.fuel_used", "kg", nn)
        if fuel is not None:
            phase_data["fuel_used_kg"] = fuel.tolist()

        # Throttle
        thr = _safe_get_array(prob, f"{phase}.throttle", None, nn)
        if thr is not None:
            phase_data["throttle"] = thr.tolist()

        # Vertical speed
        vs = _safe_get_array(prob, f"{phase}.fltcond|vs", "ft/min", nn)
        if vs is not None:
            phase_data["vertical_speed_ftmin"] = vs.tolist()

        # Battery SOC
        if metadata.get("has_battery"):
            soc = _safe_get_array(prob, f"{phase}.propmodel.batt1.SOC", None, nn)
            if soc is not None:
                phase_data["battery_SOC"] = soc.tolist()

        if phase_data:
            trajectory[phase] = phase_data

    return trajectory


def _safe_get_array(
    prob: om.Problem,
    path: str,
    units: str | None,
    nn: int,
) -> np.ndarray | None:
    """Get an array value from the problem, returning None if not found."""
    try:
        if units:
            val = prob.get_val(path, units=units)
        else:
            val = prob.get_val(path)
        arr = np.asarray(val).flatten()
        if len(arr) == nn:
            return arr
        return arr
    except (KeyError, ValueError):
        return None
