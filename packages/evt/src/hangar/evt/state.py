"""evt session state: a typed session holding the working config.

Mirrors the per-package state modules in oas/ocp/pyc. evtolpy has a single
entry point -- ``Aircraft(path_to_json)`` -- so there is no per-engine or
per-surface registry; the session just accumulates the five-section config
dict that the section-setter tools mutate and the analysis tools build from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hangar.sdk.session.manager import Session, SessionManager
from hangar.sdk.state import artifacts  # noqa: F401 -- shared artifact store singleton


@dataclass
class EvtolSession(Session):
    """SDK session extended with the working vehicle config.

    ``config`` maps section name -> param dict (aircraft, mission, power,
    propulsion, environ). It starts empty; ``load_vehicle_template`` seeds it
    and the section setters merge overrides onto it. Analysis tools build a
    fresh ``Aircraft`` from this config on every call (construction is cheap
    and idempotent), so no live model object is cached -- ``_iterate_mtow``
    mutates the aircraft it runs on, and a fresh build per call sidesteps any
    stale-state hazard.
    """

    config: dict[str, dict] = field(default_factory=dict)

    def clear(self) -> None:
        super().clear()
        self.config.clear()


sessions = SessionManager(session_factory=EvtolSession)
