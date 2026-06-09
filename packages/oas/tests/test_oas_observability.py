"""Integration tests for observability tools: get_run, pin_run, unpin_run,
get_detailed_results, get_last_logs, configure_session, set_requirements.

Migration: upstream/OpenAeroStruct/oas_mcp/tests/test_observability.py
Import mapping:
    oas_mcp.server → hangar.oas.server
    oas_mcp.tests.conftest → conftest (auto-discovered by pytest)
"""

import pytest
from hangar.oas.server import (
    configure_session,
    create_surface,
    get_detailed_results,
    get_last_logs,
    get_run,
    pin_run,
    run_aero_analysis,
    run_aerostruct_analysis,
    set_requirements,
    unpin_run,
)
from oas_surface_defs import SMALL_RECT, SMALL_RECT_STRUCT

pytestmark = pytest.mark.slow


def _r(envelope: dict) -> dict:
    """Extract the results payload from a versioned response envelope."""
    assert "schema_version" in envelope, f"Not an envelope: {list(envelope)}"
    assert "results" in envelope, f"Envelope missing 'results': {list(envelope)}"
    return envelope["results"]


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------


class TestGetRun:
    async def test_manifest_has_required_keys(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        run_id = env["run_id"]
        manifest = await get_run(run_id)
        for key in (
            "run_id", "tool_name", "analysis_type", "surfaces",
            "inputs", "outputs_summary", "cache_state",
            "detail_levels_available", "available_plots",
        ):
            assert key in manifest, f"Missing key: {key}"

    async def test_cache_state_shows_cached(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        manifest = await get_run(env["run_id"])
        assert manifest["cache_state"]["cached"] is True

    async def test_pinned_false_by_default(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        manifest = await get_run(env["run_id"])
        assert manifest["cache_state"]["pinned"] is False

    async def test_available_plots_aero(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        manifest = await get_run(env["run_id"])
        assert "lift_distribution" in manifest["available_plots"]

    async def test_available_plots_aerostruct(self, struct_wing):
        env = await run_aerostruct_analysis(["wing"], alpha=5.0)
        manifest = await get_run(env["run_id"])
        plots = manifest["available_plots"]
        assert "lift_distribution" in plots
        assert "stress_distribution" in plots

    async def test_nonexistent_run_raises(self):
        with pytest.raises(ValueError, match="not found"):
            await get_run("bogus-run-id")

    async def test_analysis_type_correct(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        manifest = await get_run(env["run_id"])
        assert manifest["analysis_type"] == "aero"


# ---------------------------------------------------------------------------
# pin_run / unpin_run
# ---------------------------------------------------------------------------


class TestPinUnpin:
    async def test_pin_returns_pinned_true(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        result = await pin_run(env["run_id"], ["wing"], "aero")
        assert result["pinned"] is True

    async def test_pin_no_cache_returns_false(self):
        result = await pin_run("nonexistent-run", ["wing"], "aero")
        assert result["pinned"] is False

    async def test_unpin_releases(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        await pin_run(env["run_id"], ["wing"], "aero")
        result = await unpin_run(env["run_id"])
        assert result["released"] is True

    async def test_unpin_without_pin_returns_false(self):
        result = await unpin_run("never-pinned")
        assert result["released"] is False

    async def test_pinned_survives_surface_change(self, aero_wing):
        """A pinned cache entry should NOT be evicted when a surface is re-created."""
        env = await run_aero_analysis(["wing"], alpha=5.0)
        run_id = env["run_id"]
        await pin_run(run_id, ["wing"], "aero")

        # Re-create the surface with a different span — would normally evict cache
        await create_surface(**{**SMALL_RECT, "span": 20.0})

        # get_run should still report pinned
        manifest = await get_run(run_id)
        assert manifest["cache_state"]["pinned"] is True

    async def test_unpinned_evicted_on_surface_change(self, aero_wing):
        """Without pinning, re-creating a surface should evict the cache."""
        env = await run_aero_analysis(["wing"], alpha=5.0)
        run_id = env["run_id"]

        # Re-create with different span — cache should be gone
        await create_surface(**{**SMALL_RECT, "span": 20.0})

        manifest = await get_run(run_id)
        assert manifest["cache_state"]["cached"] is False


# ---------------------------------------------------------------------------
# get_detailed_results
# ---------------------------------------------------------------------------


class TestGetDetailedResults:
    async def test_standard_has_sectional_data(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        detail = await get_detailed_results(env["run_id"], detail_level="standard")
        assert detail["detail_level"] == "standard"
        assert "sectional_data" in detail

    async def test_summary_returns_scalars_only(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        detail = await get_detailed_results(env["run_id"], detail_level="summary")
        assert detail["detail_level"] == "summary"
        assert "results" in detail

    async def test_invalid_detail_level_raises(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        with pytest.raises(ValueError, match="Unknown detail_level"):
            await get_detailed_results(env["run_id"], detail_level="full")

    async def test_aerostruct_standard_has_stress(self, struct_wing):
        env = await run_aerostruct_analysis(["wing"], alpha=5.0)
        detail = await get_detailed_results(env["run_id"], detail_level="standard")
        # Sectional data should include von Mises stress for structural surfaces
        sect = detail.get("sectional_data", {})
        assert "wing" in sect
        assert "vonmises_MPa" in sect["wing"]

    async def test_nonexistent_run_raises(self):
        with pytest.raises(ValueError, match="not found"):
            await get_detailed_results("bogus-run-id")


# ---------------------------------------------------------------------------
# get_last_logs
# ---------------------------------------------------------------------------


class TestGetLastLogs:
    async def test_logs_after_aero_run(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        result = await get_last_logs(env["run_id"])
        assert "run_id" in result
        assert "log_count" in result
        assert isinstance(result["logs"], list)
        assert result["log_count"] == len(result["logs"])

    async def test_logs_empty_for_unknown_run(self):
        result = await get_last_logs("bogus-run-id")
        assert result["logs"] == []
        assert result["log_count"] == 0

    async def test_log_count_matches_length(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        result = await get_last_logs(env["run_id"])
        assert result["log_count"] == len(result["logs"])


# ---------------------------------------------------------------------------
# configure_session
# ---------------------------------------------------------------------------


class TestConfigureSession:
    async def test_configure_detail_level(self):
        result = await configure_session(default_detail_level="standard")
        assert result["status"] == "configured"
        assert result["current_defaults"]["default_detail_level"] == "standard"

    async def test_configure_validation_threshold(self):
        result = await configure_session(validation_severity_threshold="error")
        assert result["current_defaults"]["validation_severity_threshold"] == "error"

    async def test_configure_project(self):
        result = await configure_session(project="my_project")
        assert result["project"] == "my_project"

    async def test_configure_visualization_output(self):
        result = await configure_session(visualization_output="file")
        assert result["current_defaults"]["visualization_output"] == "file"

    async def test_configure_invalid_detail_level_raises(self):
        with pytest.raises(ValueError, match="must be"):
            await configure_session(default_detail_level="bogus")


# ---------------------------------------------------------------------------
# set_requirements
# ---------------------------------------------------------------------------


class TestSetRequirements:
    async def test_requirements_set_count(self):
        reqs = [
            {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
            {"path": "CD", "operator": "<", "value": 1.0, "label": "max_CD"},
        ]
        result = await set_requirements(reqs)
        assert result["requirements_set"] == 2

    async def test_requirements_checked_on_analysis(self, aero_wing):
        """Set a requirement that CL >= 0.5, then run at alpha=0 where CL is near zero.
        The validation block should flag the failed requirement."""
        reqs = [{"path": "CL", "operator": ">=", "value": 0.5, "label": "min_CL"}]
        await set_requirements(reqs)

        env = await run_aero_analysis(["wing"], alpha=0.0)
        validation = env.get("validation", {})
        # The validation should report a finding for the failed requirement
        findings = validation.get("findings", [])
        failed = [f for f in findings if f.get("check_id", "").startswith("requirement")]
        assert len(failed) > 0, "Expected a failed requirement finding"
        assert any("min_CL" in f.get("message", "") for f in failed)
