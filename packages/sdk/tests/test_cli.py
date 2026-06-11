"""Tests for generic CLI framework: argument parsing, JSON serialization, output writing, state persistence.

Migrated from:
  - OpenAeroStruct/oas_mcp/tests/test_cli.py (generic/framework tests only)
  - OpenAeroStruct/oas_mcp/tests/test_cli_state.py (all state tests)

Import mapping applied:
  oas_mcp.cli        -> hangar.sdk.cli.main
  oas_mcp.cli_runner -> hangar.sdk.cli.runner
  oas_mcp.cli_state  -> hangar.sdk.cli.state

OAS-specific tests (tool registry, OAS tool invocations via CLI) moved to
packages/oas/tests/test_cli.py instead.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from unittest.mock import patch

import numpy as np
import pytest

from hangar.sdk.cli.main import (
    _coerce_json_args,
    _kebab_to_snake,
    _snake_to_kebab,
    _write_output,
)
from hangar.sdk.cli.runner import json_dumps
from hangar.sdk.cli.state import (
    clear_state,
    load_surfaces,
    save_surfaces,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _setup_oas_registry():
    """Wire up the OAS registry so generic CLI tests can resolve tool functions."""
    from hangar.sdk.cli.runner import set_registry_builder
    from hangar.oas.cli import build_oas_registry

    set_registry_builder(build_oas_registry)
    yield


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect STATE_DIR to a per-test temp directory."""
    import hangar.sdk.cli.state as cs

    monkeypatch.setattr(cs, "STATE_DIR", tmp_path / "state")
    yield tmp_path / "state"


# ===========================================================================
# Name conversion helpers
# ===========================================================================


def test_snake_to_kebab():
    assert _snake_to_kebab("run_aero_analysis") == "run-aero-analysis"
    assert _snake_to_kebab("create_surface") == "create-surface"
    assert _snake_to_kebab("reset") == "reset"


def test_kebab_to_snake():
    assert _kebab_to_snake("run-aero-analysis") == "run_aero_analysis"
    assert _kebab_to_snake("create-surface") == "create_surface"
    assert _kebab_to_snake("reset") == "reset"


# ===========================================================================
# JSON arg coercion
# ===========================================================================


def test_coerce_json_args_list():
    """surfaces arg (list[str]) should be parsed from JSON string."""
    ns = argparse.Namespace(
        surfaces='["wing", "tail"]',
        alpha=5.0,
        velocity=None,
        Mach_number=None,
        reynolds_number=None,
        density=None,
        cg=None,
        session_id=None,
        run_name=None,
    )
    result = _coerce_json_args("run_aero_analysis", ns)
    assert result["surfaces"] == ["wing", "tail"]
    assert result["alpha"] == 5.0


def test_coerce_json_args_dict():
    """dict-typed args should be parsed from JSON string."""
    ns = argparse.Namespace(
        surfaces='["wing"]',
        alpha=None,
        velocity=None,
        Mach_number=None,
        reynolds_number=None,
        density=None,
        cg='[1.0, 0.0, 0.0]',
        session_id=None,
        run_name=None,
    )
    result = _coerce_json_args("run_aero_analysis", ns)
    assert result["cg"] == [1.0, 0.0, 0.0]


def test_coerce_json_args_none_skipped():
    """None values with defaults should not appear in result (let function use defaults)."""
    ns = argparse.Namespace(
        surfaces='["wing"]',
        alpha=None,
        velocity=None,
        Mach_number=None,
        reynolds_number=None,
        density=None,
        cg=None,
        session_id=None,
        run_name=None,
    )
    result = _coerce_json_args("run_aero_analysis", ns)
    assert "alpha" not in result
    assert "velocity" not in result


def test_coerce_json_invalid_json_exits(monkeypatch):
    """Invalid JSON for a list param should sys.exit(1)."""
    ns = argparse.Namespace(
        surfaces="not-valid-json",
        alpha=5.0,
        velocity=None,
        Mach_number=None,
        reynolds_number=None,
        density=None,
        cg=None,
        session_id=None,
        run_name=None,
    )
    with pytest.raises(SystemExit) as exc_info:
        _coerce_json_args("run_aero_analysis", ns)
    assert exc_info.value.code == 1


# ===========================================================================
# json_dumps
# ===========================================================================


def test_json_dumps_numpy():
    data = {"arr": np.array([1.0, 2.0]), "val": np.float64(3.14)}
    text = json_dumps(data)
    parsed = json.loads(text)
    assert parsed["arr"] == [1.0, 2.0]
    assert abs(parsed["val"] - 3.14) < 1e-6


def test_json_dumps_pretty():
    text = json_dumps({"a": 1}, pretty=True)
    assert "\n" in text  # indented output


# ===========================================================================
# Script mode — error paths (no OAS dependency)
# ===========================================================================


