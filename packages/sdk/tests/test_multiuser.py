"""Two-user isolation tests for the in-process identity seams.

On a shared HTTP server, per-request identity comes from the JWT via
``get_current_user()``. These tests interleave two identities through the
ContextVar that the token verifier sets and assert that the two stateful
registries never cross users:

- ``SessionManager``: the same short session name must resolve to a
  different ``Session`` per user, and ``reset()`` must only clear the
  calling user's sessions.
- The active provenance session: one user's ``start_session`` must not
  repoint where another user's tool calls are recorded.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from hangar.sdk.auth.oidc import _current_user_ctx
from hangar.sdk.provenance import middleware as mw
from hangar.sdk.session.manager import SessionManager


@contextmanager
def as_user(name: str):
    """Impersonate an authenticated user the way verify_token() does."""
    token = _current_user_ctx.set(name)
    try:
        yield
    finally:
        _current_user_ctx.reset(token)


@pytest.fixture(autouse=True)
def restore_prov_state():
    """Snapshot and restore the middleware's module-level session state."""
    saved_map = dict(mw._user_session_ids)
    saved_default = mw._default_session_id
    yield
    mw._user_session_ids.clear()
    mw._user_session_ids.update(saved_map)
    mw.set_default_session_id(saved_default)


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class TestSessionManagerIsolation:
    def test_same_name_resolves_per_user(self):
        manager = SessionManager()
        with as_user("alice"):
            alice_session = manager.get("default")
        with as_user("bob"):
            bob_session = manager.get("default")
        assert alice_session is not bob_session

    def test_state_does_not_cross_users(self):
        manager = SessionManager()
        with as_user("alice"):
            manager.get("default").surfaces["wing"] = {"name": "wing"}
            manager.get("default").requirements = [{"label": "alice-req"}]
        with as_user("bob"):
            session = manager.get("default")
            assert "wing" not in session.surfaces
            assert session.requirements == []

    def test_repeated_get_is_stable_within_user(self):
        manager = SessionManager()
        with as_user("alice"):
            first = manager.get("default")
            first.project = "alice-project"
            assert manager.get("default") is first

    def test_reset_clears_only_calling_user(self):
        manager = SessionManager()
        with as_user("alice"):
            manager.get("default").surfaces["wing"] = {"name": "wing"}
        with as_user("bob"):
            manager.get("default").surfaces["fuselage"] = {"name": "fuselage"}
            manager.reset()
            assert "fuselage" not in manager.get("default").surfaces
        with as_user("alice"):
            assert "wing" in manager.get("default").surfaces

    def test_stdio_fallback_single_user(self):
        """Without a JWT identity, the OS-user fallback keys consistently."""
        manager = SessionManager()
        session = manager.get("default")
        session.project = "local"
        assert manager.get("default") is session


# ---------------------------------------------------------------------------
# Active provenance session
# ---------------------------------------------------------------------------


class TestProvenanceSessionIsolation:
    def test_start_session_does_not_repoint_other_user(self):
        mw.set_default_session_id("auto-12345678")
        with as_user("alice"):
            mw.set_server_session_id("sess-alice")
            assert mw._get_session_id() == "sess-alice"
        # Bob never called start_session: he must land in the process
        # default, not in alice's session.
        with as_user("bob"):
            assert mw._get_session_id() == "auto-12345678"
            mw.set_server_session_id("sess-bob")
            assert mw._get_session_id() == "sess-bob"
        # Alice's active session survives bob's start_session.
        with as_user("alice"):
            assert mw._get_session_id() == "sess-alice"

    def test_active_session_sticks_across_requests(self):
        """A user's start_session persists beyond the request that set it."""
        with as_user("alice"):
            mw.set_server_session_id("sess-alice")
        # New "request" (fresh identity context) for the same user.
        with as_user("alice"):
            assert mw._get_session_id() == "sess-alice"

    def test_contextvar_override_wins(self):
        """The test-isolation ContextVar keeps priority over per-user state."""
        token = mw._prov_session_id.set("ctx-session")
        try:
            with as_user("alice"):
                mw.set_server_session_id("sess-alice")
                assert mw._get_session_id() == "ctx-session"
        finally:
            mw._prov_session_id.reset(token)
