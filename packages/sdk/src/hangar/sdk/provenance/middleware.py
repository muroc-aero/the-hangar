"""@capture_tool decorator for automatic provenance recording.

Migrated from: OpenAeroStruct/oas_mcp/provenance/capture.py
"""

from __future__ import annotations

import functools
import inspect
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from hangar.sdk.provenance.db import _next_seq, record_tool_call, _dumps

# ---------------------------------------------------------------------------
# Session ID state
# ---------------------------------------------------------------------------

# Module-level: persists across asyncio task boundaries (server use)
_server_session_id: str = "default"

# ContextVar: overrides module-level only when explicitly set (test isolation)
_prov_session_id: ContextVar[str] = ContextVar("_prov_session_id", default="")


def _get_session_id() -> str:
    """Return the active provenance session ID.

    Priority: ContextVar (tests) > module-level (server).
    """
    ctx = _prov_session_id.get()
    return ctx if ctx else _server_session_id


def set_server_session_id(session_id: str) -> None:
    """Set the module-level session ID (called by start_session tool)."""
    global _server_session_id
    _server_session_id = session_id


# ---------------------------------------------------------------------------
# Tool name state (identifies which tool server is running)
# ---------------------------------------------------------------------------

_tool_name: str = ""


def set_tool_name(name: str) -> None:
    """Set the tool name for provenance records (e.g. ``"oas"``, ``"ocp"``, ``"pyc"``)."""
    global _tool_name
    _tool_name = name


# ---------------------------------------------------------------------------
# JSON serialiser
# ---------------------------------------------------------------------------


def _safe_json(kwargs: dict) -> str:
    """Serialise kwargs to JSON with str() fallback for un-serialisable objects."""
    return _dumps(kwargs)


# ---------------------------------------------------------------------------
# Periodic graph flush
# ---------------------------------------------------------------------------

_flush_counter: dict[str, int] = {}
_FLUSH_EVERY = 5


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def capture_tool(fn):
    """Wrap *fn* so every call is recorded in the provenance DB."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        call_id = str(uuid.uuid4())
        session_id = _get_session_id()
        tool_name = fn.__name__
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()

        inputs_json = _safe_json(kwargs)
        outputs_json: str | None = None
        status = "ok"
        error_msg: str | None = None
        result = None

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            status = "error"
            error_msg = str(exc)
            raise
        else:
            # Inject _provenance into the returned dict so Claude can pass
            # call_id to log_decision as prior_call_id.
            if isinstance(result, dict):
                result["_provenance"] = {
                    "call_id": call_id,
                    "session_id": session_id,
                }
            try:
                outputs_json = _safe_json(
                    result if isinstance(result, dict) else {"result": str(result)}
                )
            except Exception:
                outputs_json = None
            return result
        finally:
            duration_s = time.perf_counter() - t0
            try:
                from hangar.sdk.provenance.db import _db_path, _ensure_session
                if _db_path is not None:
                    # Ensure session exists with user attribution before
                    # recording the tool call (INSERT OR IGNORE — no-op if
                    # start_session already created the row).
                    try:
                        from hangar.sdk.auth.oidc import get_current_user
                        _ensure_session(session_id, user=get_current_user(), tool=_tool_name)
                    except Exception:
                        _ensure_session(session_id, tool=_tool_name)
                    seq = _next_seq(session_id)
                    record_tool_call(
                        call_id,
                        session_id,
                        seq,
                        tool_name,
                        inputs_json,
                        outputs_json,
                        status,
                        error_msg,
                        started_at,
                        duration_s,
                        tool=_tool_name,
                    )

                    # Periodic graph flush
                    count = _flush_counter.get(session_id, 0) + 1
                    _flush_counter[session_id] = count
                    if count >= _FLUSH_EVERY:
                        _flush_counter[session_id] = 0
                        try:
                            from hangar.sdk.provenance.flush import flush_session_graph
                            flush_session_graph(session_id)
                        except Exception:
                            pass
            except Exception:
                pass  # Never swallow the original exception

    # Preserve the original function's signature for FastMCP introspection
    wrapper.__signature__ = inspect.signature(fn, eval_str=True)
    return wrapper
