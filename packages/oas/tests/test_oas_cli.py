"""Tests for OAS-specific CLI behavior: tool registry, OAS tool invocations via CLI.

Migrated from: OpenAeroStruct/oas_mcp/tests/test_cli.py (OAS-specific tests only)

Import mapping applied:
  oas_mcp.cli        -> hangar.sdk.cli.main
  oas_mcp.cli_runner -> hangar.sdk.cli.runner
  oas_mcp.cli_state  -> hangar.sdk.cli.state
  oas_mcp.server     -> hangar.oas.server

The generic SDK CLI runner now uses set_registry_builder() instead of hardcoded
imports.  Tests that call get_registry() first call
set_registry_builder(build_oas_registry) where build_oas_registry is from
hangar.oas.cli.

Generic framework tests (name conversion, JSON serialization, output writing,
state persistence) are in packages/sdk/tests/test_cli.py.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hangar.sdk.cli.main import (
    _build_subparser,
    _coerce_json_args,
    oneshot_mode,
    run_script_mode,
    main,
)
from hangar.sdk.cli.runner import (
    get_registry,
    json_dumps,
    list_tools,
    run_tool,
    set_registry_builder,
    set_setup_tools,
)
from hangar.sdk.cli.state import (
    clear_state,
    load_setup_steps,
    load_surfaces,
    save_setup_step,
    save_surfaces,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _setup_oas_registry():
    """Wire up the OAS registry so CLI tests can resolve OAS tool functions."""
    from hangar.oas.cli import build_oas_registry

    set_registry_builder(build_oas_registry)
    set_setup_tools(["create_surface"])
    yield


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect CLI state dir to a temp directory."""
    import hangar.sdk.cli.state as cs

    monkeypatch.setattr(cs, "STATE_DIR", tmp_path / "state")
    return tmp_path / "state"


# ===========================================================================
# Argument parsing / subcommand generation
# ===========================================================================


def test_build_subparser_basic():
    """Subparser for create_surface should expose --name and --num-y flags."""
    from hangar.oas import server

    subparsers = argparse.ArgumentParser().add_subparsers()
    _build_subparser(subparsers, "create_surface", server.create_surface)

    # Parse with just --name and --num-y
    parser = argparse.ArgumentParser()
    sp = parser.add_subparsers(dest="mode")
    _build_subparser(sp, "create_surface", server.create_surface)

    ns = parser.parse_args(["create-surface", "--name", "mywing", "--num-y", "9"])
    assert ns.name == "mywing"
    assert ns.num_y == 9


def test_build_subparser_surfaces_json():
    """run_aero_analysis --surfaces should accept a JSON list string."""
    from hangar.oas import server

    parser = argparse.ArgumentParser()
    sp = parser.add_subparsers(dest="mode")
    _build_subparser(sp, "run_aero_analysis", server.run_aero_analysis)

    ns = parser.parse_args(
        ["run-aero-analysis", "--surfaces", '["wing"]', "--alpha", "5.0"]
    )
    # surfaces is still a string at parse time -- coercion happens in _coerce_json_args
    assert ns.surfaces == '["wing"]'
    assert ns.alpha == 5.0


def test_build_subparser_bool_flag():
    """Bool params should produce --flag / --no-flag pairs."""
    from hangar.oas import server

    parser = argparse.ArgumentParser()
    sp = parser.add_subparsers(dest="mode")
    _build_subparser(sp, "create_surface", server.create_surface)

    ns = parser.parse_args(["create-surface", "--name", "wing", "--with-viscous"])
    assert ns.with_viscous is True

    ns2 = parser.parse_args(["create-surface", "--name", "wing", "--no-with-viscous"])
    assert ns2.with_viscous is False


# ===========================================================================
# cli_runner: run_tool
# ===========================================================================


@pytest.mark.asyncio
async def test_run_tool_unknown():
    response = await run_tool("nonexistent_tool_xyz", {})
    assert response["ok"] is False
    assert "nonexistent_tool_xyz" in response["error"]["message"]


