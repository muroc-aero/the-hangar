"""Structured logging with per-run log capture.

Migrated from: OpenAeroStruct/oas_mcp/core/telemetry.py
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_first(*names: str, default: str = "") -> str:
    """Return the first non-empty env var value, or *default*."""
    for name in names:
        val = os.environ.get(name)
        if val:
            return val
    return default


_LOG_LEVEL = getattr(
    logging,
    _env_first("HANGAR_LOG_LEVEL", "OAS_LOG_LEVEL", default="INFO").upper(),
    logging.INFO,
)
_MAX_RUNS = int(_env_first("HANGAR_LOG_MAX_RUNS", "OAS_LOG_MAX_RUNS", default="100"))

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logger = logging.getLogger("hangar")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(_LOG_LEVEL)
    logger.propagate = False


# ---------------------------------------------------------------------------
# Per-run log capture
# ---------------------------------------------------------------------------


@dataclass
class _RunLogBuffer:
    run_id: str
    session_id: str
    tool_name: str
    records: list[dict] = field(default_factory=list)


class _RunLogHandler(logging.Handler):
    """In-memory handler that routes records to the active run buffer."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._active: _RunLogBuffer | None = None
        self._store: deque[_RunLogBuffer] = deque(maxlen=_MAX_RUNS)
        self._by_run_id: dict[str, _RunLogBuffer] = {}

    def set_active(self, buf: _RunLogBuffer) -> None:
        with self._lock:
            self._active = buf

    def clear_active(self, buf: _RunLogBuffer) -> None:
        with self._lock:
            if self._active is buf:
                self._active = None
            # Evict oldest entry from _by_run_id before deque overwrites it
            if len(self._store) == self._store.maxlen:
                evicted = self._store[0]
                self._by_run_id.pop(evicted.run_id, None)
            self._store.append(buf)
            self._by_run_id[buf.run_id] = buf

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            if self._active is not None:
                from datetime import datetime, timezone
                ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )
                self._active.records.append({
                    "time": ts,
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "logger": record.name,
                })

    def get_logs(self, run_id: str) -> list[dict] | None:
        with self._lock:
            buf = self._by_run_id.get(run_id)
            if buf is None and self._active and self._active.run_id == run_id:
                buf = self._active
            return list(buf.records) if buf is not None else None


_run_log_handler = _RunLogHandler()
logger.addHandler(_run_log_handler)


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------


def _redact_array(arr: Any) -> dict:
    """Replace a numpy array with a shape/stats summary (never raw values)."""
    a = np.asarray(arr)
    h = hashlib.sha256(a.tobytes()).hexdigest()[:8]
    summary: dict[str, Any] = {"shape": list(a.shape), "hash": h}
    if a.size > 0:
        summary["min"] = float(a.min())
        summary["max"] = float(a.max())
        summary["mean"] = float(a.mean())
    return summary


def redact(obj: Any, max_depth: int = 4) -> Any:
    """Recursively redact numpy arrays from a nested object.

    Arrays -> shape/hash/stats summary.  Other values pass through.
    """
    if max_depth <= 0:
        return "..."
    if isinstance(obj, np.ndarray):
        return _redact_array(obj)
    if isinstance(obj, dict):
        return {k: redact(v, max_depth - 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        if len(obj) > 20:
            return {
                "type": "list",
                "length": len(obj),
                "first": redact(obj[0], max_depth - 1),
                "last": redact(obj[-1], max_depth - 1),
            }
        return [redact(v, max_depth - 1) for v in obj]
    return obj


def get_run_logs(run_id: str) -> list[dict] | None:
    """Return captured log records for *run_id*, or None if not found."""
    return _run_log_handler.get_logs(run_id)


def set_active_run(run_id: str, session_id: str, tool_name: str) -> _RunLogBuffer:
    """Create a run log buffer and set it as the active capture target.

    Returns the buffer so the caller can pass it to ``clear_active_run``
    when the tool call finishes.
    """
    buf = _RunLogBuffer(run_id=run_id, session_id=session_id, tool_name=tool_name)
    _run_log_handler.set_active(buf)
    return buf


def clear_active_run(buf: _RunLogBuffer) -> None:
    """Finalize the run buffer and move it into the completed store."""
    _run_log_handler.clear_active(buf)


# ---------------------------------------------------------------------------
# Telemetry summary builder
# ---------------------------------------------------------------------------


def make_telemetry(
    elapsed_s: float,
    cache_hit: bool,
    surface_count: int = 0,
    mesh_shape: tuple[int, int, int] | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a telemetry block for the response envelope.

    Parameters
    ----------
    elapsed_s:
        Wall-clock seconds for the analysis.
    cache_hit:
        Whether the OpenMDAO problem was retrieved from cache.
    surface_count:
        Number of surfaces analysed.
    mesh_shape:
        (nx, ny, 3) shape of the first surface mesh, if available.
    extra:
        Additional key/value pairs to include.
    """
    telem: dict[str, Any] = {
        "elapsed_s": round(elapsed_s, 4),
        "oas.cache.hit": cache_hit,
        "oas.surface.count": surface_count,
    }
    if mesh_shape is not None:
        telem["oas.mesh.nx"] = mesh_shape[0]
        telem["oas.mesh.ny"] = mesh_shape[1]
    if extra:
        telem.update(extra)
    return telem


class RunLogStore:
    """Convenience wrapper providing context-manager semantics for run logging.

    Usage::

        store = RunLogStore()
        with store.capture(run_id, session_id, tool_name):
            # ... run analysis; all logger output is captured ...
        logs = store.get_logs(run_id)
    """

    class _CaptureContext:
        def __init__(self, run_id: str, session_id: str, tool_name: str) -> None:
            self._run_id = run_id
            self._session_id = session_id
            self._tool_name = tool_name
            self._buf: _RunLogBuffer | None = None

        def __enter__(self) -> _RunLogBuffer:
            self._buf = set_active_run(self._run_id, self._session_id, self._tool_name)
            return self._buf

        def __exit__(self, *exc: object) -> None:
            if self._buf is not None:
                clear_active_run(self._buf)

    def capture(self, run_id: str, session_id: str, tool_name: str) -> _CaptureContext:
        """Return a context manager that captures logs for the given run."""
        return self._CaptureContext(run_id, session_id, tool_name)

    @staticmethod
    def get_logs(run_id: str) -> list[dict] | None:
        """Return captured log records for *run_id*."""
        return get_run_logs(run_id)
