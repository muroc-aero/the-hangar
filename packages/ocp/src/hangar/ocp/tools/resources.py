"""MCP resources for OpenConcept."""

from __future__ import annotations

import asyncio
from pathlib import Path

from hangar.sdk.auth import get_current_user
from hangar.ocp.state import artifacts as _artifacts


_PKG_DIR = Path(__file__).resolve().parent.parent


async def reference_guide() -> str:
    """Return the OCP parameter reference document."""
    ref_path = _PKG_DIR / "reference.md"
    return ref_path.read_text(encoding="utf-8")


async def workflow_guide() -> str:
    """Return the OCP step-by-step workflow guide."""
    wf_path = _PKG_DIR / "workflows.md"
    return wf_path.read_text(encoding="utf-8")


async def artifact_by_run_id(run_id: str) -> str:
    """Return a saved artifact as JSON text."""
    import json

    user = get_current_user()
    artifact = await asyncio.to_thread(_artifacts.get, run_id, None, user)
    if artifact is None:
        return json.dumps({"error": f"Artifact '{run_id}' not found"})
    return json.dumps(artifact, default=str, indent=2)