@pytest.mark.asyncio
async def test_run_tool_user_input_error():
    """Calling run_aero_analysis without creating a surface should error."""
    from hangar.oas.server import reset

    await reset()
    response = await run_tool("run_aero_analysis", {"surfaces": ["nonexistent_surface"]})
    assert response["ok"] is False


# ===========================================================================
# list_tools
# ===========================================================================


def test_list_tools():
    tools = list_tools()
    assert "create_surface" in tools
    assert "run_aero_analysis" in tools
    assert "run_optimization" in tools
    assert "reset" in tools
    assert "start_session" in tools


def test_list_tools_completeness():
    """All 24 tools (20 analysis + 4 provenance) should be registered."""
    tools = list_tools()
    assert len(tools) == 24, f"Expected 24 tools, got {len(tools)}: {tools}"


# ===========================================================================
# Script mode — with OAS tools
# ===========================================================================


def test_run_script_mode_basic(tmp_path, capsys):
    """Script mode executes steps in sequence and prints JSON-line results."""
    script = [
        {"tool": "create_surface", "args": {"name": "wing", "num_y": 7}},
    ]
    script_path = tmp_path / "workflow.json"
    script_path.write_text(json.dumps(script))

    from hangar.oas.server import reset

    asyncio.run(reset())
    run_script_mode(str(script_path))

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().splitlines() if l]
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is True


# ===========================================================================
# Interactive mode — with OAS tools
# ===========================================================================


@pytest.mark.asyncio
async def test_interactive_loop_single_command(monkeypatch, capsys):
    """Interactive loop parses a JSON line and produces a JSON-line response."""
    import asyncio
    from hangar.oas.server import reset

    await reset()

    # Feed a single create_surface command via a mock stdin
    line = json.dumps({"tool": "create_surface", "args": {"name": "wing", "num_y": 7}}) + "\n"

    async def _fake_loop(pretty=False):
        # Simulate what _interactive_loop does for one line
        cmd = json.loads(line.strip())
        response = await run_tool(cmd["tool"], cmd.get("args", {}))
        print(json_dumps(response, pretty=pretty), flush=True)

    await _fake_loop()

    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_interactive_loop_actual(capsys):
    """Test actual _interactive_loop with mocked stdin pipe."""
    import asyncio
    from hangar.oas.server import reset

    await reset()

    line = json.dumps({"tool": "create_surface", "args": {"name": "wing", "num_y": 7}}) + "\n"

    async def _patched_interactive(pretty=False):
        # Simulate the reader with an asyncio.StreamReader fed our data
        reader = asyncio.StreamReader()
        reader.feed_data(line.encode("utf-8"))
        reader.feed_eof()

        while True:
            line_bytes = await reader.readline()
            if not line_bytes:
                break
            text = line_bytes.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            cmd = json.loads(text)
            response = await run_tool(cmd["tool"], cmd.get("args", {}))
            print(json_dumps(response, pretty=pretty), flush=True)

    await _patched_interactive()

    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    assert result["ok"] is True


# ===========================================================================
# main() entry point — OAS-specific
# ===========================================================================


def test_main_list_tools(monkeypatch, capsys):
    """main() list-tools should print tool names."""
    from hangar.oas.cli import main as oas_main

    monkeypatch.setattr(sys, "argv", ["oas-cli", "list-tools"])
    oas_main()
    captured = capsys.readouterr()
    assert "create_surface" in captured.out
    assert "run_aero_analysis" in captured.out


# ===========================================================================
# One-shot mode (OAS-specific)
# ===========================================================================


def _make_ns(**kwargs):
    """Build an argparse.Namespace with defaults for create_surface."""
    fn = get_registry()["create_surface"]
    sig = inspect.signature(fn)
    defaults = {}
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        defaults[name] = param.default if param.default is not inspect.Parameter.empty else None
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_oneshot_create_surface(isolated_state, capsys):
    """One-shot create-surface should persist surface state."""
    from hangar.oas.server import reset

    asyncio.run(reset())

    ns = _make_ns(name="wing", num_y=7)
    oneshot_mode("create_surface", ns, workspace="test_ws")

    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    assert result["ok"] is True

    # Surface should be saved in state (generic setup-step path)
    steps = load_setup_steps("test_ws")
    assert any(s["tool"] == "create_surface" and s["args"].get("name") == "wing" for s in steps)


