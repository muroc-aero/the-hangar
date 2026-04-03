"""Shared fixtures for hangar-omd tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolate_db(tmp_path, monkeypatch):
    """Redirect analysis DB to per-test temp directory."""
    monkeypatch.setenv("OMD_DB_PATH", str(tmp_path / "analysis.db"))
    yield tmp_path


@pytest.fixture
def fixtures_dir():
    """Return the path to test fixture plan directories."""
    return FIXTURES_DIR
