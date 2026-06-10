"""Integration tests for pyCycle MCP tools."""

import pytest

from hangar.pyc.tools.engine import create_engine
from hangar.pyc.tools.analysis import run_design_point, run_off_design
from hangar.pyc.tools.session import (
    delete_artifact,
    get_artifact,
    get_artifact_summary,
    list_artifacts,
    log_decision,
    reset,
    start_session,
)


# ---------------------------------------------------------------------------
# create_engine
# ---------------------------------------------------------------------------


class TestCreateEngine:
    async def test_create_turbojet(self):
        result = await create_engine(archetype="turbojet", name="tj1")
        assert result["engine_name"] == "tj1"
        assert result["archetype"] == "turbojet"
        assert "comp" in result["elements"]
        assert "turb" in result["elements"]

    async def test_create_with_custom_params(self):
        result = await create_engine(
            archetype="turbojet",
            name="tj2",
            comp_PR=15.0,
            comp_eff=0.85,
        )
        assert result["params"]["comp_PR"] == 15.0
        assert result["params"]["comp_eff"] == 0.85

    async def test_invalid_archetype(self):
        with pytest.raises(ValueError, match="Unknown archetype"):
            await create_engine(archetype="scramjet")

    async def test_invalid_thermo_method(self):
        with pytest.raises(ValueError, match="thermo_method"):
            await create_engine(archetype="turbojet", thermo_method="INVALID")


# ---------------------------------------------------------------------------
# run_design_point
# ---------------------------------------------------------------------------


class TestRunDesignPoint:
    @pytest.mark.slow
    async def test_design_point_basic(self, turbojet_engine):
        result = await run_design_point(
            engine_name=turbojet_engine,
            alt=0.0,
            MN=0.000001,
            Fn_target=11800.0,
            T4_target=2370.0,
        )
        # Check envelope structure
        assert result["schema_version"] == "1.0"
        assert "results" in result
        assert "validation" in result
        assert "run_id" in result

        # Check performance results
        perf = result["results"]["performance"]
        assert perf["Fn"] is not None
        assert perf["Fn"] > 0
        assert perf["TSFC"] is not None
        assert perf["TSFC"] > 0
        assert perf["OPR"] is not None

    @pytest.mark.slow
    async def test_design_point_validation_passes(self, turbojet_engine):
        result = await run_design_point(
            engine_name=turbojet_engine,
            alt=0.0,
            MN=0.000001,
            Fn_target=11800.0,
            T4_target=2370.0,
        )
        # Validation should pass for reasonable inputs
        validation = result["validation"]
        errors = [f for f in validation.get("findings", []) if f["severity"] == "error"]
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    async def test_design_point_no_engine(self):
        with pytest.raises(ValueError, match="not found"):
            await run_design_point(engine_name="nonexistent")

    async def test_invalid_flight_conditions(self, turbojet_engine):
        with pytest.raises(ValueError, match="Altitude"):
            await run_design_point(
                engine_name=turbojet_engine, alt=200000
            )

    async def test_invalid_thrust(self, turbojet_engine):
        with pytest.raises(ValueError, match="Fn_target"):
            await run_design_point(
                engine_name=turbojet_engine, Fn_target=-100
            )


# ---------------------------------------------------------------------------
# run_off_design
# ---------------------------------------------------------------------------


class TestRunOffDesign:
    @pytest.mark.slow
    async def test_off_design_basic(self, turbojet_engine):
        # Must design first
        await run_design_point(
            engine_name=turbojet_engine,
            alt=0.0,
            MN=0.000001,
            Fn_target=11800.0,
            T4_target=2370.0,
        )

        result = await run_off_design(
            engine_name=turbojet_engine,
            alt=0.0,
            MN=0.2,
            Fn_target=8000.0,
        )
        assert result["schema_version"] == "1.0"
        perf = result["results"]["performance"]
        assert perf["Fn"] is not None
        assert perf["TSFC"] is not None

    async def test_off_design_before_design(self, turbojet_engine):
        with pytest.raises(ValueError, match="not been sized"):
            await run_off_design(engine_name=turbojet_engine)


# ---------------------------------------------------------------------------
# Session / provenance tools
# ---------------------------------------------------------------------------


class TestSessionTools:
    async def test_start_session(self):
        result = await start_session(notes="test session")
        assert "session_id" in result
        assert result["joined"] is False

    async def test_log_decision(self):
        await start_session()
        result = await log_decision(
            decision_type="archetype_selection",
            reasoning="Turbojet for simplicity",
            selected_action="archetype=turbojet",
        )
        assert "decision_id" in result

    @pytest.mark.slow
    async def test_artifacts_saved(self, turbojet_engine):
        await run_design_point(
            engine_name=turbojet_engine,
            alt=0.0,
            MN=0.000001,
            Fn_target=11800.0,
            T4_target=2370.0,
        )
        arts = await list_artifacts()
        assert arts["count"] >= 1
        # Artifacts live under the tool-container session_id, not the
        # provenance session id; oas/ocp do the same and cross-tool artifact
        # lookups rely on it.
        assert arts["artifacts"][0]["session_id"] == "default"


class TestArtifactScoping:
    """Artifact tools must be scoped to the authenticated user."""

    @pytest.fixture
    def two_user_artifacts(self):
        from hangar.sdk.auth import get_current_user
        from hangar.sdk.state import artifacts as _artifacts

        def save(user):
            return _artifacts.save(
                session_id="default",
                analysis_type="design",
                tool_name="run_design_point",
                surfaces=["engine"],
                parameters={"alt": 0.0},
                results={"performance": {"TSFC": 0.8}},
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
        assert artifact["results"]["performance"]["TSFC"] == 0.8

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
        from hangar.sdk.state import artifacts as _artifacts

        with pytest.raises(ValueError, match="not found"):
            await delete_artifact(two_user_artifacts["theirs"])
        # Still on disk under the other user
        assert _artifacts.get(two_user_artifacts["theirs"], user="someone-else") is not None

    async def test_reset_clears_engines(self, turbojet_engine):
        await reset()
        with pytest.raises(ValueError, match="not found"):
            await run_design_point(engine_name=turbojet_engine)


# ---------------------------------------------------------------------------
# Typed session state
# ---------------------------------------------------------------------------


class TestTypedSessionState:
    async def test_session_is_pyc_session_with_engines_field(self):
        from hangar.pyc.state import PycSession, sessions

        await create_engine(archetype="turbojet", name="typed1")
        session = sessions.get("default")
        assert isinstance(session, PycSession)
        assert "typed1" in session.engines
        # No live OpenMDAO problem is stored in the engine config
        assert "design_prob" not in session.engines["typed1"]

    async def test_clear_resets_engines(self):
        from hangar.pyc.state import sessions

        await create_engine(archetype="turbojet", name="typed2")
        session = sessions.get("default")
        session.clear()
        assert session.engines == {}
