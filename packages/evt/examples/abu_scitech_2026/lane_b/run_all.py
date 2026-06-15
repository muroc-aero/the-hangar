"""Lane B: the case study through the hangar-evt MCP tool layer.

For each case, the five config sections from the vendored JSON are applied via
the section setters (the same path ``evt-cli`` and the MCP server take), then
``run_mission_analysis`` and ``run_sizing`` are run in-process. This exercises
the entire wrapper -- setter validation, config assembly, temp-file
serialization, ``Aircraft`` construction, result harvest, and the validation
findings -- so a parity mismatch against Lane A pinpoints a wrapper bug.

``run_sizing`` raises a tool error (USER_INPUT_ERROR) when evtolpy's MTOW
iteration diverges; this lane records that as ``sized_mtow_kg=None`` /
``converged=False``, matching Lane A's handling of the same cases.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import all_cases, case_id, config_path  # noqa: E402

from hangar.evt.tools.vehicle import (  # noqa: E402
    define_vehicle, set_environment, set_power, set_propulsion,
)
from hangar.evt.tools.mission import configure_mission  # noqa: E402
from hangar.evt.tools.analysis import run_mission_analysis, run_sizing  # noqa: E402


async def _apply_config(cfg: dict, session_id: str) -> None:
    await define_vehicle(params=dict(cfg["aircraft"]), session_id=session_id)
    await set_propulsion(params=dict(cfg["propulsion"]), session_id=session_id)
    await set_power(params=dict(cfg["power"]), session_id=session_id)
    await set_environment(params=dict(cfg["environ"]), session_id=session_id)
    await configure_mission(params=dict(cfg["mission"]), session_id=session_id)


async def run_case(vehicle: str, alt_ft: int, range_mi: int,
                   session_id: str = "default") -> dict:
    """Return the headline metrics for one case via the evt tools."""
    cfg = json.loads(config_path(vehicle, alt_ft, range_mi).read_text())
    await _apply_config(cfg, session_id)

    mission = (await run_mission_analysis(session_id=session_id))["results"]
    energy = mission["totals"]["total_mission_energy_kw_hr"]
    peak_power = max(mission["avg_electric_power_kw"].values())

    try:
        sizing = (await run_sizing(session_id=session_id))["results"]
        sized = sizing["sized_mtow_kg"]
        iters = sizing["iterations"]
        converged = bool(sizing["converged"])
    except ValueError:
        # The MTOW iteration diverged: evtolpy's safeguard raises, which the
        # in-process tool surfaces as ValueError (the envelope layer maps it to
        # USER_INPUT_ERROR). A real result for this vehicle/range, not a bug.
        sized = None
        iters = None
        converged = False

    return {
        "case_id": case_id(vehicle, alt_ft, range_mi),
        "vehicle": vehicle,
        "alt_ft": alt_ft,
        "range_mi": range_mi,
        "total_mission_energy_kw_hr": energy,
        "peak_avg_electric_power_kw": peak_power,
        "sized_mtow_kg": sized,
        "iterations": iters,
        "converged": converged,
    }


async def run_all(session_id: str = "default") -> list[dict]:
    """Run all 18 cases through the evt tools, in matrix order."""
    return [await run_case(v, alt, r, session_id) for (v, alt, r) in all_cases()]
