"""MCP resources for the omd server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent.parent


async def reference_guide() -> str:
    """Return the omd parameter reference document."""
    ref_path = _PKG_DIR / "reference.md"
    return await asyncio.to_thread(ref_path.read_text, "utf-8")


async def plan_schema_resource() -> str:
    """Return the plan JSON Schema (the authoritative plan YAML contract)."""
    from hangar.omd.plan_schema import PLAN_SCHEMA

    return json.dumps(PLAN_SCHEMA, indent=2, default=str)


async def plan_by_id(plan_id: str) -> str:
    """Return the latest assembled YAML for a plan from the plan store."""
    from hangar.omd.db import plan_store_dir

    store = plan_store_dir() / plan_id
    versions = sorted(
        store.glob("v*.yaml"),
        key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0,
    )
    if not versions:
        raise ValueError(f"No plan versions found for {plan_id!r}")
    return await asyncio.to_thread(versions[-1].read_text, "utf-8")
