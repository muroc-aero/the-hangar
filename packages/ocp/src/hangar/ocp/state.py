"""OCP session state management and module-level singletons.

Parallels ``hangar.sdk.state`` but with OpenConcept-specific session data:
aircraft configs, propulsion architecture, mission profiles instead of
surface meshes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hangar.sdk.artifacts.store import ArtifactStore
from hangar.sdk.session.manager import SessionDefaults


def _config_fingerprint(session: OcpSession) -> str:
    """Hash of (aircraft_data, architecture, mission_type, num_nodes) for cache invalidation."""
    raw = json.dumps(
        {
            "aircraft_data": session.aircraft_data,
            "architecture": session.propulsion_architecture,
            "propulsion_overrides": session.propulsion_overrides,
            "mission_type": session.mission_type,
            "num_nodes": session.num_nodes,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class OcpSession:
    """Stores aircraft configuration, propulsion, mission, and cached problem state."""

    # Aircraft configuration
    aircraft_data: dict | None = None
    aircraft_template: str | None = None

    # Propulsion architecture
    propulsion_architecture: str | None = None
    propulsion_overrides: dict = field(default_factory=dict)

    # Mission profile
    mission_type: str = "full"
    mission_params: dict = field(default_factory=dict)
    num_nodes: int = 11

    # Solver settings
    solver_settings: dict = field(default_factory=lambda: {
        "maxiter": 20,
        "atol": 1e-10,
        "rtol": 1e-10,
        "solve_subsystems": True,
    })

    # SDK-compatible fields
    project: str = "default"
    defaults: SessionDefaults = field(default_factory=SessionDefaults)
    requirements: list[dict] = field(default_factory=list)

    # Cached OpenMDAO problem
    _cached_problem: Any = field(default=None, repr=False)
    _cached_metadata: dict = field(default_factory=dict, repr=False)
    _cache_fingerprint: str | None = field(default=None, repr=False)

    # Per-session result history
    _last_results: dict = field(default_factory=dict, repr=False)
    _convergence: dict = field(default_factory=dict, repr=False)
    _pinned: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Problem caching
    # ------------------------------------------------------------------

    def get_cached_problem(self) -> tuple[Any, dict] | None:
        """Return (prob, metadata) if the cache is valid, else None."""
        if self._cached_problem is None:
            return None
        current_fp = _config_fingerprint(self)
        if self._cache_fingerprint != current_fp:
            self._cached_problem = None
            self._cached_metadata = {}
            self._cache_fingerprint = None
            return None
        return self._cached_problem, self._cached_metadata

    def store_problem(self, prob: Any, metadata: dict) -> None:
        self._cached_problem = prob
        self._cached_metadata = metadata
        self._cache_fingerprint = _config_fingerprint(self)

    def invalidate_cache(self) -> None:
        self._cached_problem = None
        self._cached_metadata = {}
        self._cache_fingerprint = None

    # ------------------------------------------------------------------
    # Results and convergence (bounded stores)
    # ------------------------------------------------------------------

    def _bounded_store(self, store: dict, key: str, value: Any, maxlen: int = 100) -> None:
        store[key] = value
        if len(store) > maxlen:
            del store[next(iter(store))]

    def store_last_results(self, analysis_type: str, results: dict) -> None:
        self._bounded_store(self._last_results, analysis_type, results)

    def get_last_results(self, analysis_type: str) -> dict | None:
        return self._last_results.get(analysis_type)

    def store_convergence(self, run_id: str, data: dict) -> None:
        self._bounded_store(self._convergence, run_id, data)

    def get_convergence(self, run_id: str) -> dict | None:
        return self._convergence.get(run_id)

    # ------------------------------------------------------------------
    # Pin/unpin (for artifact protection)
    # ------------------------------------------------------------------

    def pin_run(self, run_id: str) -> bool:
        if self._cached_problem is None:
            return False
        self._pinned[run_id] = True
        return True

    def unpin_run(self, run_id: str) -> bool:
        return self._pinned.pop(run_id, None) is not None

    def is_pinned(self, run_id: str) -> bool:
        return run_id in self._pinned

    # ------------------------------------------------------------------
    # Configure and requirements
    # ------------------------------------------------------------------

    def configure(self, **kwargs) -> None:
        valid_fields = {
            "default_detail_level", "validation_severity_threshold",
            "auto_visualize", "telemetry_mode", "project",
            "visualization_output", "retention_max_count",
        }
        for key, value in kwargs.items():
            if key not in valid_fields:
                raise ValueError(
                    f"Unknown session default {key!r}. "
                    f"Valid keys: {sorted(valid_fields)}"
                )
            if key == "project":
                self.project = value
            else:
                setattr(self.defaults, key, value)

    def set_requirements(self, requirements: list[dict]) -> None:
        self.requirements = list(requirements)

    def clear_requirements(self) -> None:
        self.requirements = []

    # ------------------------------------------------------------------
    # Clear / reset
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self.aircraft_data = None
        self.aircraft_template = None
        self.propulsion_architecture = None
        self.propulsion_overrides = {}
        self.mission_type = "full"
        self.mission_params = {}
        self.num_nodes = 11
        self.solver_settings = {
            "maxiter": 20, "atol": 1e-10, "rtol": 1e-10,
            "solve_subsystems": True,
        }
        self.invalidate_cache()
        self._last_results.clear()
        self._convergence.clear()
        self._pinned.clear()
        self.defaults = SessionDefaults()
        self.requirements = []
        self.project = "default"


class OcpSessionManager:
    """Global registry of named OCP sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, OcpSession] = {"default": OcpSession()}

    def get(self, session_id: str = "default") -> OcpSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = OcpSession()
        return self._sessions[session_id]

    def reset(self) -> None:
        self._sessions = {"default": OcpSession()}


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

sessions = OcpSessionManager()
artifacts = ArtifactStore()
