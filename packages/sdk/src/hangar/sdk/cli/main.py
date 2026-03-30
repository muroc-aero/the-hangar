"""Generic CLI framework: argument parsing, mode dispatch, interactive/one-shot/script modes.

Migrated from: OpenAeroStruct/oas_mcp/cli.py

Three modes:

  hangar interactive
      JSON-lines protocol over stdin/stdout.  Agents spawn this as a
      long-lived subprocess and exchange one JSON object per line.

  hangar run-script workflow.json
      Execute a sequence of tool calls from a JSON file in a single process
      (in-memory state is preserved across steps).

  hangar <tool-name> [--arg value ...]
      One-shot subcommand.  Surface definitions are persisted to a state file
      so multi-step workflows work across separate invocations.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import types as _types
import typing
from pathlib import Path
from typing import Any, Union, get_type_hints

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_arg(value: str, param_name: str) -> Any:
    """Parse a JSON string into a Python object."""
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--{param_name}: invalid JSON: {exc}"
        ) from exc


def _is_list_or_dict_type(annotation) -> bool:
    """Return True if the annotation is list[...], dict[...], or a Union containing one."""
    origin = getattr(annotation, "__origin__", None)
    if origin in (list, dict):
        return True
    # Handle typing.Union (typing.Optional, Union[X, None])
    if origin is Union:
        return any(_is_list_or_dict_type(a) for a in annotation.__args__ if a is not type(None))
    # Handle Python 3.10+ X | Y syntax (types.UnionType)
    if isinstance(annotation, _types.UnionType):
        return any(_is_list_or_dict_type(a) for a in annotation.__args__ if a is not type(None))
    return False


def _unwrap_annotated(annotation):
    """Strip typing.Annotated wrapper, returning the inner type."""
    if hasattr(annotation, "__metadata__"):  # typing.Annotated
        return annotation.__args__[0]
    return annotation


def _is_optional(annotation) -> bool:
    """Return True if annotation is Optional[X] (Union[X, None] or X | None)."""
    origin = getattr(annotation, "__origin__", None)
    if origin is Union:
        return type(None) in annotation.__args__
    # Python 3.10+ X | Y syntax
    if isinstance(annotation, _types.UnionType):
        return type(None) in annotation.__args__
    return False


def _argparse_type(annotation):
    """Return the argparse type callable for a given type annotation."""
    inner = _unwrap_annotated(annotation)
    # Strip Optional
    if _is_optional(inner):
        non_none = [a for a in inner.__args__ if a is not type(None)]
        if non_none:
            inner = non_none[0]

    if _is_list_or_dict_type(inner):
        return None  # JSON string — handled specially
    if inner is int:
        return int
    if inner is float:
        return float
    if inner is bool:
        return None  # handled as store_true/store_false
    return str  # default: string


def _snake_to_kebab(name: str) -> str:
    return name.replace("_", "-")


def _kebab_to_snake(name: str) -> str:
    return name.replace("-", "_")


# ---------------------------------------------------------------------------
# Build argparse subcommand from a tool function
# ---------------------------------------------------------------------------


def _build_subparser(subparsers, tool_name: str, fn) -> argparse.ArgumentParser:
    """Add a subparser for tool_name derived from fn's signature."""
    cmd_name = _snake_to_kebab(tool_name)
    sub = subparsers.add_parser(
        cmd_name,
        help=fn.__doc__.splitlines()[0] if fn.__doc__ else "",
    )

    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        raw_annotation = hints.get(param_name, param.annotation)
        if raw_annotation is inspect.Parameter.empty:
            raw_annotation = str

        inner = _unwrap_annotated(raw_annotation)
        default = param.default if param.default is not inspect.Parameter.empty else None
        flag = f"--{_snake_to_kebab(param_name)}"

        # Bool params: --flag / --no-flag
        actual_inner = inner
        if _is_optional(actual_inner):
            non_none = [a for a in actual_inner.__args__ if a is not type(None)]
            actual_inner = non_none[0] if non_none else str

        if actual_inner is bool:
            group = sub.add_mutually_exclusive_group()
            group.add_argument(flag, dest=param_name, action="store_true", default=default)
            group.add_argument(
                f"--no-{_snake_to_kebab(param_name)}",
                dest=param_name,
                action="store_false",
            )
        elif _is_list_or_dict_type(inner) or _is_list_or_dict_type(actual_inner):
            # Accept JSON string
            sub.add_argument(
                flag,
                dest=param_name,
                default=default,
                metavar="JSON",
                help=f"JSON value (e.g. '[1,2,3]' or '{{\"key\":val}}')",
            )
        else:
            arg_type = _argparse_type(raw_annotation)
            sub.add_argument(
                flag,
                dest=param_name,
                default=default,
                type=arg_type,
            )

    return sub


