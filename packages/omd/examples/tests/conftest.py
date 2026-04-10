"""Fixtures for examples parity tests."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def isolate_omd_data(tmp_path, monkeypatch):
    """Redirect all omd data paths to per-test temp directory."""
    monkeypatch.setenv("OMD_DB_PATH", str(tmp_path / "analysis.db"))
    monkeypatch.setenv("OMD_PLAN_STORE", str(tmp_path / "plans"))
    monkeypatch.setenv("OMD_RECORDINGS_DIR", str(tmp_path / "recordings"))
    yield tmp_path


# Example package names whose `shared` modules differ between examples.
_EXAMPLE_PKGS = [
    "paraboloid", "oas_aero_rect", "oas_aerostruct_rect",
    "ocp_caravan_basic", "ocp_caravan_full", "ocp_hybrid_twin",
    "oas_ocp_combined", "ocp_oas_coupled", "ocp_oas_direct",
    "ocp_pyc_coupled", "pyc_turbojet", "ocp_three_tool",
]


@pytest.fixture(autouse=True)
def clean_shared_modules():
    """Purge cached 'shared' and example package modules between tests.

    Each example has its own shared.py with different exports.  Without
    cleanup, earlier tests pollute sys.path / sys.modules and later
    imports resolve against the wrong shared module.
    """
    yield
    for mod_name in list(sys.modules):
        if mod_name == "shared" or any(
            mod_name == pkg or mod_name.startswith(pkg + ".")
            for pkg in _EXAMPLE_PKGS
        ):
            del sys.modules[mod_name]
