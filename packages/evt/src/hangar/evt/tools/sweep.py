"""Parameter sweep tool -- run_parameter_sweep."""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Annotated

from hangar.sdk.helpers import _suppress_output
from hangar.evt.state import sessions as _sessions

from hangar.evt.builders import build_aircraft
from hangar.evt.validators import validate_config_present, validate_sweep_param
from hangar.evt.config.defaults import INT_KEYS
from hangar.evt.tools._helpers import _finalize_analysis, _make_run_id

# Output metrics a sweep can collect. "sized_mtow_kg" runs the MTOW iteration
# per point; the rest read properties from the unsized aircraft.
METRICS = {
    "total_mission_energy_kw_hr": lambda ac: float(ac.total_mission_energy_kw_hr),
    "total_reserve_mission_energy_kw_hr": lambda ac: float(
        ac.total_reserve_mission_energy_kw_hr
    ),
    "battery_mass_kg": lambda ac: float(ac.battery_mass_kg),
    "empty_mass_kg": lambda ac: float(ac.empty_mass_kg),
    "cruise_l_p_d": lambda ac: float(ac.cruise_l_p_d),
    "cruise_avg_electric_power_kw": lambda ac: float(ac.cruise_avg_electric_power_kw),
    "disk_loading_kg_p_m2": lambda ac: float(ac.disk_loading_kg_p_m2),
    "sized_mtow_kg": lambda ac: float(ac._iterate_mtow()[0]),
}


async def run_parameter_sweep(
    param: Annotated[
        str,
        "Config key to sweep as 'section.key', e.g. "
        "'power.batt_spec_energy_w_h_p_kg' or 'mission.cruise_s'.",
    ],
    values: Annotated[
        list[float],
        "Explicit list of values to evaluate the parameter at.",
    ],
    metric: Annotated[
        str,
        "Output metric to collect. One of: " + ", ".join(sorted(METRICS)),
    ] = "total_mission_energy_kw_hr",
    run_name: Annotated[str | None, "Optional label for this run"] = None,
    session_id: Annotated[str, "Session ID"] = "default",
) -> dict:
    """Sweep one config parameter over a list of values and collect a metric.

    For each value the vehicle config is rebuilt and the chosen ``metric`` is
    evaluated. ``sized_mtow_kg`` converges MTOW at each point (slower); all other
    metrics read the unsized aircraft. Points that raise (e.g. a diverging MTOW)
    are recorded with a null metric and an ``error`` note rather than aborting
    the sweep.

    Returns a versioned response envelope with a list of ``{value, metric}`` points.
    """
    t0 = time.perf_counter()
    session = _sessions.get(session_id)
    config = validate_config_present(session)
    section, key = validate_sweep_param(param)

    if metric not in METRICS:
        raise ValueError(
            f"Unknown metric {metric!r}. Valid: {sorted(METRICS)}"
        )
    if not values:
        raise ValueError("values must be a non-empty list.")

    metric_fn = METRICS[metric]
    run_id = _make_run_id()

    def _run():
        points = []
        for raw in values:
            val = int(raw) if key in INT_KEYS else float(raw)
            cfg = copy.deepcopy(config)
            cfg.setdefault(section, {})[key] = val
            point = {"value": val, "metric": None}
            try:
                aircraft = build_aircraft(cfg)
                point["metric"] = metric_fn(aircraft)
            except Exception as exc:  # diverging MTOW / infeasible point
                point["error"] = str(exc).splitlines()[0]
            points.append(point)
        return points

    points = await asyncio.to_thread(_suppress_output, _run)

    valid = [p["metric"] for p in points if p["metric"] is not None]
    results = {
        "param": param,
        "metric": metric,
        "points": points,
        "summary": {
            "evaluated": len(points),
            "succeeded": len(valid),
            "min": min(valid) if valid else None,
            "max": max(valid) if valid else None,
        },
    }
    findings: list = []

    inputs = {"param": param, "metric": metric, "n_values": len(values)}

    return await _finalize_analysis(
        tool_name="run_parameter_sweep",
        run_id=run_id,
        session=session,
        session_id=session_id,
        analysis_type="sweep",
        inputs=inputs,
        results=results,
        findings=findings,
        t0=t0,
        run_name=run_name,
    )
