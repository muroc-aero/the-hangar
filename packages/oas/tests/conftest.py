"""
Shared fixtures for hangar-oas tests.

Migrated from: OpenAeroStruct/oas_mcp/tests/conftest.py

The global session manager lives in hangar.oas.server, so we reset it between
tests via the reset() tool to keep tests isolated.

The global artifact store is redirected to a per-test tmp_path so that
tests never write to the real oas_data/ directory.
"""

import uuid

import pytest
import pytest_asyncio
from hangar.sdk.state import artifacts as _artifacts
from hangar.oas.server import create_surface, reset

# Surface definitions live in oas_surface_defs.py (unique module name);
# test modules import them from there, not from conftest.
from oas_surface_defs import (  # noqa: F401 -- re-export for fixtures below
    SMALL_RECT,
    SMALL_RECT_STRUCT,
    SMALL_RECT_WINGBOX,
    SMALL_TAIL,
    SMALL_TAIL_STRUCT,
)


@pytest.fixture(autouse=True)
def isolate_artifacts(tmp_path):
    """Redirect artifact storage to a per-test temp directory."""
    original = _artifacts._data_dir
    _artifacts._data_dir = tmp_path / "artifacts"
    yield
    _artifacts._data_dir = original


@pytest.fixture(autouse=True)
def isolate_provenance(tmp_path):
    """Redirect provenance DB to a per-test temp file and reset the session ID."""
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
async def aero_wing():
    """Create a small aero-only wing and return its name."""
    await create_surface(**SMALL_RECT)
    return "wing"


@pytest_asyncio.fixture
async def struct_wing():
    """Create a small wing with structural properties."""
    await create_surface(**SMALL_RECT_STRUCT)
    return "wing"


@pytest_asyncio.fixture
async def wingbox_wing():
    """Create a small wing with wingbox structural properties."""
    await create_surface(**SMALL_RECT_WINGBOX)
    return "wing"


@pytest_asyncio.fixture
async def wing_and_tail():
    """Create wing + tail aero-only surfaces for multi-surface tests."""
    await create_surface(**SMALL_RECT)
    await create_surface(**SMALL_TAIL)
    return ["wing", "tail"]


@pytest_asyncio.fixture
async def wing_and_tail_struct():
    """Create wing + tail with tube structural properties."""
    await create_surface(**SMALL_RECT_STRUCT)
    await create_surface(**SMALL_TAIL_STRUCT)
    return ["wing", "tail"]
