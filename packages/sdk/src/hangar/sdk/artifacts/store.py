"""Filesystem-backed artifact store for analysis runs.

Migrated from: OpenAeroStruct/oas_mcp/core/artifacts.py
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import re

import numpy as np

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-. @]+$")

# Artifact schema version — stamped into every persisted artifact.
# Bump when the on-disk artifact format changes; add a migration step
# in _migrate_artifact() so older files are transparently upgraded on read.
ARTIFACT_SCHEMA_VERSION = "1.0"


def _migrate_artifact(artifact: dict) -> dict:
    """Apply schema migrations to an artifact loaded from disk.

    Artifacts written before versioning have no ``artifact_schema_version``
    key and are treated as version ``"1.0"`` (the current format).
    Future migrations would be chained here (1.0 → 1.1 → 1.2, etc.).
    """
    if "artifact_schema_version" not in artifact:
        artifact["artifact_schema_version"] = "1.0"
    return artifact


def _validate_path_segment(value: str, label: str) -> None:
    """Reject path-traversal characters in user-supplied path segments."""
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"{label} contains unsafe characters: {value!r}")
    if not _SAFE_NAME_RE.match(value):
        raise ValueError(f"{label} contains invalid characters: {value!r}")


def _default_data_dir() -> Path:
    from hangar.sdk.env import _hangar_env

    return Path(_hangar_env("HANGAR_DATA_DIR", "OAS_DATA_DIR", default="./hangar_data"))


class _NumpyEncoder(json.JSONEncoder):
    """Extend JSONEncoder to handle numpy scalars and arrays."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def _make_run_id() -> str:
    """Return a sortable, collision-resistant run ID: ``YYYYMMDDTHHMMSS_xxxx``."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = secrets.token_hex(8)  # 16 hex chars
    return f"{ts}_{suffix}"


class ArtifactStore:
    """Manages analysis artifacts on the local filesystem.

    Parameters
    ----------
    data_dir:
        Root directory for artifacts.  Falls back to ``HANGAR_DATA_DIR``
        (or legacy ``OAS_DATA_DIR``), or ``./hangar_data/`` if unset.

    Storage layout::

        {data_dir}/{user}/{project}/{session_id}/{run_id}.json
        {data_dir}/{user}/{project}/{session_id}/index.json
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session_dir(self, user: str, project: str, session_id: str) -> Path:
        _validate_path_segment(user, "user")
        _validate_path_segment(project, "project")
        _validate_path_segment(session_id, "session_id")
        resolved = (self._data_dir / user / project / session_id).resolve()
        if not str(resolved).startswith(str(self._data_dir.resolve())):
            raise ValueError("Path escapes data directory")
        return self._data_dir / user / project / session_id

    def _artifact_path(self, user: str, project: str, session_id: str, run_id: str) -> Path:
        _validate_path_segment(run_id, "run_id")
        return self._session_dir(user, project, session_id) / f"{run_id}.json"

    def _index_path(self, user: str, project: str, session_id: str) -> Path:
        return self._session_dir(user, project, session_id) / "index.json"

    def _load_index(self, user: str, project: str, session_id: str) -> list[dict]:
        """Load the index for *session_id*, rebuilding if missing or corrupt."""
        index_path = self._index_path(user, project, session_id)
        if not index_path.exists():
            return self._rebuild_index(user, project, session_id)
        try:
            with index_path.open() as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return self._rebuild_index(user, project, session_id)

    def _save_index(
        self, user: str, project: str, session_id: str, index: list[dict]
    ) -> None:
        index_path = self._index_path(user, project, session_id)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = index_path.with_suffix(".tmp")
        try:
            with tmp.open("w") as f:
                json.dump(index, f, indent=2, cls=_NumpyEncoder)
            tmp.replace(index_path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise

    def _rebuild_index(self, user: str, project: str, session_id: str) -> list[dict]:
        """Reconstruct the index by scanning artifact files on disk."""
        session_dir = self._session_dir(user, project, session_id)
        index: list[dict] = []
        seen_run_ids: set[str] = set()
        if session_dir.exists():
            for path in sorted(session_dir.glob("*.json")):
                if path.name == "index.json":
                    continue
                try:
                    with path.open() as f:
                        artifact = json.load(f)
                    meta = artifact.get("metadata", {})
                    rid = meta.get("run_id", path.stem)
                    if rid in seen_run_ids:
                        continue
                    seen_run_ids.add(rid)
                    entry: dict[str, Any] = {
                        "run_id": rid,
                        "session_id": meta.get("session_id", session_id),
                        "user": meta.get("user", user),
                        "project": meta.get("project", project),
                        "analysis_type": meta.get("analysis_type", "unknown"),
                        "timestamp": meta.get("timestamp", ""),
                        "surfaces": meta.get("surfaces", []),
                        "tool_name": meta.get("tool_name", ""),
                    }
                    if meta.get("name") is not None:
                        entry["name"] = meta["name"]
                    index.append(entry)
                except (json.JSONDecodeError, OSError):
                    continue
        self._save_index(user, project, session_id, index)
        return index

    def _iter_session_triples(
        self,
        user_filter: str | None = None,
        project_filter: str | None = None,
        session_filter: str | None = None,
    ):
        """Yield (user, project, session_id) tuples matching the given filters."""
        if not self._data_dir.exists():
            return
        for user_dir in sorted(self._data_dir.iterdir()):
            if not user_dir.is_dir():
                continue
            if user_filter is not None and user_dir.name != user_filter:
                continue
            for project_dir in sorted(user_dir.iterdir()):
                if not project_dir.is_dir():
                    continue
                if project_filter is not None and project_dir.name != project_filter:
                    continue
                for session_dir in sorted(project_dir.iterdir()):
                    if not session_dir.is_dir():
                        continue
                    if session_filter is not None and session_dir.name != session_filter:
                        continue
                    yield user_dir.name, project_dir.name, session_dir.name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        session_id: str,
        analysis_type: str,
        tool_name: str,
        surfaces: list[str],
        parameters: dict,
        results: Any,
        user: str = "default",
        project: str = "default",
        name: str | None = None,
        validation: dict | None = None,
        telemetry: dict | None = None,
        run_id: str | None = None,
    ) -> str:
        """Persist an analysis artifact and return its ``run_id``.

        Parameters
        ----------
        session_id:
            The session that produced this result.
        analysis_type:
            One of ``"aero"``, ``"aerostruct"``, ``"drag_polar"``,
            ``"stability"``, ``"optimization"``.
        tool_name:
            The MCP tool that was called (e.g. ``"run_aero_analysis"``).
        surfaces:
            List of surface names involved.
        parameters:
            Flight conditions and/or configuration dict.
        results:
            The tool return value (may contain numpy arrays).
        user:
            User identity (from JWT or env/OS).
        project:
            Project name for organising runs.
        name:
            Optional human-readable label for this run.
        validation:
            Validation findings dict to persist alongside results.
        telemetry:
            Telemetry dict to persist alongside results.
        run_id:
            Pre-generated run ID.  A new one is generated if not supplied.

        Returns
        -------
        str
            The ``run_id`` (either the one provided or a newly generated one).
        """
        if run_id is None:
            run_id = _make_run_id()
        timestamp = datetime.now(timezone.utc).isoformat()

        metadata: dict[str, Any] = {
            "run_id": run_id,
            "session_id": session_id,
            "user": user,
            "project": project,
            "analysis_type": analysis_type,
            "timestamp": timestamp,
            "surfaces": surfaces,
            "tool_name": tool_name,
            "parameters": parameters,
        }
        if name is not None:
            metadata["name"] = name

        artifact: dict[str, Any] = {
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "metadata": metadata,
            "results": results,
        }
        if validation is not None:
            artifact["validation"] = validation
        if telemetry is not None:
            artifact["telemetry"] = telemetry

        with self._lock:
            artifact_path = self._artifact_path(user, project, session_id, run_id)
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            with artifact_path.open("w") as f:
                json.dump(artifact, f, indent=2, cls=_NumpyEncoder)

            index = self._load_index(user, project, session_id)
            # Deduplicate: remove any existing entry with the same run_id
            index = [e for e in index if e.get("run_id") != run_id]
            entry: dict[str, Any] = {
                "run_id": run_id,
                "session_id": session_id,
                "user": user,
                "project": project,
                "analysis_type": analysis_type,
                "timestamp": timestamp,
                "surfaces": surfaces,
                "tool_name": tool_name,
            }
            if name is not None:
                entry["name"] = name
            index.append(entry)
            self._save_index(user, project, session_id, index)

        return run_id

    def list(
        self,
        session_id: str | None = None,
        analysis_type: str | None = None,
        user: str | None = None,
        project: str | None = None,
    ) -> list[dict]:
        """Return index entries, optionally filtered.

        Parameters
        ----------
        session_id:
            If given, restrict results to that session.
        analysis_type:
            If given, restrict results to that analysis type.
        user:
            If given, restrict to that user's artifacts.
        project:
            If given, restrict to that project's artifacts.
        """
        with self._lock:
            entries: list[dict] = []
            for u, p, s in self._iter_session_triples(user, project, session_id):
                entries.extend(self._load_index(u, p, s))

            if analysis_type is not None:
                entries = [e for e in entries if e.get("analysis_type") == analysis_type]

            return entries

    def get_latest(
        self,
        user: str | None = None,
        project: str | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """Return the run_id of the most recent artifact, or ``None``.

        Scans all matching (user, project, session) directories and returns
        the run_id with the lexicographically greatest timestamp prefix.
        """
        with self._lock:
            latest_rid: str | None = None
            for u, p, s in self._iter_session_triples(user, project, session_id):
                index = self._load_index(u, p, s)
                for entry in index:
                    rid = entry.get("run_id", "")
                    if latest_rid is None or rid > latest_rid:
                        latest_rid = rid
            return latest_rid

    def get(
        self,
        run_id: str,
        session_id: str | None = None,
        user: str | None = None,
        project: str | None = None,
    ) -> dict | None:
        """Return the full artifact (metadata + results), or ``None`` if not found.

        Parameters
        ----------
        run_id:
            The run ID to look up.
        session_id:
            Optional hint.  Narrows the search to directories matching this
            session name.
        user:
            Optional hint.  Restricts search to this user's directory.
        project:
            Optional hint.  Restricts search to this project's directory.
        """
        with self._lock:
            for u, p, s in self._iter_session_triples(user, project, session_id):
                path = self._session_dir(u, p, s) / f"{run_id}.json"
                if path.exists():
                    try:
                        with path.open() as f:
                            return _migrate_artifact(json.load(f))
                    except (json.JSONDecodeError, OSError):
                        return None
        return None

    def get_summary(
        self,
        run_id: str,
        session_id: str | None = None,
        user: str | None = None,
        project: str | None = None,
    ) -> dict | None:
        """Return artifact metadata only (no results payload), or ``None``."""
        artifact = self.get(run_id, session_id, user, project)
        if artifact is None:
            return None
        return artifact.get("metadata")

    def delete(
        self,
        run_id: str,
        session_id: str | None = None,
        user: str | None = None,
        project: str | None = None,
    ) -> bool:
        """Delete an artifact from disk and its index entry.

        Returns ``True`` if the artifact was found and removed, ``False``
        if it did not exist.
        """
        with self._lock:
            for u, p, s in self._iter_session_triples(user, project, session_id):
                path = self._session_dir(u, p, s) / f"{run_id}.json"
                if path.exists():
                    path.unlink()
                    index = self._load_index(u, p, s)
                    index = [e for e in index if e.get("run_id") != run_id]
                    self._save_index(u, p, s, index)
                    return True
        return False

    def cleanup(
        self,
        user: str,
        project: str,
        session_id: str,
        max_count: int | None = None,
        max_age_days: int | None = None,
        protected_run_ids: set[str] | None = None,
    ) -> list[str]:
        """Delete oldest artifacts exceeding retention limits.

        Parameters
        ----------
        user, project, session_id:
            Identify the session directory to clean up.
        max_count:
            Keep at most this many artifacts (newest first). Oldest are
            deleted when the count is exceeded.
        max_age_days:
            Delete artifacts whose timestamp is older than this many days.
        protected_run_ids:
            Run IDs that must never be deleted (e.g. pinned runs).

        Returns
        -------
        list[str]
            Run IDs of deleted artifacts.
        """
        if max_count is None and max_age_days is None:
            return []

        protected = protected_run_ids or set()

        with self._lock:
            index = self._load_index(user, project, session_id)
            if not index:
                return []

            # Sort oldest-first by run_id (chronologically sortable prefix)
            index.sort(key=lambda e: e.get("run_id", ""))

            to_delete: list[str] = []

            # --- age-based deletion ---
            if max_age_days is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
                cutoff_iso = cutoff.isoformat()
                for entry in index:
                    rid = entry["run_id"]
                    ts = entry.get("timestamp", "")
                    if ts and ts < cutoff_iso and rid not in protected:
                        to_delete.append(rid)

            # --- count-based deletion ---
            if max_count is not None and max_count >= 0:
                # After removing age-expired, compute how many remain
                remaining = [e for e in index if e["run_id"] not in set(to_delete)]
                excess = len(remaining) - max_count
                if excess > 0:
                    # Delete the oldest excess entries, skipping protected
                    for entry in remaining:
                        if excess <= 0:
                            break
                        rid = entry["run_id"]
                        if rid not in protected and rid not in set(to_delete):
                            to_delete.append(rid)
                            excess -= 1

            # Perform deletions
            delete_set = set(to_delete)
            for rid in to_delete:
                path = self._artifact_path(user, project, session_id, rid)
                if path.exists():
                    path.unlink()

            if to_delete:
                index = [e for e in index if e["run_id"] not in delete_set]
                self._save_index(user, project, session_id, index)

            return to_delete
