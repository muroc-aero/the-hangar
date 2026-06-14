"""Parity test fixtures -- isolate artifacts and provenance, reset session."""

import uuid

import pytest
import pytest_asyncio
from hangar.sdk.state import artifacts as _artifacts
from hangar.evtol.tools.session import reset


@pytest.fixture(autouse=True)
def isolate_artifacts(tmp_path):
    original = _artifacts._data_dir
    _artifacts._data_dir = tmp_path / "artifacts"
    yield
    _artifacts._data_dir = original


@pytest.fixture(autouse=True)
def isolate_provenance(tmp_path):
    from hangar.sdk.provenance.middleware import _prov_session_id
    from hangar.sdk.provenance.db import init_db

    init_db(tmp_path / "prov.db")
    token = _prov_session_id.set(f"parity-{uuid.uuid4().hex[:8]}")
    yield
    _prov_session_id.reset(token)


@pytest_asyncio.fixture(autouse=True)
async def clean_session(isolate_provenance):
    await reset()
    yield
    await reset()