def test_oneshot_state_reconstruction(isolated_state, capsys):
    """One-shot analysis should reconstruct surfaces from saved state."""
    from hangar.oas.server import reset

    asyncio.run(reset())

    # Pre-save a surface in state (generic setup-step path)
    save_setup_step("test_ws", "create_surface", {"name": "wing", "num_y": 7})

    # Run aero analysis -- should reconstruct the surface first
    fn = get_registry()["run_aero_analysis"]
    sig = inspect.signature(fn)
    defaults = {}
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        defaults[name] = param.default if param.default is not inspect.Parameter.empty else None
    defaults["surfaces"] = '["wing"]'
    defaults["alpha"] = 5.0
    ns = argparse.Namespace(**defaults)

    oneshot_mode("run_aero_analysis", ns, workspace="test_ws")

    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    assert result["ok"] is True


def test_oneshot_workspace_isolation(isolated_state, capsys):
    """Surfaces in different workspaces should not interfere."""
    from hangar.oas.server import reset

    asyncio.run(reset())

    ns = _make_ns(name="wing", num_y=7)
    oneshot_mode("create_surface", ns, workspace="ws_a")
    capsys.readouterr()  # discard

    asyncio.run(reset())

    ns2 = _make_ns(name="tail", num_y=5)
    oneshot_mode("create_surface", ns2, workspace="ws_b")
    capsys.readouterr()

    steps_a = load_setup_steps("ws_a")
    steps_b = load_setup_steps("ws_b")
    assert any(s["args"].get("name") == "wing" for s in steps_a)
    assert not any(s["args"].get("name") == "tail" for s in steps_a)
    assert any(s["args"].get("name") == "tail" for s in steps_b)


def test_oneshot_reset_clears_state(isolated_state, capsys):
    """One-shot reset should clear the workspace state file."""
    from hangar.oas.server import reset as server_reset

    asyncio.run(server_reset())

    save_setup_step("test_ws", "create_surface", {"name": "wing", "num_y": 7})
    assert load_setup_steps("test_ws") != []

    # Build a namespace for reset (no params)
    ns = argparse.Namespace()
    oneshot_mode("reset", ns, workspace="test_ws")
    capsys.readouterr()

    assert load_setup_steps("test_ws") == []


def test_oneshot_output_file(isolated_state, tmp_path, capsys):
    """One-shot --output should write JSON to file."""
    from hangar.oas.server import reset

    asyncio.run(reset())

    out_path = tmp_path / "result.json"
    ns = _make_ns(name="wing", num_y=7)
    oneshot_mode("create_surface", ns, workspace="test_ws", output=str(out_path))

    assert out_path.exists()
    result = json.loads(out_path.read_text())
    assert result["ok"] is True


def test_oneshot_bad_saved_surface(isolated_state, capsys):
    """If saved surface has invalid args, should return structured error."""
    from hangar.oas.server import reset

    asyncio.run(reset())

    # Save a surface with invalid args (num_y must be odd >= 3)
    save_setup_step("test_ws", "create_surface", {"name": "bad", "num_y": 2})

    # Try to run analysis -- state reconstruction should fail gracefully
    fn = get_registry()["run_aero_analysis"]
    sig = inspect.signature(fn)
    defaults = {}
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        defaults[name] = param.default if param.default is not inspect.Parameter.empty else None
    defaults["surfaces"] = '["bad"]'
    defaults["alpha"] = 5.0
    ns = argparse.Namespace(**defaults)

    with pytest.raises(SystemExit):
        oneshot_mode("run_aero_analysis", ns, workspace="test_ws")

    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    assert result["ok"] is False
    assert "reconstruct" in result["error"]["message"].lower() or "state" in result["error"]["message"].lower()
