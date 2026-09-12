"""External subsystem registry for Aviary runs.

Aviary's ``SubsystemBuilder`` interface lets an external OpenMDAO system
join the sizing problem (pre-mission or mission). This package wraps the
builders hangar-avy ships behind a name registry + JSON-config surface,
mirroring ``MISSION_TEMPLATES`` in ``hangar.avy.missions``.
"""

from hangar.avy.subsystems.registry import (
    EXTERNAL_SUBSYSTEMS,
    build_external_subsystems,
    list_external_subsystems_info,
    validate_subsystem_spec,
)

__all__ = [
    "EXTERNAL_SUBSYSTEMS",
    "build_external_subsystems",
    "list_external_subsystems_info",
    "validate_subsystem_spec",
]
