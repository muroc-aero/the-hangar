"""pyc session state: typed session with an engine registry.

Mirrors the per-package state modules in oas/ocp. The engine registry used
to be duck-punched onto the shared SDK ``Session`` (``session.engines``
created via ``hasattr`` checks scattered across tools); it is a real
dataclass field here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hangar.sdk.session.manager import Session, SessionManager
from hangar.sdk.state import artifacts  # noqa: F401 -- shared artifact store singleton


@dataclass
class PycSession(Session):
    """SDK session extended with the named-engine registry.

    Each entry: name -> {archetype, params, design_solved, design_conditions}.
    """

    engines: dict[str, dict] = field(default_factory=dict)

    def clear(self) -> None:
        super().clear()
        self.engines.clear()


sessions = SessionManager(session_factory=PycSession)