# ---------------------------------------------------------------------------
# Mode 1: interactive JSON-lines
# ---------------------------------------------------------------------------


async def _interactive_loop(pretty: bool = False) -> None:
    """Read JSON-line commands from stdin, write JSON-line responses to stdout."""
    from hangar.sdk.cli.runner import run_tool, json_dumps

    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line_bytes = await reader.readline()
        except Exception as exc:
            print(f"Error reading stdin: {exc}", file=sys.stderr)
            break

        if not line_bytes:
            break

        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            continue

        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {
                "ok": False,
                "error": {"code": "USER_INPUT_ERROR", "message": f"Invalid JSON: {exc}"},
            }
            print(json_dumps(response, pretty=pretty), flush=True)
            continue

        tool_name = cmd.get("tool", "")
        args = cmd.get("args", {})

        response = await run_tool(tool_name, args)
        print(json_dumps(response, pretty=pretty), flush=True)


def interactive_mode(pretty: bool = False) -> None:
    """Run the JSON-lines interactive loop."""
    asyncio.run(_interactive_loop(pretty=pretty))


# ---------------------------------------------------------------------------
# Mode 2: one-shot subcommand
# ---------------------------------------------------------------------------


def _coerce_json_args(tool_name: str, args_ns: argparse.Namespace) -> dict:
    """Convert string args to typed values (parse JSON where needed)."""
    from hangar.sdk.cli.runner import get_registry

    registry = get_registry()
    fn = registry.get(tool_name)
    if fn is None:
        return vars(args_ns)

    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}

    result = {}
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        value = getattr(args_ns, param_name, None)
        if value is None:
            if param.default is not inspect.Parameter.empty:
                continue  # let the function use its own default
            else:
                continue  # skip — no value provided

        raw_annotation = hints.get(param_name, param.annotation)
        inner = _unwrap_annotated(raw_annotation)
        actual_inner = inner
        if _is_optional(actual_inner):
            non_none = [a for a in actual_inner.__args__ if a is not type(None)]
            actual_inner = non_none[0] if non_none else str

        if isinstance(value, str) and (_is_list_or_dict_type(inner) or _is_list_or_dict_type(actual_inner)):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                print(
                    f"Error: --{_snake_to_kebab(param_name)}: invalid JSON: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)

        result[param_name] = value

    return result


def oneshot_mode(
    tool_name: str,
    args_ns: argparse.Namespace,
    workspace: str = "default",
    pretty: bool = False,
    output: str | None = None,
) -> None:
    """Execute a single tool call, persisting setup state for one-shot mode.

    Before running the requested tool, any saved setup steps from prior
    invocations are replayed to reconstruct the session. After the tool
    completes, its args are saved if it's a declared setup tool.

    Two state paths are supported:

    1. **Generic setup steps** — used when ``set_setup_tools()`` has been
       called by the tool server. Steps are saved as an ordered list and
       replayed in declaration order before analysis tools.

    2. **Legacy surface persistence** — backward-compatible fallback for
       OAS when no setup tools are declared. Saves ``create_surface()``
       args and replays them via the ``"create_surface"`` registry entry.
    """
    from hangar.sdk.cli.runner import run_tool, get_registry, get_setup_tools, json_dumps
    from hangar.sdk.cli.state import (
        load_setup_steps, save_setup_step,
        load_surfaces, save_surfaces,
        clear_state,
    )

    registry = get_registry()
    setup_tools = get_setup_tools()
    is_setup_tool = tool_name in setup_tools

    # Parse and coerce args before entering the event loop
    tool_args = _coerce_json_args(tool_name, args_ns)

    async def _run() -> dict:
        if setup_tools:
            # --- Generic path: replay setup steps ---
            # Replay saved steps that precede the current tool in declaration order.
            # Analysis tools (not in setup_tools) get all steps replayed.
            # Setup tools get only the steps that come *before* them.
            if tool_name != "reset":
                saved_steps = load_setup_steps(workspace)
                if is_setup_tool:
                    # Only replay steps that come before this tool in the order
                    my_idx = setup_tools.index(tool_name)
                    predecessors = set(setup_tools[:my_idx])
                    steps_to_replay = [s for s in saved_steps if s["tool"] in predecessors]
                else:
                    steps_to_replay = saved_steps

                for step in steps_to_replay:
                    step_fn = registry.get(step["tool"])
                    if step_fn is None:
                        continue
                    try:
                        await step_fn(**step.get("args", {}))
                    except Exception as exc:
                        return {
                            "ok": False,
                            "error": {
                                "code": "INTERNAL_ERROR",
                                "message": (
                                    f"Failed to reconstruct state from saved "
                                    f"step '{step['tool']}': {exc}"
                                ),
                            },
                        }
        else:
            # --- Legacy path: replay create_surface calls ---
            saved_surfaces = load_surfaces(workspace)
            create_surface_fn = registry.get("create_surface")
            if saved_surfaces and create_surface_fn and tool_name != "create_surface":
                for surf_args in saved_surfaces.values():
                    try:
                        await create_surface_fn(**surf_args)
                    except Exception as exc:
                        return {
                            "ok": False,
                            "error": {
                                "code": "INTERNAL_ERROR",
                                "message": f"Failed to reconstruct surface from saved state: {exc}",
                            },
                        }

        # Run the actual tool
        return await run_tool(tool_name, tool_args)

    # Single event loop for both state reconstruction and tool execution
    response = asyncio.run(_run())

    # --- Post-tool state persistence ---
    if response.get("ok"):
        if setup_tools:
            # Generic path: save setup tool args
            if is_setup_tool:
                save_setup_step(workspace, tool_name, tool_args)
        else:
            # Legacy path: save create_surface args
            if tool_name == "create_surface":
                surface_name = tool_args.get("name", "wing")
                save_surfaces(workspace, {surface_name: tool_args})

        # Reset always clears state (both paths)
        if tool_name == "reset":
            clear_state(workspace)

    _output_response(response, pretty=pretty, output=output)


# ---------------------------------------------------------------------------
# Mode 3: script/batch
# ---------------------------------------------------------------------------


async def _run_script_async(
    steps: list[dict],
    pretty: bool = False,
    output: str | None = None,
) -> None:
    """Execute a list of tool-call dicts in sequence (in-memory state shared)."""
    from hangar.sdk.cli.runner import run_tool, interpolate_args, json_dumps

    all_results = []
    for i, step in enumerate(steps):
        tool_name = step.get("tool", "")
        args = step.get("args", {})
        # Interpolate $prev.run_id and $N.run_id references
        try:
            args = interpolate_args(args, all_results)
        except ValueError as exc:
            response = {
                "ok": False,
                "error": {"code": "USER_INPUT_ERROR", "message": str(exc)},
            }
            all_results.append({"step": i, "tool": tool_name, **response})
            if output is None:
                print(json_dumps(response, pretty=pretty), flush=True)
            continue
        response = await run_tool(tool_name, args)
        all_results.append({"step": i, "tool": tool_name, **response})
        # Print each result as it completes for streaming output
        if output is None:
            print(json_dumps(response, pretty=pretty), flush=True)

    if output is not None:
        _write_output(all_results, output, pretty)


def run_script_mode(
    script_path: str,
    pretty: bool = False,
    output: str | None = None,
) -> None:
    """Execute a workflow JSON script."""
    path = Path(script_path)
    if not path.exists():
        print(f"Error: script file not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    try:
        steps = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {script_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(steps, list):
        print("Error: script must be a JSON array of tool-call objects", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run_script_async(steps, pretty=pretty, output=output))


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _output_response(response: dict, pretty: bool, output: str | None) -> None:
    from hangar.sdk.cli.runner import json_dumps

    text = json_dumps(response, pretty=pretty)
    if output:
        _write_output(response, output, pretty)
    else:
        print(text, flush=True)
    # Exit non-zero on error
    if not response.get("ok", True):
        sys.exit(1)


def _write_output(data: Any, path: str, pretty: bool) -> None:
    from hangar.sdk.cli.runner import json_dumps

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Special case: if data contains base64 PNG image(s), decode to file(s)
    if isinstance(data, dict) and "result" in data:
        result = data["result"]
        if isinstance(result, list):
            import base64
            images = [
                item for item in result
                if isinstance(item, dict) and item.get("type") == "image"
            ]
            if images:
                if len(images) == 1:
                    p.write_bytes(base64.b64decode(images[0].get("data", "")))
                else:
                    for i, item in enumerate(images):
                        numbered = p.with_stem(f"{p.stem}_{i}")
                        numbered.write_bytes(base64.b64decode(item.get("data", "")))
                return

    p.write_text(json_dumps(data, pretty=pretty), encoding="utf-8")


# ---------------------------------------------------------------------------
# Convenience commands
# ---------------------------------------------------------------------------


def _cmd_list_runs(
    limit: int = 10,
    analysis_type: str | None = None,
    pretty: bool = False,
    output: str | None = None,
) -> None:
    """List recent analysis runs."""
    from hangar.sdk.cli.runner import run_tool_sync, json_dumps

    args: dict = {}
    if analysis_type:
        args["analysis_type"] = analysis_type

    response = run_tool_sync("list_artifacts", args)
    if not response.get("ok"):
        _output_response(response, pretty=pretty, output=output)
        return

    result = response.get("result", [])
    # list_artifacts returns {"count": N, "artifacts": [...]} or a raw list
    entries = result.get("artifacts", result) if isinstance(result, dict) else result
    # Sort by run_id (chronological) descending, take latest N
    entries.sort(key=lambda e: e.get("run_id", ""), reverse=True)
    entries = entries[:limit]

    # Print a concise table to stdout
    if output:
        _write_output(entries, output, pretty)
    else:
        if not entries:
            print("No runs found.")
            return
        fmt = "{:<28s}  {:<14s}  {:<20s}  {}"
        print(fmt.format("RUN_ID", "TYPE", "TOOL", "SURFACES"))
        print("-" * 80)
        for e in entries:
            print(fmt.format(
                e.get("run_id", "?"),
                e.get("analysis_type", "?"),
                e.get("tool_name", "?"),
                ", ".join(e.get("surfaces", [])),
            ))


def _cmd_show(
    run_id: str = "latest",
    pretty: bool = False,
    output: str | None = None,
) -> None:
    """Show summary of a run's results."""
    from hangar.sdk.cli.runner import run_tool_sync, json_dumps

    response = run_tool_sync("get_run", {"run_id": run_id})
    _output_response(response, pretty=True, output=output)


def _cmd_plot(
    run_id: str = "latest",
    plot_type: str = "lift_distribution",
    out: str | None = None,
) -> None:
    """Save a plot PNG to disk."""
    from hangar.sdk.cli.runner import run_tool_sync, json_dumps

    response = run_tool_sync("visualize", {
        "run_id": run_id,
        "plot_type": plot_type,
        "output": "file",
    })

    if not response.get("ok"):
        _output_response(response, pretty=True, output=None)
        return

    result = response.get("result", [])
    # Extract the file_path from metadata
    meta = result[0] if isinstance(result, list) and result else result
    file_path = meta.get("file_path") if isinstance(meta, dict) else None

    if out and file_path:
        # Move/copy to requested output path
        import shutil
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, out)
        print(f"Plot saved to: {out}")
    elif file_path:
        print(f"Plot saved to: {file_path}")
    else:
        print(json_dumps(response, pretty=True))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(
    prog: str = "hangar",
    description: str = "Hangar CLI -- run analysis tools from the command line.",
    viewer_callback=None,
) -> None:
    """Generic CLI entry point.

    Parameters
    ----------
    prog:
        Program name shown in help text.
    description:
        Description shown in help text.
    viewer_callback:
        Optional callable(port, db) to start a viewer/dashboard server.
        If None, the ``viewer`` subcommand is not registered.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description,
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON output"
    )
    parser.add_argument(
        "--workspace",
        default="default",
        help="State file namespace for one-shot mode (default: 'default')",
    )
    parser.add_argument(
        "--save-to", default=None, dest="save_to", metavar="FILE",
        help="Write output to FILE instead of stdout",
    )

    subparsers = parser.add_subparsers(dest="mode", metavar="MODE")

    # --- Mode 1: interactive ---
    subparsers.add_parser(
        "interactive",
        help="JSON-lines protocol over stdin/stdout (for agent subprocesses)",
    )

    # --- Mode 3: run-script ---
    script_parser = subparsers.add_parser(
        "run-script",
        help="Execute a batch workflow JSON file",
    )
    script_parser.add_argument("script", metavar="SCRIPT.json", help="Path to workflow JSON file")

    # --- list-tools ---
    subparsers.add_parser("list-tools", help="Print available tool names and exit")

    # --- list-runs ---
    lr_parser = subparsers.add_parser("list-runs", help="Show recent analysis runs")
    lr_parser.add_argument("--limit", type=int, default=10, help="Max runs to show (default: 10)")
    lr_parser.add_argument("--analysis-type", default=None, help="Filter by analysis type")

    # --- show ---
    show_parser = subparsers.add_parser("show", help="Show summary of a run's results")
    show_parser.add_argument("run_id", nargs="?", default="latest", help="Run ID (default: latest)")

    # --- plot ---
    plot_parser = subparsers.add_parser("plot", help="Save a plot to disk (shorthand for visualize)")
    plot_parser.add_argument("run_id", nargs="?", default="latest", help="Run ID (default: latest)")
    plot_parser.add_argument("plot_type", help="Plot type (e.g. lift_distribution, drag_polar)")
    plot_parser.add_argument("-o", "--out", default=None, help="Output file path (default: <run_id>_<plot_type>.png)")

    # --- viewer (optional) ---
    if viewer_callback is not None:
        viewer_parser = subparsers.add_parser(
            "viewer",
            help="Start the provenance/dashboard viewer server (http://localhost:PORT)",
        )
        viewer_parser.add_argument(
            "--port", type=int, default=7654, help="Port to listen on (default: 7654)",
        )
        viewer_parser.add_argument(
            "--db", default=None, metavar="PATH",
            help="Path to provenance SQLite file",
        )

    # --- Mode 2: one-shot tool subcommands ---
    try:
        from hangar.sdk.cli.runner import get_registry

        registry = get_registry()
        for tool_name, fn in sorted(registry.items()):
            _build_subparser(subparsers, tool_name, fn)
    except Exception:
        # If server import fails (missing deps), still allow --help
        pass

    args = parser.parse_args()

    pretty = args.pretty
    workspace = args.workspace
    output = args.save_to

    if args.mode == "interactive":
        interactive_mode(pretty=pretty)

    elif args.mode == "run-script":
        run_script_mode(args.script, pretty=pretty, output=output)

    elif args.mode == "list-tools":
        from hangar.sdk.cli.runner import list_tools
        print("\n".join(list_tools()))

    elif args.mode == "list-runs":
        _cmd_list_runs(
            limit=args.limit,
            analysis_type=args.analysis_type,
            pretty=pretty,
            output=output,
        )

    elif args.mode == "show":
        _cmd_show(run_id=args.run_id, pretty=pretty, output=output)

    elif args.mode == "plot":
        _cmd_plot(
            run_id=args.run_id,
            plot_type=args.plot_type,
            out=args.out,
        )

    elif args.mode == "viewer" and viewer_callback is not None:
        viewer_callback(port=args.port, db=args.db)

    elif args.mode is None:
        parser.print_help()
        sys.exit(0)

    else:
        # One-shot subcommand: convert kebab mode to snake_case tool name
        tool_name = _kebab_to_snake(args.mode)
        oneshot_mode(
            tool_name=tool_name,
            args_ns=args,
            workspace=workspace,
            pretty=pretty,
            output=output,
        )
