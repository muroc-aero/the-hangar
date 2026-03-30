"""Workspace state persistence for CLI one-shot mode.

Stores tool call arguments in a JSON file so that one-shot invocations can
rebuild session state before running an analysis tool.

State is keyed by workspace name (default: "default").
File location: ~/.hangar/state/<workspace>.json

The state file stores an ordered list of "setup steps" — tool calls that
must be replayed to reconstruct the session. Each tool server declares
which of its tools produce state and how to replay them.

Schema::

    {
      "setup_steps": [
        {"tool": "load_aircraft_template", "args": {"template": "caravan"}},
        {"tool": "set_propulsion_architecture", "args": {"architecture": "turboprop"}},
        {"tool": "configure_mission", "args": {"mission_type": "basic", ...}}
      ],
      "surfaces": {
        "wing": {"name": "wing", "num_y": 7, ...}
      }
    }

The ``surfaces`` key is retained for backward compatibility with existing
OAS state files. New tool servers should use ``setup_steps`` exclusively.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hangar.sdk.cli.runner import _NumpyEncoder

STATE_DIR = Path.home() / ".hangar" / "state"


def _state_path(workspace: str) -> Path:
    return STATE_DIR / f"{workspace}.json"


# ---------------------------------------------------------------------------
# Generic setup-step persistence (new, tool-agnostic)
# ---------------------------------------------------------------------------

def save_setup_step(workspace: str, tool_name: str, args: dict) -> None:
    """Append or replace a setup step in the state file.

    If a step with the same tool name already exists, it is replaced
    (last-wins). This keeps the state file from growing unboundedly
    when the user calls the same tool multiple times.

    Parameters
    ----------
    workspace:
        Namespace for state isolation (default: "default").
    tool_name:
        The tool that was called (e.g. "load_aircraft_template").
    args:
        The kwargs dict passed to the tool.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_raw(workspace)
    steps: list[dict] = existing.get("setup_steps", [])

    # Replace existing step with same tool name, or append
    replaced = False
    for i, step in enumerate(steps):
        if step.get("tool") == tool_name:
            steps[i] = {"tool": tool_name, "args": args}
            replaced = True
            break
    if not replaced:
        steps.append({"tool": tool_name, "args": args})

    existing["setup_steps"] = steps
    _write_raw(workspace, existing)


def load_setup_steps(workspace: str) -> list[dict]:
    """Load the ordered list of setup steps from the state file.

    Returns an empty list if the workspace state file does not exist.
    """
    return _load_raw(workspace).get("setup_steps", [])


# ---------------------------------------------------------------------------
# Legacy surface persistence (backward-compatible with OAS)
# ---------------------------------------------------------------------------

def save_surfaces(workspace: str, surfaces: dict[str, dict]) -> None:
    """Save surface call arguments to the state file.

    Parameters
    ----------
    workspace:
        Namespace for state isolation (default: "default").
    surfaces:
        Mapping from surface name to the kwargs dict passed to create_surface.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_raw(workspace)
    existing["surfaces"] = {**existing.get("surfaces", {}), **surfaces}
    _write_raw(workspace, existing)


def load_surfaces(workspace: str) -> dict[str, dict]:
    """Load surface call arguments from the state file.

    Returns an empty dict if the workspace state file does not exist.
    """
    return _load_raw(workspace).get("surfaces", {})


# ---------------------------------------------------------------------------
# Common operations
# ---------------------------------------------------------------------------

def clear_state(workspace: str) -> None:
    """Delete the state file for the given workspace."""
    path = _state_path(workspace)
    if path.exists():
        path.unlink()


def _load_raw(workspace: str) -> dict:
    path = _state_path(workspace)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_raw(workspace: str, data: dict) -> None:
    path = _state_path(workspace)
    path.write_text(
        json.dumps(data, cls=_NumpyEncoder, indent=2),
        encoding="utf-8",
    )