def test_run_script_mode_missing_file(tmp_path):
    from hangar.sdk.cli.main import run_script_mode

    with pytest.raises(SystemExit):
        run_script_mode(str(tmp_path / "does_not_exist.json"))


def test_run_script_mode_invalid_json(tmp_path):
    from hangar.sdk.cli.main import run_script_mode

    p = tmp_path / "bad.json"
    p.write_text("not json")
    with pytest.raises(SystemExit):
        run_script_mode(str(p))


def test_run_script_mode_not_array(tmp_path):
    from hangar.sdk.cli.main import run_script_mode

    p = tmp_path / "obj.json"
    p.write_text('{"tool": "reset"}')
    with pytest.raises(SystemExit):
        run_script_mode(str(p))


# ===========================================================================
# Interactive mode — malformed JSON
# ===========================================================================


@pytest.mark.asyncio
async def test_interactive_loop_malformed_json(capsys):
    """Malformed JSON in interactive mode should produce an error response, not crash."""
    import asyncio
    from hangar.sdk.cli.runner import run_tool, json_dumps

    bad_line = "not valid json\n"
    good_line = json.dumps({"tool": "reset", "args": {}}) + "\n"
    data = (bad_line + good_line).encode("utf-8")

    async def _run():
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()

        while True:
            line_bytes = await reader.readline()
            if not line_bytes:
                break
            text = line_bytes.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                cmd = json.loads(text)
            except json.JSONDecodeError as exc:
                response = {
                    "ok": False,
                    "error": {"code": "USER_INPUT_ERROR", "message": f"Invalid JSON: {exc}"},
                }
                print(json_dumps(response), flush=True)
                continue

            response = await run_tool(cmd["tool"], cmd.get("args", {}))
            print(json_dumps(response), flush=True)

    await _run()

    captured = capsys.readouterr()
    lines = [ln for ln in captured.out.strip().splitlines() if ln]
    assert len(lines) == 2
    err = json.loads(lines[0])
    assert err["ok"] is False
    assert err["error"]["code"] == "USER_INPUT_ERROR"
    ok = json.loads(lines[1])
    assert ok["ok"] is True


# ===========================================================================
# _write_output
# ===========================================================================


def test_write_output_json(tmp_path):
    """_write_output should write JSON when no images are present."""
    out = tmp_path / "out.json"
    _write_output({"ok": True, "result": {"CL": 0.5}}, str(out), pretty=True)
    data = json.loads(out.read_text())
    assert data["result"]["CL"] == 0.5


def test_write_output_single_image(tmp_path):
    """_write_output should decode a single base64 PNG."""
    fake_png = base64.b64encode(b"fake-png-data").decode()
    out = tmp_path / "plot.png"
    _write_output(
        {"ok": True, "result": [{"type": "image", "data": fake_png}]},
        str(out),
        pretty=False,
    )
    assert out.read_bytes() == b"fake-png-data"


def test_write_output_multiple_images(tmp_path):
    """_write_output should save multiple images with numbered suffixes."""
    img1 = base64.b64encode(b"img-one").decode()
    img2 = base64.b64encode(b"img-two").decode()
    out = tmp_path / "plot.png"
    _write_output(
        {"ok": True, "result": [
            {"type": "image", "data": img1},
            {"type": "image", "data": img2},
        ]},
        str(out),
        pretty=False,
    )
    assert (tmp_path / "plot_0.png").read_bytes() == b"img-one"
    assert (tmp_path / "plot_1.png").read_bytes() == b"img-two"


def test_write_output_creates_dirs(tmp_path):
    """_write_output should create parent directories."""
    out = tmp_path / "nested" / "deep" / "out.json"
    _write_output({"ok": True}, str(out), pretty=False)
    assert out.exists()


# ===========================================================================
# main() entry point — generic (no OAS tools listed)
# ===========================================================================


