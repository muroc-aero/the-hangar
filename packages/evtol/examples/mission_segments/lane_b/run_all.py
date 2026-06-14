"""Lane B: drive the same config through the hangar-evtol MCP tools.

Builds the full five-section config from ``shared.CONFIG`` using the section
setters (no template involved), then runs the mission and sizing tools. This
exercises the entire wrapper path -- setter validation, config assembly, temp-
file serialization, ``Aircraft`` construction, and result harvest -- so a parity
mismatch against Lane A pinpoints a wrapper bug.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import CONFIG  # noqa: E402

from hangar.evtol.tools.vehicle import (  # noqa: E402
    define_vehicle, set_environment, set_power, set_propulsion,
)
from hangar.evtol.tools.mission import configure_mission  # noqa: E402
from hangar.evtol.tools.analysis import run_mission_analysis, run_sizing  # noqa: E402


async def _apply_config(session_id: str = "default") -> None:
    await define_vehicle(params=dict(CONFIG["aircraft"]), session_id=session_id)
    await set_propulsion(params=dict(CONFIG["propulsion"]), session_id=session_id)
    await set_power(params=dict(CONFIG["power"]), session_id=session_id)
    await set_environment(params=dict(CONFIG["environ"]), session_id=session_id)
    await configure_mission(params=dict(CONFIG["mission"]), session_id=session_id)


async def run_mission(session_id: str = "default") -> dict:
    """Apply the config and return the run_mission_analysis results payload."""
    await _apply_config(session_id)
    envelope = await run_mission_analysis(session_id=session_id)
    return envelope["results"]


async def run_sizing_lane(session_id: str = "default") -> dict:
    """Apply the config and return the run_sizing results payload."""
    await _apply_config(session_id)
    envelope = await run_sizing(session_id=session_id)
    return envelope["results"]
