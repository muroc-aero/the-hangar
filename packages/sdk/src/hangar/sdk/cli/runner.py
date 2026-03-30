"""Generic CLI execution logic: tool registry, run_tool(), JSON serialization.

Provides a tool registry and run_tool() function used by all three CLI modes.
The registry is populated by calling ``set_registry_builder(builder_fn)`` with
a callable that returns a ``dict[str, Callable]`` mapping tool names to async
functions.  This keeps the runner generic -- server-specific tool imports live
in the server package, not here.

Migrated from: OpenAeroStruct/oas_mcp/cli_runner.py (generic parts only)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import numpy as np

# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


class _NumpyEncoder(json.JSONEncoder):
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


def json_dumps(obj: Any, pretty: bool = False) -> str:
    """Serialize obj to JSON, handling numpy types."""
    indent = 2 if pretty else None
    return json.dumps(obj, cls=_NumpyEncoder, indent=indent)


# ---------------------------------------------------------------------------
# Tool registry — populated lazily on first access
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable] | None = None
_REGISTRY_BUILDER: Callable[[], dict[str, Callable]] | None = None

# Setup tools: tools whose args should be persisted and replayed in one-shot mode.
# Ordered list of tool names — replay order matches declaration order.
_SETUP_TOOLS: list[str] = []


def set_registry_builder(builder: Callable[[], dict[str, Callable]]) -> None:
    """Register a callable that builds the tool name -> function mapping.

    The builder is invoked lazily on the first call to ``get_registry()``.
    This allows server packages to supply their own tool imports without
    hardcoding them in the SDK.

    Parameters
    ----------
    builder:
        A zero-argument callable returning ``dict[str, Callable]``.
    """
    global _REGISTRY_BUILDER, _REGISTRY
    _REGISTRY_BUILDER = builder
    _REGISTRY = None  # reset so next get_registry() calls the new builder


def set_setup_tools(tool_names: list[str]) -> None:
    """Declare which tools produce persistent state for one-shot mode.

    When a tool listed here succeeds, its arguments are saved to the
    workspace state file. Before running any non-setup tool, the saved
    setup steps are replayed in order to reconstruct the session.

    The ``"reset"`` tool is always handled specially (clears state) and
    does not need to be listed.

    Call this alongside ``set_registry_builder()`` in your CLI entry point.

    Parameters
    ----------
    tool_names:
        Ordered list of tool names. Replay order matches this order,
        regardless of the order the user originally called them.

    Example
    -------
    OAS declares::

        set_setup_tools(["create_surface"])

    OCP declares::

        set_setup_tools([
            "load_aircraft_template",
            "define_aircraft",
            "set_propulsion_architecture",
            "configure_mission",
        ])
    """
    global _SETUP_TOOLS
    _SETUP_TOOLS = list(tool_names)


def get_setup_tools() -> list[str]:
    """Return the declared setup tool names."""
    return list(_SETUP_TOOLS)


def get_registry() -> dict[str, Callable]:
    """Return the tool registry, building it on first access.

    Raises
    ------
    RuntimeError
        If no registry builder has been set via ``set_registry_builder()``.
    """
    global _REGISTRY
    if _REGISTRY is None:
        if _REGISTRY_BUILDER is None:
            raise RuntimeError(
                "No tool registry builder configured. "
                "Call set_registry_builder(builder_fn) before using the CLI."
            )
        _REGISTRY = _REGISTRY_BUILDER()
    return _REGISTRY


# ---------------------------------------------------------------------------
# run_tool — call a tool by name, return JSON-serializable dict
# ---------------------------------------------------------------------------


_last_run_id: str | None = None


def _extract_run_id(response: dict) -> str | None:
    """Extract run_id from a successful tool response."""
    if not response.get("ok"):
        return None
    result = response.get("result")
    if isinstance(result, dict):
        return result.get("run_id")
    return None


def interpolate_args(args: dict, prev_results: list[dict]) -> dict:
    """Replace ``$prev.run_id`` and ``$N.run_id`` references in string arg values.

    - ``$prev.run_id`` -> run_id from the most recent successful step
    - ``$1.run_id``    -> run_id from step 1's result (1-indexed)
    - ``latest``/``last`` as a run_id value -> left as-is (handled server-side)
    """
    out = {}
    for key, value in args.items():
        if isinstance(value, str):
            if value == "$prev.run_id":
                # Find most recent run_id walking backwards
                for prev in reversed(prev_results):
                    rid = _extract_run_id(prev)
                    if rid:
                        value = rid
                        break
            elif value.startswith("$") and value.endswith(".run_id"):
                # $N.run_id — step reference (1-indexed)
                try:
                    idx = int(value[1:].split(".")[0]) - 1
                    if 0 <= idx < len(prev_results):
                        rid = _extract_run_id(prev_results[idx])
                        if rid:
                            value = rid
                        else:
                            step_tool = prev_results[idx].get("tool", "unknown")
                            raise ValueError(
                                f"Cannot resolve {value!r}: step {idx + 1} "
                                f"({step_tool}) did not return a run_id. "
                                f"Use $prev.run_id to reference the most "
                                f"recent step that produced a run_id."
                            )
                    else:
                        raise ValueError(
                            f"Cannot resolve {value!r}: only "
                            f"{len(prev_results)} steps have completed so far."
                        )
                except ValueError:
                    raise
                except (IndexError,):
                    pass
        out[key] = value
    return out


async def run_tool(name: str, args: dict) -> dict:
    """Call a tool function by name with the given args.

    Returns a dict with either ``{"ok": True, "result": ...}`` or
    ``{"ok": False, "error": {"code": ..., "message": ...}}``.
    """
    registry = get_registry()
    fn = registry.get(name)
    if fn is None:
        return {
            "ok": False,
            "error": {
                "code": "USER_INPUT_ERROR",
                "message": f"Unknown tool: {name!r}. Available: {sorted(registry)}",
            },
        }

    # In interactive mode, resolve "latest"/"last" run_id to the tracked value
    global _last_run_id
    if "run_id" in args and isinstance(args["run_id"], str):
        if args["run_id"].lower() in ("latest", "last") and _last_run_id is not None:
            args = {**args, "run_id": _last_run_id}

    try:
        result = await fn(**args)
        # visualize() returns a list (image + metadata) — serialize to JSON-safe form
        if isinstance(result, list):
            result = _serialize_list(result)
        response = {"ok": True, "result": result}
        # Track the last run_id for interactive chaining
        rid = _extract_run_id(response)
        if rid:
            _last_run_id = rid
        return response
    except Exception as exc:
        # Try to use structured error if available
        if hasattr(exc, "to_dict"):
            return {"ok": False, "error": exc.to_dict()}
        return {
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc),
            },
        }


def run_tool_sync(name: str, args: dict) -> dict:
    """Synchronous wrapper around run_tool()."""
    return asyncio.run(run_tool(name, args))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_list(items: list) -> list:
    """Convert a mixed list (may contain MCP ImageContent / TextContent) to JSON-safe form."""
    out = []
    for item in items:
        if hasattr(item, "model_dump"):
            out.append(item.model_dump())
        elif hasattr(item, "__dict__"):
            out.append(vars(item))
        else:
            out.append(item)
    return out


def list_tools() -> list[str]:
    """Return sorted list of available tool names."""
    return sorted(get_registry())
