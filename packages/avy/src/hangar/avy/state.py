"""avy session state: typed session with an aircraft registry.

Mirrors the per-package state modules in oas/ocp/pyc. Each aircraft entry
holds the template deck, deck overrides, and the configured mission, so an
analysis call can rebuild the full Aviary problem from session state alone.

The session also keeps the last converged sizing per aircraft as a live
AviaryProblem (``sized``) so run_off_design / run_payload_range can fly
from it instead of re-running the sizing, and a memo of precompute-mode
subsystem sub-optimizations (``sub_opt_cache``). Both are keyed by content
fingerprints, so a changed deck override, mission, or subsystem config
never reuses a stale result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hangar.sdk.session.manager import Session, SessionManager
from hangar.sdk.state import artifacts  # noqa: F401 -- shared artifact store singleton

# Aviary runs chdir into per-run scratch dirs (see runner.py), so the shared
# store's default *relative* data dir (./hangar_data) would resolve against
# whichever scratch dir holds the run lock. Pin it to an absolute path at
# import time (server/CLI startup, before any run).
artifacts._data_dir = Path(artifacts._data_dir).resolve()


def sizing_fingerprint(aircraft_cfg: dict, optimizer: str, max_iter: int) -> str:
    """Content hash of everything that determines a sizing result.

    Deck, overrides, the *configured* (unmutated) mission, the attached
    external subsystems, and the driver settings. The subsystem coupling
    mode is deliberately NOT part of it: coupled and precompute produce
    the same sized aircraft (feed-forward topology), so either may serve
    an off-design run.
    """
    mission = aircraft_cfg.get("mission")
    payload = {
        "deck": aircraft_cfg["deck"],
        "overrides": aircraft_cfg.get("overrides") or {},
        "phase_info": mission["phase_info"] if mission else None,
        "external_subsystems": aircraft_cfg.get("external_subsystems") or [],
        "optimizer": optimizer,
        "max_iter": max_iter,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class SizedProblem:
    """A live, converged AviaryProblem kept for off-design reuse.

    ``run_id`` is the run that produced it (run_sizing, or the internal
    sizing of an off-design run); ``fingerprint`` is what it was sized
    from (see ``sizing_fingerprint``).
    """

    run_id: str
    fingerprint: str
    prob: Any = field(repr=False)


@dataclass
class AvySession(Session):
    """SDK session extended with the named-aircraft registry.

    Each ``aircraft`` entry: name -> {template, deck, mass_method,
    mission_method, overrides, mission, external_subsystems, sized_run_id}
    (``sized_run_id`` is the run_id of the cached sizing in ``sized``, if
    any).
    """

    aircraft: dict[str, dict] = field(default_factory=dict)

    # aircraft name -> last converged sizing (live problem; see module doc).
    # One entry per aircraft: a new sizing replaces the old one, a failed
    # sizing drops it. Not JSON state -- never serialize.
    sized: dict[str, SizedProblem] = field(default_factory=dict, repr=False)

    # precompute-mode sub-opt memo: content key -> wing mass (lbm)
    sub_opt_cache: dict[str, float] = field(default_factory=dict, repr=False)

    def cache_sized(self, aircraft_name: str, run_id: str, fingerprint: str, prob: Any) -> None:
        self.sized[aircraft_name] = SizedProblem(run_id, fingerprint, prob)
        self.aircraft[aircraft_name]["sized_run_id"] = run_id

    def drop_sized(self, aircraft_name: str) -> None:
        self.sized.pop(aircraft_name, None)
        if aircraft_name in self.aircraft:
            self.aircraft[aircraft_name]["sized_run_id"] = None

    def get_sized(self, aircraft_name: str, fingerprint: str) -> SizedProblem | None:
        """The cached sizing for this aircraft if it matches ``fingerprint``."""
        entry = self.sized.get(aircraft_name)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
        return None

    def clear(self) -> None:
        super().clear()
        self.aircraft.clear()
        self.sized.clear()
        self.sub_opt_cache.clear()


sessions = SessionManager(session_factory=AvySession)
