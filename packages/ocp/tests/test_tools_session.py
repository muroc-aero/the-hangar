"""Tests for ocp session/artifact tools.

Mirrors the pyc artifact-scoping suite: the artifact tools must be scoped
to the authenticated user on shared deployments.
"""

import pytest

from hangar.ocp.state import artifacts as _artifacts, sessions
from hangar.ocp.tools.session import (
    delete_artifact,
    get_artifact,
    get_artifact_summary,
    list_artifacts,
)


@pytest.fixture(autouse=True)
def isolate_artifacts(tmp_path):
    """Redirect artifact storage to a per-test temp directory."""
    original = _artifacts._data_dir
    _artifacts._data_dir = tmp_path / "artifacts"
    yield
    _artifacts._data_dir = original


@pytest.fixture(autouse=True)
def reset_sessions():
    sessions.reset()
    yield
    sessions.reset()


class TestArtifactScoping:
    """Artifact tools must be scoped to the authenticated user."""

    @pytest.fixture
    def two_user_artifacts(self):
        from hangar.sdk.auth import get_current_user

        def save(user):
            return _artifacts.save(
                session_id="default",
                analysis_type="mission",
                tool_name="run_mission_analysis",
                surfaces=["caravan"],
                parameters={"mission_range_NM": 300},
                results={"fuel_burn_kg": 120.0},
                user=user,
            )

        return {
            "mine": save(get_current_user()),
            "theirs": save("someone-else"),
        }

    async def test_list_excludes_other_users(self, two_user_artifacts):
        arts = await list_artifacts()
        run_ids = {a["run_id"] for a in arts["artifacts"]}
        assert two_user_artifacts["mine"] in run_ids
        assert two_user_artifacts["theirs"] not in run_ids

    async def test_get_own_artifact(self, two_user_artifacts):
        artifact = await get_artifact(two_user_artifacts["mine"])
        assert artifact["results"]["fuel_burn_kg"] == 120.0

    async def test_get_other_users_artifact_denied(self, two_user_artifacts):
        with pytest.raises(ValueError, match="not found"):
            await get_artifact(two_user_artifacts["theirs"])

    async def test_summary_own_artifact(self, two_user_artifacts):
        summary = await get_artifact_summary(two_user_artifacts["mine"])
        assert summary["run_id"] == two_user_artifacts["mine"]

    async def test_summary_other_users_artifact_denied(self, two_user_artifacts):
        with pytest.raises(ValueError, match="not found"):
            await get_artifact_summary(two_user_artifacts["theirs"])

    async def test_delete_own_artifact(self, two_user_artifacts):
        result = await delete_artifact(two_user_artifacts["mine"])
        assert result["status"] == "deleted"

    async def test_delete_other_users_artifact_denied(self, two_user_artifacts):
        with pytest.raises(ValueError, match="not found"):
            await delete_artifact(two_user_artifacts["theirs"])
        # Still on disk under the other user.
        assert (
            _artifacts.get(two_user_artifacts["theirs"], user="someone-else")
            is not None
        )
