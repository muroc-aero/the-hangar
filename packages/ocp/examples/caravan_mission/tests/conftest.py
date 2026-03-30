"""Fixtures for Caravan mission demonstration parity tests."""

import uuid

import pytest
import pytest_asyncio
from hangar.ocp.cli import build_ocp_registry
from hangar.sdk.cli.runner import set_registry_builder
from hangar.ocp.state import sessions as _sessions, artifacts as _artifacts

# Wire the OCP tool registry so run_tool() works in parity tests
set_registry_builder(build_ocp_registry)


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
    token = _prov_session_id.set(f"demo-{uuid.uuid4().hex[:8]}")
    yield
    _prov_session_id.reset(token)


@pytest_asyncio.fixture(autouse=True)
async def clean_session(isolate_provenance):
    """Reset global OCP session before every test."""
    from hangar.ocp.tools.session import reset
    await reset()
    yield
    await reset()
