"""Shared helpers for omd MCP tools: path resolution and view URLs."""

from __future__ import annotations

import os
from pathlib import Path

from hangar.sdk.errors import UserInputError


def workspace_dir() -> Path:
    """Server-side plan workspace for MCP-only agents (no filesystem access).

    Relative plan paths in tool arguments resolve here, so a claude.ai agent
    can author, validate, and run plans entirely through tool calls.
    """
    from hangar.omd.db import omd_data_root

    ws = omd_data_root() / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def resolve_plan_path(plan_path: str, *, must_exist: bool = True) -> Path:
    """Resolve a plan file/dir path: absolute, cwd-relative, or workspace-relative."""
    if not plan_path:
        raise UserInputError("plan_path must be a non-empty string")
    p = Path(plan_path).expanduser()
    if p.is_absolute():
        candidates = [p]
    else:
        candidates = [Path.cwd() / p, workspace_dir() / p]
    for c in candidates:
        if c.exists():
            return c
    if not must_exist:
        return candidates[-1]
    tried = ", ".join(str(c) for c in candidates)
    raise UserInputError(f"Plan path not found: {plan_path!r} (tried: {tried})")


def resolve_plan_dir(plan_dir: str, *, create: bool = False) -> Path:
    """Resolve a modular plan directory; relative names live in the workspace."""
    if not plan_dir:
        raise UserInputError("plan_dir must be a non-empty string")
    p = Path(plan_dir).expanduser()
    if not p.is_absolute():
        cwd_candidate = Path.cwd() / p
        if cwd_candidate.exists():
            return cwd_candidate
        p = workspace_dir() / p
    if not p.exists() and not create:
        raise UserInputError(f"Plan directory not found: {plan_dir!r} (resolved to {p})")
    return p


def workspace_write_target(rel_path: str) -> Path:
    """Resolve a write target; relative paths are confined to the workspace."""
    if not rel_path:
        raise UserInputError("path must be a non-empty string")
    p = Path(rel_path).expanduser()
    if p.is_absolute():
        return p
    ws = workspace_dir().resolve()
    target = (ws / p).resolve()
    if not target.is_relative_to(ws):
        raise UserInputError(f"Relative path escapes the plan workspace: {rel_path!r}")
    return target


def rs_dashboard_base() -> str | None:
    """Base URL of the range-safety dashboard, if one is reachable.

    ``RS_DASHBOARD_URL`` is either set by the deployment (dashboard runs as
    its own service) or by the omd server's autostart (see ``server.py``).
    """
    url = os.environ.get("RS_DASHBOARD_URL")
    return url.rstrip("/") if url else None


def view_urls(run_id: str | None = None, plan_id: str | None = None) -> dict:
    """Clickable URLs for every view that applies to *run_id* / *plan_id*.

    Empty dict when no viewer is reachable (viewer disabled and no
    RESOURCE_SERVER_URL / RS_DASHBOARD_URL configured).
    """
    from hangar.sdk.helpers import _get_viewer_base_url

    urls: dict[str, str] = {}
    base = None
    try:
        base = _get_viewer_base_url()
    except Exception:
        pass
    if base:
        urls["viewer"] = f"{base}/viewer"
        if plan_id:
            urls["plan_provenance"] = f"{base}/omd-provenance?plan_id={plan_id}"
            urls["plan_detail"] = f"{base}/omd-plan-detail?plan_id={plan_id}"
        if run_id:
            urls["problem_dag"] = f"{base}/omd-problem-dag?run_id={run_id}"
            urls["plots"] = f"{base}/omd-plots?run_id={run_id}"
            urls["n2"] = f"{base}/omd-n2?run_id={run_id}"

    rs = rs_dashboard_base()
    if rs:
        params = []
        if plan_id:
            params.append(f"plan_id={plan_id}")
        if run_id:
            params.append(f"run_id={run_id}")
        query = ("?" + "&".join(params)) if params else ""
        urls["range_safety_dashboard"] = f"{rs}/{query}"
    return urls


def load_plan_for_run(run_id: str, plan_path: str | None = None) -> tuple[dict, str]:
    """Resolve (plan dict, plan_id) for a run from an explicit path or the store.

    MCP-friendly twin of the CLI helper in ``hangar.omd.cli`` (raises
    ``UserInputError`` instead of ``SystemExit``).
    """
    import yaml

    from hangar.omd.db import plan_store_dir, query_entity

    if plan_path:
        path = resolve_plan_path(plan_path)
        plan = yaml.safe_load(path.read_text()) or {}
        plan_id = (plan.get("metadata") or {}).get("id") or run_id
        return plan, plan_id

    run = query_entity(run_id)
    if not run or not run.get("plan_id"):
        raise UserInputError(
            f"No plan_id recorded for run {run_id!r}; pass plan_path explicitly."
        )
    plan_id = run["plan_id"]
    store = plan_store_dir() / plan_id
    versions = sorted(
        store.glob("v*.yaml"),
        key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0,
    )
    if not versions:
        raise UserInputError(f"No plan versions found for {plan_id!r} in {store}.")
    plan = yaml.safe_load(versions[-1].read_text()) or {}
    return plan, plan_id
