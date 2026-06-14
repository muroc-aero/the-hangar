"""MCP resources for evtol."""

from __future__ import annotations

import asyncio
from pathlib import Path

from hangar.sdk.auth import get_current_user
from hangar.evtol.state import artifacts as _artifacts


_PKG_DIR = Path(__file__).resolve().parent.parent


async def reference_guide() -> str:
    """Return the evtol parameter reference document."""
    return (_PKG_DIR / "reference.md").read_text(encoding="utf-8")


async def workflow_guide() -> str:
    """Return the evtol step-by-step workflow guide."""
    return (_PKG_DIR / "workflows.md").read_text(encoding="utf-8")


async def artifact_by_run_id(run_id: str) -> str:
    """Return a saved artifact as JSON text."""
    import json

    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, None, user)
    if artifact is None:
        return json.dumps({"error": f"Artifact '{run_id}' not found"})
    return json.dumps(artifact, default=str, indent=2)
