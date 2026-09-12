"""Shared fixtures for hangar-avy tests.

Isolates artifacts and provenance per-test, resets session state between
tests. Tests that need the aviary package guard with
``pytest.importorskip("aviary")`` -- aviary lives in the isolated .venv-avy
(see scripts/setup-avy-venv.sh), not the main workspace venv.
"""

import uuid

import pytest
import pytest_asyncio
from hangar.sdk.state import artifacts as _artifacts
from hangar.avy.tools.aircraft import load_aircraft_template
from hangar.avy.tools.session import reset


@pytest.fixture(autouse=True)
def isolate_artifacts(tmp_path):
    """Redirect artifact storage to a per-test temp directory."""
    original = _artifacts._data_dir
    _artifacts._data_dir = tmp_path / "artifacts"
    yield
    _artifacts._data_dir = original


@pytest.fixture(autouse=True)
def isolate_provenance(tmp_path):
    """Redirect provenance DB to a per-test temp file."""
    from hangar.sdk.provenance.middleware import _prov_session_id
    from hangar.sdk.provenance.db import init_db

    init_db(tmp_path / "prov.db")
    token = _prov_session_id.set(f"test-{uuid.uuid4().hex[:8]}")
    yield
    _prov_session_id.reset(token)


@pytest_asyncio.fixture(autouse=True)
async def clean_session(isolate_provenance):
    """Reset the global session before every test."""
    await reset()
    yield
    await reset()


@pytest_asyncio.fixture
async def single_aisle():
    """Load the default single-aisle template and return its name."""
    result = await load_aircraft_template(
        template="advanced_single_aisle", name="test_aircraft"
    )
    return result["aircraft_name"]
