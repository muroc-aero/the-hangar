"""Mission configuration tool."""

from __future__ import annotations

from typing import Annotated, Any

from hangar.evt.tools.vehicle import _apply_section


async def configure_mission(
    params: Annotated[
        dict[str, Any],
        "Mission-section overrides as {key: value}, e.g. "
        "{'cruise_s': 720.0, 'cruise_h_m_p_s': 70.0}. Keys cover per-segment "
        "horizontal/vertical speeds (m/s) and durations (s) for the 18 mission "
        "segments, including reserves.",
    ],
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Override mission-profile parameters (segment speeds and durations).

    The mission defaults come from the loaded template; this overrides individual
    segment values. See the evt://reference resource for the full key list.
    """
    return await _apply_section("mission", params, session_id)
