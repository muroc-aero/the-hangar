"""Shared helper utilities for tool implementations.

Migrated from: OpenAeroStruct/oas_mcp/tools/_helpers.py (generic parts)
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import warnings
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Sentinel values for run_id resolution
# ---------------------------------------------------------------------------

_LATEST_SENTINELS = {"latest", "last"}


async def _resolve_run_id(
    run_id: str, session_id: str | None = None
) -> str:
    """Resolve ``"latest"``/``"last"`` to the most recent run_id for the current user."""
    from hangar.sdk.state import artifacts as _artifacts
    from hangar.sdk.auth import get_current_user

    if run_id.lower() in _LATEST_SENTINELS:
        user = get_current_user()
        resolved = await asyncio.to_thread(
            _artifacts.get_latest, user, None, session_id
        )
        if resolved is None:
            raise ValueError(
                "No runs found for the current user. Run an analysis first."
            )
        return resolved
    return run_id


def _get_viewer_base_url() -> str | None:
    """Compute the base URL for the viewer/dashboard HTTP endpoints.

    Uses RESOURCE_SERVER_URL (set on VPS deployments, e.g. https://mcp.lakesideai.dev)
    if available.  Falls back to the local daemon thread viewer port for stdio transport.
    Returns None if no viewer is reachable.
    """
    resource_url = os.environ.get("RESOURCE_SERVER_URL")
    if resource_url:
        return resource_url.rstrip("/")
    from hangar.sdk.env import _hangar_env

    prov_port = _hangar_env("HANGAR_PROV_PORT", "OAS_PROV_PORT", default="7654")
    if _hangar_env("HANGAR_PROV_VIEWER", "OAS_PROV_VIEWER").lower() != "off":
        return f"http://localhost:{prov_port}"
    return None


def _sanitize_surface_dicts(surface_dicts: list[dict]) -> list[dict]:
    """Strip complex dtypes from surface dicts so they survive JSON round-trip.

    OpenMDAO's complex-step setup can leave complex-valued arrays or scalars
    in the surface dicts (e.g. wingbox thickness parameters).  We only need
    real parts for rebuilding the problem structure.
    """
    sanitized = []
    for sd in surface_dicts:
        clean: dict[str, Any] = {}
        for k, v in sd.items():
            if isinstance(v, np.ndarray) and np.issubdtype(v.dtype, np.complexfloating):
                clean[k] = v.real.copy()
            elif isinstance(v, complex):
                clean[k] = v.real
            else:
                clean[k] = v
        sanitized.append(clean)
    return sanitized


def _suppress_output(func, *args, **kwargs):
    """Run func(*args, **kwargs) while suppressing stdout/stderr and warnings."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return func(*args, **kwargs)