def test_main_no_args(monkeypatch, capsys):
    """main() with no args should print help and exit 0."""
    from hangar.sdk.cli.main import main

    monkeypatch.setattr(sys, "argv", ["hangar"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


# ===========================================================================
# State persistence (migrated from test_cli_state.py)
# ===========================================================================


def test_save_and_load_surfaces(isolated_state):
    args = {"name": "wing", "wing_type": "rect", "num_y": 7}
    save_surfaces("default", {"wing": args})
    loaded = load_surfaces("default")
    assert loaded == {"wing": args}


def test_load_missing_workspace():
    loaded = load_surfaces("nonexistent_workspace_xyz")
    assert loaded == {}


def test_save_merges_existing(isolated_state):
    save_surfaces("ws", {"wing": {"name": "wing"}})
    save_surfaces("ws", {"tail": {"name": "tail"}})
    loaded = load_surfaces("ws")
    assert "wing" in loaded
    assert "tail" in loaded


def test_save_overwrites_same_name(isolated_state):
    save_surfaces("ws", {"wing": {"name": "wing", "num_y": 7}})
    save_surfaces("ws", {"wing": {"name": "wing", "num_y": 9}})
    loaded = load_surfaces("ws")
    assert loaded["wing"]["num_y"] == 9


def test_clear_state(isolated_state):
    save_surfaces("ws", {"wing": {"name": "wing"}})
    clear_state("ws")
    loaded = load_surfaces("ws")
    assert loaded == {}


def test_clear_missing_state_is_noop(isolated_state):
    # Should not raise
    clear_state("does_not_exist")


def test_workspace_isolation(isolated_state):
    save_surfaces("ws1", {"wing": {"name": "wing"}})
    save_surfaces("ws2", {"tail": {"name": "tail"}})
    assert "wing" in load_surfaces("ws1")
    assert "tail" not in load_surfaces("ws1")
    assert "tail" in load_surfaces("ws2")
    assert "wing" not in load_surfaces("ws2")


def test_numpy_arrays_serialized(isolated_state):
    import numpy as np

    args = {"name": "wing", "twist_cp": np.array([1.0, 2.0, 3.0])}
    save_surfaces("ws", {"wing": args})

    # Read raw file to verify numpy array was serialized as list
    import hangar.sdk.cli.state as cs
    path = cs._state_path("ws")
    raw = json.loads(path.read_text())
    assert raw["surfaces"]["wing"]["twist_cp"] == [1.0, 2.0, 3.0]


def test_load_corrupt_state_returns_empty(isolated_state):
    import hangar.sdk.cli.state as cs

    cs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = cs._state_path("ws")
    path.write_text("not valid json", encoding="utf-8")
    loaded = load_surfaces("ws")
    assert loaded == {}


# ---------------------------------------------------------------------------
# viewer_command (shared `viewer` subcommand)
# ---------------------------------------------------------------------------


def test_viewer_command_exits_when_server_fails(monkeypatch):
    """Port busy (start_viewer_server returns None) exits with code 1."""
    import os

    from hangar.sdk.cli.main import viewer_command

    monkeypatch.delenv("HANGAR_PROV_PORT", raising=False)
    with patch.dict(os.environ), patch(
        "hangar.sdk.viz.viewer_server.start_viewer_server", return_value=None
    ):
        with pytest.raises(SystemExit) as excinfo:
            viewer_command(port=7991)
    assert excinfo.value.code == 1


def test_viewer_command_sets_env_from_args(monkeypatch, tmp_path):
    """--port and --db reach the viewer via HANGAR_PROV_PORT/HANGAR_PROV_DB."""
    import os

    from hangar.sdk.cli.main import viewer_command

    monkeypatch.delenv("HANGAR_PROV_PORT", raising=False)
    monkeypatch.delenv("HANGAR_PROV_DB", raising=False)
    db = str(tmp_path / "prov.db")

    seen = {}

    def fake_start():
        seen["port"] = os.environ.get("HANGAR_PROV_PORT")
        seen["db"] = os.environ.get("HANGAR_PROV_DB")
        return None  # skip the blocking wait

    with patch.dict(os.environ), patch(
        "hangar.sdk.viz.viewer_server.start_viewer_server", side_effect=fake_start
    ):
        with pytest.raises(SystemExit):
            viewer_command(port=7991, db=db)

    assert seen == {"port": "7991", "db": db}


# ---------------------------------------------------------------------------
# interpolate_args
# ---------------------------------------------------------------------------


def test_interpolate_step_reference_resolves():
    from hangar.sdk.cli.runner import interpolate_args

    prev = [{"ok": True, "result": {"run_id": "run-abc"}}]
    out = interpolate_args({"run_id": "$1.run_id"}, prev)
    assert out["run_id"] == "run-abc"


def test_interpolate_prev_resolves_most_recent():
    from hangar.sdk.cli.runner import interpolate_args

    prev = [
        {"ok": True, "result": {"run_id": "run-old"}},
        {"ok": True, "result": {"status": "no run id here"}},
        {"ok": True, "result": {"run_id": "run-new"}},
    ]
    out = interpolate_args({"run_id": "$prev.run_id"}, prev)
    assert out["run_id"] == "run-new"


def test_interpolate_non_numeric_step_gets_clear_error():
    """A malformed step reference used to surface the raw int() parse
    error ('invalid literal for int() with base 10')."""
    from hangar.sdk.cli.runner import interpolate_args

    with pytest.raises(ValueError, match=r"\$N\.run_id.*'foo'"):
        interpolate_args({"run_id": "$foo.run_id"}, [])


def test_interpolate_out_of_range_step_errors():
    from hangar.sdk.cli.runner import interpolate_args

    with pytest.raises(ValueError, match="only 1 steps have completed"):
        interpolate_args(
            {"run_id": "$5.run_id"},
            [{"ok": True, "result": {"run_id": "run-abc"}}],
        )
