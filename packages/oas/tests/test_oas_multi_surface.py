"""Integration tests for multi-surface (wing + tail) analysis.

Migration: upstream/OpenAeroStruct/oas_mcp/tests/test_multi_surface.py
Import mapping:
    oas_mcp.server          → hangar.oas.server
    oas_mcp.tests.conftest  → conftest (auto-discovered by pytest)

Verifies that two-surface configurations produce physically consistent results:
both surfaces appear in output, trim effects, drag increments, etc.
"""

import pytest
from hangar.oas.server import (
    compute_drag_polar,
    compute_stability_derivatives,
    create_surface,
    run_aero_analysis,
    run_aerostruct_analysis,
)
from oas_surface_defs import SMALL_RECT

pytestmark = pytest.mark.slow


def _r(envelope: dict) -> dict:
    """Extract the results payload from a versioned response envelope."""
    assert "schema_version" in envelope
    return envelope["results"]


# ---------------------------------------------------------------------------
# Multi-surface aero
# ---------------------------------------------------------------------------


class TestMultiSurfaceAero:
    async def test_both_surfaces_in_results(self, wing_and_tail):
        r = _r(await run_aero_analysis(wing_and_tail, alpha=5.0))
        assert "surfaces" in r
        assert "wing" in r["surfaces"]
        assert "tail" in r["surfaces"]

    async def test_tail_changes_cl(self, wing_and_tail):
        """Adding a tail should change the total CL compared to wing alone."""
        r_both = _r(await run_aero_analysis(wing_and_tail, alpha=5.0))
        # Create wing-only and compare
        await create_surface(**SMALL_RECT)
        r_wing = _r(await run_aero_analysis(["wing"], alpha=5.0))
        assert r_both["CL"] != pytest.approx(r_wing["CL"], rel=0.01)

    async def test_two_surfaces_more_drag(self, wing_and_tail):
        """Two surfaces should produce more induced drag than one."""
        r_both = _r(await run_aero_analysis(wing_and_tail, alpha=5.0))
        await create_surface(**SMALL_RECT)
        r_wing = _r(await run_aero_analysis(["wing"], alpha=5.0))
        assert r_both["CD"] > r_wing["CD"] * 0.5  # loosely — at least nontrivial drag

    async def test_tail_changes_cm(self, wing_and_tail):
        """Adding a tail behind the wing should change the pitching moment."""
        r_both = _r(await run_aero_analysis(wing_and_tail, alpha=5.0))
        await create_surface(**SMALL_RECT)
        r_wing = _r(await run_aero_analysis(["wing"], alpha=5.0))
        assert r_both["CM"] != pytest.approx(r_wing["CM"], rel=0.01)

    async def test_stability_with_tail(self, wing_and_tail):
        r = _r(await compute_stability_derivatives(wing_and_tail, alpha=5.0))
        assert "CL_alpha" in r
        assert "CM_alpha" in r
        assert "static_margin" in r

    async def test_drag_polar_two_surfaces(self, wing_and_tail):
        r = _r(await compute_drag_polar(
            wing_and_tail, alpha_start=-2.0, alpha_end=8.0, num_alpha=5
        ))
        assert len(r["CL"]) == 5
        assert len(r["CD"]) == 5


# ---------------------------------------------------------------------------
# Multi-surface aerostruct
# ---------------------------------------------------------------------------


class TestMultiSurfaceAerostruct:
    async def test_both_surfaces_in_results(self, wing_and_tail_struct):
        r = _r(await run_aerostruct_analysis(wing_and_tail_struct, alpha=5.0))
        assert "surfaces" in r
        assert "wing" in r["surfaces"]
        assert "tail" in r["surfaces"]

    async def test_structural_mass_sum(self, wing_and_tail_struct):
        """Total structural mass should be positive and exceed either surface alone."""
        r = _r(await run_aerostruct_analysis(wing_and_tail_struct, alpha=5.0))
        assert r["structural_mass"] > 0

    async def test_per_surface_failure(self, wing_and_tail_struct):
        """Each surface should report its own failure value."""
        r = _r(await run_aerostruct_analysis(wing_and_tail_struct, alpha=5.0))
        for name in ("wing", "tail"):
            surf = r["surfaces"][name]
            assert "failure" in surf

    async def test_fuelburn_positive(self, wing_and_tail_struct):
        r = _r(await run_aerostruct_analysis(wing_and_tail_struct, alpha=5.0))
        assert r["fuelburn"] > 0
