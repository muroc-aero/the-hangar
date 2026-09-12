"""avy session state: typed session with an aircraft registry.

Mirrors the per-package state modules in oas/ocp/pyc. Each aircraft entry
holds the template deck, deck overrides, and the configured mission, so an
analysis call can rebuild the full Aviary problem from session state alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathlib import Path

from hangar.sdk.session.manager import Session, SessionManager
from hangar.sdk.state import artifacts  # noqa: F401 -- shared artifact store singleton

# Aviary runs chdir into per-run scratch dirs (see runner.py), so the shared
# store's default *relative* data dir (./hangar_data) would resolve against
# whichever scratch dir holds the run lock. Pin it to an absolute path at
# import time (server/CLI startup, before any run).
artifacts._data_dir = Path(artifacts._data_dir).resolve()


@dataclass
class AvySession(Session):
    """SDK session extended with the named-aircraft registry.

    Each entry: name -> {template, deck_path, overrides, mission, sized_run_id}.
    """

    aircraft: dict[str, dict] = field(default_factory=dict)

    def clear(self) -> None:
        super().clear()
        self.aircraft.clear()


sessions = SessionManager(session_factory=AvySession)
