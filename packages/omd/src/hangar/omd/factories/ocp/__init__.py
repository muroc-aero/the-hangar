"""OpenConcept mission component factories.

Builds OpenConcept mission analysis problems from plan YAML configs using
upstream openconcept and openmdao APIs directly. No dependency on hangar-ocp.

Public API:
    build_ocp_basic_mission
    build_ocp_full_mission
    build_ocp_mission_with_reserve
    AIRCRAFT_TEMPLATES
    PROPULSION_ARCHITECTURES
"""

from hangar.omd.factories.ocp.architectures import PROPULSION_ARCHITECTURES
from hangar.omd.factories.ocp.templates import AIRCRAFT_TEMPLATES
from hangar.omd.factories.ocp.builder import (
    build_ocp_basic_mission,
    build_ocp_full_mission,
    build_ocp_mission_with_reserve,
)

__all__ = [
    "build_ocp_basic_mission",
    "build_ocp_full_mission",
    "build_ocp_mission_with_reserve",
    "AIRCRAFT_TEMPLATES",
    "PROPULSION_ARCHITECTURES",
]
