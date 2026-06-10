"""Session state management — surfaces, caching, pinning.

Migrated from: OpenAeroStruct/oas_mcp/core/session.py
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np


def _surface_fingerprint(surface: dict) -> str:
    """
    Produce a stable string fingerprint of a surface dict for cache invalidation.
    Numpy arrays are converted to lists before hashing.
    """

    def _convert(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(v) for v in obj]
        return obj

    serialisable = _convert(surface)
    raw = json.dumps(serialisable, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class _CachedProblem:
    prob: Any
    analysis_type: str  # "aero" or "aerostruct"
    surface_fingerprints: dict[str, str]  # name → fingerprint at build time
    pinned_by: set[str] = field(default_factory=set)  # set of run_ids that pinned this


@dataclass
class SessionDefaults:
    """Per-session preferences that persist across tool calls."""

    # "summary" (default) | "standard"
    default_detail_level: str = "summary"
    # Minimum severity to include in validation block: "error" | "warning" | "info"
    validation_severity_threshold: str = "info"
    # Plot types to auto-generate with each analysis (empty = no auto-plots)
    auto_visualize: list[str] = field(default_factory=list)
    # "off" | "logging" | "otel" — overrides OAS_TELEMETRY_MODE env var for this session
    telemetry_mode: str | None = None
    # "inline" (default) | "file" | "url" — controls what visualize() returns
    visualization_output: str = "inline"
    # Max artifacts to keep per session (oldest pruned after each save). None = unlimited.
    retention_max_count: int | None = None

    def to_dict(self) -> dict:
        return {
            "default_detail_level": self.default_detail_level,
            "validation_severity_threshold": self.validation_severity_threshold,
            "auto_visualize": self.auto_visualize,
            "telemetry_mode": self.telemetry_mode,
            "visualization_output": self.visualization_output,
            "retention_max_count": self.retention_max_count,
        }


@dataclass
class Session:
    """Stores surfaces, cached problems, defaults, and requirements."""

    # name → surface dict (includes mesh as numpy array)
    surfaces: dict[str, dict] = field(default_factory=dict)

    # Project name for organising artifacts (configurable per session)
    project: str = "default"

    # Cached problems: key = analysis_type + ":" + sorted surface names
    _cache: dict[str, _CachedProblem] = field(default_factory=dict, repr=False)

    # Pinned run_ids → cache_keys: prevent cache eviction
    _pinned: dict[str, str] = field(default_factory=dict, repr=False)

    # Per-session defaults
    defaults: SessionDefaults = field(default_factory=SessionDefaults)

    # User-defined requirements (dot-path assertions checked after each analysis)
    requirements: list[dict] = field(default_factory=list)

    # run_id → convergence data (stored at run time)
    _convergence: dict[str, dict] = field(default_factory=dict, repr=False)

    # run_id → mesh snapshot (for planform plots)
    _mesh_snapshots: dict[str, dict] = field(default_factory=dict, repr=False)

    # analysis_type:surface_names → results dict (for delta summaries)
    _last_results: dict[str, dict] = field(default_factory=dict, repr=False)

    def add_surface(self, surface: dict) -> None:
        name = surface["name"]
        self.surfaces[name] = surface
        # Invalidate any unpinned cached problems that include this surface
        stale = [
            k for k, v in self._cache.items()
            if name in v.surface_fingerprints and not v.pinned_by
        ]
        for k in stale:
            del self._cache[k]

    def get_surfaces(self, names: list[str]) -> list[dict]:
        return [self.surfaces[n] for n in names]

    def _cache_key(self, names: list[str], analysis_type: str) -> str:
        return analysis_type + ":" + ",".join(sorted(names))

    def get_cached_problem(
        self, names: list[str], analysis_type: str
    ) -> Any | None:
        key = self._cache_key(names, analysis_type)
        cached = self._cache.get(key)
        if cached is None:
            return None
        # Validate fingerprints
        for name in names:
            if name not in self.surfaces:
                del self._cache[key]
                return None
            current = _surface_fingerprint(self.surfaces[name])
            if cached.surface_fingerprints.get(name) != current:
                if not cached.pinned_by:
                    del self._cache[key]
                return None
        return cached.prob

    def store_problem(
        self, names: list[str], analysis_type: str, prob: Any
    ) -> None:
        key = self._cache_key(names, analysis_type)
        fingerprints = {n: _surface_fingerprint(self.surfaces[n]) for n in names}
        self._cache[key] = _CachedProblem(
            prob=prob,
            analysis_type=analysis_type,
            surface_fingerprints=fingerprints,
        )

    def cache_status(self, names: list[str], analysis_type: str) -> dict:
        """Return cache status for a set of surfaces and analysis type."""
        key = self._cache_key(names, analysis_type)
        cached = self._cache.get(key)
        if cached is None:
            return {"cached": False, "pinned": False, "pin_count": 0}
        return {
            "cached": True,
            "pinned": bool(cached.pinned_by),
            "pin_count": len(cached.pinned_by),
        }

    # ------------------------------------------------------------------
    # Cache pinning
    # ------------------------------------------------------------------

    def pin_run(self, run_id: str, names: list[str], analysis_type: str) -> bool:
        """Pin the cached problem for *run_id* to prevent eviction.

        Returns True if there was a cached problem to pin, False otherwise.
        """
        key = self._cache_key(names, analysis_type)
        cached = self._cache.get(key)
        if cached is None:
            return False
        cached.pinned_by.add(run_id)
        self._pinned[run_id] = key
        return True

    def unpin_run(self, run_id: str) -> bool:
        """Remove the pin for *run_id*.

        Returns True if the pin existed.
        """
        key = self._pinned.pop(run_id, None)
        if key is None:
            return False
        cached = self._cache.get(key)
        if cached is not None:
            cached.pinned_by.discard(run_id)
        return True

    def is_pinned(self, run_id: str) -> bool:
        return run_id in self._pinned

    # ------------------------------------------------------------------
    # Convergence & mesh snapshots
    # ------------------------------------------------------------------

    def _bounded_store(self, store: dict, key: str, value: Any, maxlen: int = 100) -> None:
        """Insert *key*→*value* into *store*, evicting the oldest entry if over *maxlen*."""
        store[key] = value
        if len(store) > maxlen:
            del store[next(iter(store))]

    def store_convergence(self, run_id: str, data: dict) -> None:
        self._bounded_store(self._convergence, run_id, data)

    def get_convergence(self, run_id: str) -> dict | None:
        return self._convergence.get(run_id)

    def store_mesh_snapshot(self, run_id: str, data: dict) -> None:
        self._bounded_store(self._mesh_snapshots, run_id, data)

    def get_mesh_snapshot(self, run_id: str) -> dict | None:
        return self._mesh_snapshots.get(run_id)

    def store_last_results(self, names: list[str], analysis_type: str, results: dict) -> None:
        self._bounded_store(self._last_results, self._cache_key(names, analysis_type), results)

    def get_last_results(self, names: list[str], analysis_type: str) -> dict | None:
        return self._last_results.get(self._cache_key(names, analysis_type))

    # ------------------------------------------------------------------
    # Configure defaults
    # ------------------------------------------------------------------

    def configure(self, **kwargs) -> None:
        """Update session defaults from keyword arguments."""
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

    # ------------------------------------------------------------------
    # Requirements
    # ------------------------------------------------------------------

    def set_requirements(self, requirements: list[dict]) -> None:
        self.requirements = list(requirements)

    def clear_requirements(self) -> None:
        self.requirements = []

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self) -> None:
        self.surfaces.clear()
        self._cache.clear()
        self._pinned.clear()
        self._convergence.clear()
        self._mesh_snapshots.clear()
        self._last_results.clear()
        self.defaults = SessionDefaults()
        self.requirements = []
        self.project = "default"


class SessionManager:
    """Global registry of named sessions, keyed per authenticated user.

    The same short session name (every tool defaults to ``"default"``)
    resolves to a different :class:`Session` per user, so surfaces, engines,
    requirements, pins, and cached problems never cross users on a shared
    HTTP server. On stdio there is one user per process and this degrades to
    a plain name-keyed registry. Sessions are created on first access.
    """

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], Session] = {}

    @staticmethod
    def _key(session_id: str) -> tuple[str, str]:
        from hangar.sdk.auth import get_current_user

        return (get_current_user(), session_id)

    def get(self, session_id: str = "default") -> Session:
        key = self._key(session_id)
        if key not in self._sessions:
            self._sessions[key] = Session()
        return self._sessions[key]

    def reset(self) -> None:
        """Clear the calling user's sessions and cached problems."""
        from hangar.sdk.auth import get_current_user

        user = get_current_user()
        self._sessions = {
            key: session for key, session in self._sessions.items() if key[0] != user
        }
