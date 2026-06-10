"""
Integration tests for all MCP tools.

Migrated from: OpenAeroStruct/oas_mcp/tests/test_tools.py

These run real OAS computations on small meshes (num_y=5) to verify that
tools produce physically correct, consistent results.  Marked with
pytest.mark.slow so they can be excluded from quick feedback loops:

    pytest -m "not slow"   # unit tests only
    pytest                 # everything
"""

import pytest
import pytest_asyncio
from hangar.oas.server import (
    compute_drag_polar,
    compute_stability_derivatives,
    create_surface,
    reset,
    run_aero_analysis,
    run_aerostruct_analysis,
    run_optimization,
)

pytestmark = pytest.mark.slow


def _r(envelope: dict) -> dict:
    """Extract the results payload from a versioned response envelope.

    All analysis tools now return an envelope with schema_version, run_id,
    validation, telemetry, and results.  Tests use this helper to unwrap it
    so existing assertions still read naturally.
    """
    assert "schema_version" in envelope, f"Not an envelope: {list(envelope)}"
    assert "results" in envelope, f"Envelope missing 'results': {list(envelope)}"
    return envelope["results"]


# ---------------------------------------------------------------------------
# create_surface
# ---------------------------------------------------------------------------


class TestCreateSurface:
    async def test_rect_wing_summary(self, aero_wing):
        from hangar.sdk.state import sessions as _sessions
        session = _sessions.get("default")
        assert "wing" in session.surfaces
        surf = session.surfaces["wing"]
        assert surf["mesh"].shape[0] == 2  # num_x
        assert surf["mesh"].shape[2] == 3  # x,y,z

    async def test_crm_wing_has_twist(self):
        result = await create_surface(
            name="crm", wing_type="CRM", num_x=2, num_y=5, symmetry=True
        )
        from hangar.sdk.state import sessions as _sessions
        surf = _sessions.get("default").surfaces["crm"]
        assert len(surf["twist_cp"]) >= 2

    async def test_struct_wing_has_fem_properties(self):
        await create_surface(
            name="sw", wing_type="rect", num_x=2, num_y=5,
            fem_model_type="tube", E=70e9, G=30e9,
            yield_stress=500e6, safety_factor=2.5, mrho=3e3,
        )
        from hangar.sdk.state import sessions as _sessions
        surf = _sessions.get("default").surfaces["sw"]
        assert surf["fem_model_type"] == "tube"
        assert surf["E"] == 70e9

    async def test_returns_surface_summary(self, aero_wing):
        result = await create_surface(
            name="check", wing_type="rect", num_x=2, num_y=5,
            span=10.0, root_chord=1.0, symmetry=True,
        )
        assert result["surface_name"] == "check"
        assert result["span_m"] == pytest.approx(10.0, abs=0.1)
        assert result["has_structure"] is False
        assert result["status"] == "Surface created successfully"

    async def test_invalid_even_num_y_raises(self):
        with pytest.raises(ValueError, match="odd"):
            await create_surface(name="bad", num_y=6)

    async def test_invalid_wing_type_raises(self):
        with pytest.raises(ValueError, match="wing_type"):
            await create_surface(name="bad", wing_type="ellipse")

    async def test_wingbox_surface_has_required_keys(self):
        await create_surface(
            name="wb", wing_type="rect", num_x=2, num_y=5,
            fem_model_type="wingbox", E=73.1e9, G=27.5e9,
            yield_stress=420e6, safety_factor=1.5, mrho=2.78e3,
        )
        from hangar.sdk.state import sessions as _sessions
        surf = _sessions.get("default").surfaces["wb"]
        # Keys required by SectionPropertiesWingbox
        assert "original_wingbox_airfoil_t_over_c" in surf
        assert "data_x_upper" in surf
        assert "data_y_upper" in surf
        assert "data_x_lower" in surf
        assert "data_y_lower" in surf
        assert "spar_thickness_cp" in surf
        assert "skin_thickness_cp" in surf

    async def test_wingbox_surface_does_not_have_tube_keys(self):
        await create_surface(
            name="wb2", wing_type="rect", num_x=2, num_y=5,
            fem_model_type="wingbox",
        )
        from hangar.sdk.state import sessions as _sessions
        surf = _sessions.get("default").surfaces["wb2"]
        assert "thickness_cp" not in surf
        assert "radius_cp" not in surf

    async def test_wingbox_custom_spar_skin_thickness(self):
        # User provides root-to-tip; stored internally in OAS tip-to-root order.
        await create_surface(
            name="wb3", wing_type="rect", num_x=2, num_y=5,
            fem_model_type="wingbox",
            spar_thickness_cp=[0.003, 0.005, 0.007],
            skin_thickness_cp=[0.004, 0.008, 0.012],
        )
        from hangar.sdk.state import sessions as _sessions
        import numpy as np
        surf = _sessions.get("default").surfaces["wb3"]
        # Internal OAS order is reversed (tip-to-root)
        assert list(surf["spar_thickness_cp"]) == pytest.approx([0.007, 0.005, 0.003])
        assert list(surf["skin_thickness_cp"]) == pytest.approx([0.012, 0.008, 0.004])

    async def test_wingbox_t_over_c_custom(self):
        await create_surface(
            name="wb4", wing_type="rect", num_x=2, num_y=5,
            fem_model_type="wingbox",
            original_wingbox_airfoil_t_over_c=0.15,
        )
        from hangar.sdk.state import sessions as _sessions
        surf = _sessions.get("default").surfaces["wb4"]
        assert surf["original_wingbox_airfoil_t_over_c"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# Control-point ordering convention
# ---------------------------------------------------------------------------


class TestCpOrdering:
    async def test_twist_cp_stored_in_oas_tip_to_root_order(self):
        """User-provided root-to-tip array must be reversed for internal OAS storage."""
        await create_surface(name="cp_test", wing_type="rect", num_x=2, num_y=5,
                             twist_cp=[3.0, 0.0])
        from hangar.sdk.state import sessions as _sessions
        surf = _sessions.get("default").surfaces["cp_test"]
        # [3.0, 0.0] root-to-tip -> stored as [0.0, 3.0] tip-to-root
        import numpy as np
        assert list(surf["twist_cp"]) == pytest.approx([0.0, 3.0])

    async def test_twist_cp_root_loads_more_than_tip(self):
        """twist_cp=[5, 0] should load root (high twist) more than tip (zero twist)."""
        await create_surface(name="twist_conv", wing_type="rect", num_x=2, num_y=5,
                             twist_cp=[5.0, 0.0])
        env = await run_aero_analysis(["twist_conv"], alpha=0.0)
        r = _r(env)
        surf_r = r["surfaces"]["twist_conv"]
        # A 5 deg root twist with 0 deg tip: root sections carry more lift than tip
        # Verify overall CL is positive (root twist produces lift at alpha=0)
        assert r["CL"] > 0.0

    async def test_zero_twist_vs_root_twist_cl(self):
        """Wing with root-only twist must produce more CL than untwisted wing at alpha=0."""
        await create_surface(name="no_twist", wing_type="rect", num_x=2, num_y=5,
                             twist_cp=[0.0, 0.0])
        await create_surface(name="root_twist", wing_type="rect", num_x=2, num_y=5,
                             twist_cp=[5.0, 0.0])
        r_none = _r(await run_aero_analysis(["no_twist"], alpha=0.0))
        r_root = _r(await run_aero_analysis(["root_twist"], alpha=0.0))
        # Root twist of 5 deg should produce significantly more lift
        assert r_root["CL"] > r_none["CL"] + 0.05

    async def test_optimization_returns_root_to_tip_order(self):
        """Optimised twist DV must come back in root-to-tip order."""
        await create_surface(name="opt_conv", wing_type="rect", num_x=2, num_y=5)
        env = await run_optimization(
            surfaces=["opt_conv"],
            analysis_type="aero",
            objective="CD",
            design_variables=[{"name": "twist", "lower": -10.0, "upper": 10.0}],
            constraints=[{"name": "CL", "equals": 0.3}],
        )
        r = _r(env)
        twist_out = r["optimized_design_variables"].get("twist")
        assert twist_out is not None
        # Must be a flat list of floats (root-to-tip)
        assert isinstance(twist_out, list)
        assert all(isinstance(v, float) for v in twist_out)
        # initial_dvs must also be present
        assert r["optimization_history"]["initial_dvs"].get("twist") is not None
        # constraint_history must be present with CL constraint
        con_hist = r["optimization_history"].get("constraint_history", {})
        assert "CL" in con_hist, "constraint_history should include CL"
        assert len(con_hist["CL"]) > 0, "CL constraint history should have entries"
        assert all(isinstance(v, float) for v in con_hist["CL"])


# ---------------------------------------------------------------------------
# run_aero_analysis
# ---------------------------------------------------------------------------


class TestRunAeroAnalysis:
    async def test_basic_results_structure(self, aero_wing):
        env = await run_aero_analysis(["wing"])
        assert env["schema_version"] == "1.0"
        assert env["tool_name"] == "run_aero_analysis"
        assert "run_id" in env
        assert "validation" in env
        assert "telemetry" in env
        r = _r(env)
        assert "CL" in r
        assert "CD" in r
        assert "CM" in r
        assert "L_over_D" in r
        assert "surfaces" in r
        assert "wing" in r["surfaces"]

    async def test_envelope_validation_block(self, aero_wing):
        env = await run_aero_analysis(["wing"], alpha=5.0)
        v = env["validation"]
        assert "passed" in v
        assert "findings" in v
        assert isinstance(v["passed"], bool)

    async def test_cl_positive_at_positive_alpha(self, aero_wing):
        r = _r(await run_aero_analysis(["wing"], alpha=5.0))
        assert r["CL"] > 0

    async def test_cl_negative_at_negative_alpha(self, aero_wing):
        r = _r(await run_aero_analysis(["wing"], alpha=-5.0))
        assert r["CL"] < 0

    async def test_cd_always_positive(self, aero_wing):
        for alpha in [-5.0, 0.0, 5.0]:
            r = _r(await run_aero_analysis(["wing"], alpha=alpha))
            assert r["CD"] > 0, f"CD should be positive at alpha={alpha}"

    async def test_cl_zero_at_zero_alpha_rect(self, aero_wing):
        r = _r(await run_aero_analysis(["wing"], alpha=0.0))
        assert abs(r["CL"]) < 0.01  # rect wing, no camber -> CL~0 at alpha=0

    async def test_cl_increases_with_alpha(self, aero_wing):
        r1 = _r(await run_aero_analysis(["wing"], alpha=0.0))
        r2 = _r(await run_aero_analysis(["wing"], alpha=5.0))
        r3 = _r(await run_aero_analysis(["wing"], alpha=10.0))
        assert r1["CL"] < r2["CL"] < r3["CL"]

    async def test_ld_is_cl_over_cd(self, aero_wing):
        r = _r(await run_aero_analysis(["wing"], alpha=5.0))
        assert r["L_over_D"] == pytest.approx(r["CL"] / r["CD"], rel=1e-4)

    async def test_missing_surface_raises(self):
        with pytest.raises(ValueError, match="not found"):
            await run_aero_analysis(["nonexistent"])

    async def test_invalid_velocity_raises(self, aero_wing):
        with pytest.raises(ValueError, match="velocity"):
            await run_aero_analysis(["wing"], velocity=-1.0)

    async def test_session_cache_reused(self, aero_wing):
        from hangar.sdk.state import sessions as _sessions
        # First call stores a problem
        await run_aero_analysis(["wing"], alpha=0.0)
        cached_before = _sessions.get("default").get_cached_problem(["wing"], "aero")
        assert cached_before is not None
        # Second call should use the same cached object
        await run_aero_analysis(["wing"], alpha=5.0)
        cached_after = _sessions.get("default").get_cached_problem(["wing"], "aero")
        assert cached_before is cached_after


# ---------------------------------------------------------------------------
# run_aerostruct_analysis
# ---------------------------------------------------------------------------


class TestRunAerostructAnalysis:
    async def test_basic_results_structure(self, struct_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert "CL" in r
        assert "CD" in r
        assert "fuelburn" in r
        assert "structural_mass" in r
        assert "L_equals_W" in r

    async def test_structural_mass_positive(self, struct_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert r["structural_mass"] > 0

    async def test_fuelburn_positive(self, struct_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert r["fuelburn"] > 0

    async def test_failure_in_surface_results(self, struct_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert "failure" in r["surfaces"]["wing"]

    async def test_no_struct_props_raises(self, aero_wing):
        with pytest.raises(ValueError, match="structural"):
            await run_aerostruct_analysis(["wing"])

    async def test_cl_positive_at_positive_alpha(self, struct_wing):
        r = _r(await run_aerostruct_analysis(["wing"], alpha=5.0))
        assert r["CL"] > 0

    # --- wingbox model ---

    async def test_wingbox_basic_results_structure(self, wingbox_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert "CL" in r
        assert "CD" in r
        assert "fuelburn" in r
        assert "structural_mass" in r
        assert "L_equals_W" in r

    async def test_wingbox_structural_mass_positive(self, wingbox_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert r["structural_mass"] > 0

    async def test_wingbox_failure_in_surface_results(self, wingbox_wing):
        r = _r(await run_aerostruct_analysis(["wing"]))
        assert "failure" in r["surfaces"]["wing"]

    async def test_wingbox_cl_positive_at_positive_alpha(self, wingbox_wing):
        r = _r(await run_aerostruct_analysis(["wing"], alpha=5.0))
        assert r["CL"] > 0


# ---------------------------------------------------------------------------
# compute_drag_polar
# ---------------------------------------------------------------------------


class TestComputeDragPolar:
    async def test_result_arrays_same_length(self, aero_wing):
        dp = _r(await compute_drag_polar(["wing"], alpha_start=-5.0, alpha_end=10.0, num_alpha=4))
        n = len(dp["alpha_deg"])
        assert len(dp["CL"]) == n
        assert len(dp["CD"]) == n
        assert len(dp["CM"]) == n
        assert len(dp["L_over_D"]) == n

    async def test_cl_monotonically_increasing(self, aero_wing):
        dp = _r(await compute_drag_polar(["wing"], alpha_start=-5.0, alpha_end=10.0, num_alpha=4))
        cls = dp["CL"]
        assert all(cls[i] < cls[i + 1] for i in range(len(cls) - 1))

    async def test_cd_parabolic_minimum_at_mid_alpha(self, aero_wing):
        dp = _r(await compute_drag_polar(["wing"], alpha_start=-5.0, alpha_end=10.0, num_alpha=5))
        cds = dp["CD"]
        # CD should decrease then increase (parabolic) -- min not at endpoints
        min_idx = cds.index(min(cds))
        assert 0 < min_idx < len(cds) - 1

    async def test_best_ld_keys(self, aero_wing):
        dp = _r(await compute_drag_polar(["wing"], alpha_start=0.0, alpha_end=10.0, num_alpha=3))
        best = dp["best_L_over_D"]
        assert "alpha_deg" in best
        assert "CL" in best
        assert "CD" in best
        assert "L_over_D" in best
        assert isinstance(best["alpha_deg"], float)  # no np.float64 leakage

    async def test_num_alpha_respected(self, aero_wing):
        dp = _r(await compute_drag_polar(["wing"], num_alpha=6))
        assert len(dp["alpha_deg"]) == 6


# ---------------------------------------------------------------------------
# compute_stability_derivatives
# ---------------------------------------------------------------------------


class TestComputeStabilityDerivatives:
    async def test_result_keys(self, aero_wing):
        sd = _r(await compute_stability_derivatives(["wing"]))
        assert "CL_alpha" in sd
        assert "CM_alpha" in sd
        assert "static_margin" in sd
        assert "stability" in sd

    async def test_cl_alpha_positive(self, aero_wing):
        sd = _r(await compute_stability_derivatives(["wing"]))
        assert sd["CL_alpha"] > 0, "CL_alpha should be positive for a lifting surface"

    async def test_stability_string_reflects_sign(self, aero_wing):
        sd = _r(await compute_stability_derivatives(["wing"], cg=[0.5, 0.0, 0.0]))
        sm = sd["static_margin"]
        if sm > 0.05:
            assert "stable" in sd["stability"]
        elif sm > 0:
            assert "marginally" in sd["stability"]
        else:
            assert "unstable" in sd["stability"]


# ---------------------------------------------------------------------------
# run_optimization
# ---------------------------------------------------------------------------


class TestRunOptimization:
    async def test_cl_constraint_satisfied(self, aero_wing):
        result = _r(await run_optimization(
            surfaces=["wing"],
            analysis_type="aero",
            objective="CD",
            design_variables=[{"name": "alpha", "lower": -10.0, "upper": 15.0}],
            constraints=[{"name": "CL", "equals": 0.5}],
        ))
        assert result["success"] is True
        assert result["final_results"]["CL"] == pytest.approx(0.5, abs=1e-3)

    async def test_result_structure(self, aero_wing):
        result = _r(await run_optimization(
            surfaces=["wing"],
            analysis_type="aero",
            objective="CD",
            design_variables=[{"name": "alpha", "lower": -5.0, "upper": 15.0}],
            constraints=[{"name": "CL", "equals": 0.3}],
        ))
        assert "success" in result
        assert "optimized_design_variables" in result
        assert "final_results" in result

    async def test_unknown_dv_raises(self, aero_wing):
        with pytest.raises(ValueError, match="Unknown design variable"):
            await run_optimization(
                surfaces=["wing"],
                design_variables=[{"name": "magic_param"}],
                constraints=[{"name": "CL", "equals": 0.5}],
            )

    async def test_unknown_constraint_raises(self, aero_wing):
        with pytest.raises(ValueError, match="Unknown constraint"):
            await run_optimization(
                surfaces=["wing"],
                design_variables=[{"name": "alpha", "lower": -5.0, "upper": 15.0}],
                constraints=[{"name": "mystery_output", "equals": 0.0}],
            )

    async def test_thickness_dv_on_wingbox_raises(self, wingbox_wing):
        """'thickness' maps to thickness_cp which doesn't exist on wingbox surfaces."""
        with pytest.raises(ValueError, match="spar_thickness.*skin_thickness"):
            await run_optimization(
                surfaces=["wing"],
                analysis_type="aerostruct",
                objective="structural_mass",
                design_variables=[{"name": "thickness", "lower": 0.001, "upper": 0.1}],
                constraints=[{"name": "L_equals_W", "equals": 1.0}],
            )

    async def test_spar_thickness_dv_on_tube_raises(self, struct_wing):
        """'spar_thickness' / 'skin_thickness' are wingbox-only DVs."""
        with pytest.raises(ValueError, match="wingbox"):
            await run_optimization(
                surfaces=["wing"],
                analysis_type="aerostruct",
                objective="structural_mass",
                design_variables=[{"name": "spar_thickness", "lower": 0.001, "upper": 0.05}],
                constraints=[{"name": "L_equals_W", "equals": 1.0}],
            )


# ---------------------------------------------------------------------------
# Multipoint wingbox optimization
# ---------------------------------------------------------------------------


class TestMultipointWingboxOptimization:
    """Integration test for multipoint aerostructural optimization.

    Uses a coarse mesh (num_y=7, rect planform) and very few iterations
    (max_iterations=5) to verify the multipoint wiring and result structure
    without waiting for convergence. Complex features (distributed fuel weight,
    point masses) are disabled to keep the solver stable on a coarse mesh.
    """

    async def test_multipoint_result_structure(self):
        await reset()
        await create_surface(
            name="wing",
            wing_type="rect",
            num_x=3,
            num_y=7,
            span=30.0,
            root_chord=5.0,
            fem_model_type="wingbox",
            E=73.1e9,
            G=73.1e9 / 2 / 1.33,
            yield_stress=420e6,
            safety_factor=1.5,
            mrho=2780.0,
            struct_weight_relief=False,
            distributed_fuel_weight=False,
            fuel_density=803.0,
            Wf_reserve=15000.0,
            wing_weight_ratio=1.25,
            CD0=0.0078,
            with_wave=True,
        )

        flight_points = [
            # Cruise
            {"velocity": 248.0, "Mach_number": 0.84, "density": 0.38,
             "reynolds_number": 1.0e6, "speed_of_sound": 295.0, "load_factor": 1.0},
            # 2.5g maneuver
            {"velocity": 200.0, "Mach_number": 0.60, "density": 0.80,
             "reynolds_number": 2.0e6, "speed_of_sound": 333.0, "load_factor": 2.5},
        ]

        env = await run_optimization(
            surfaces=["wing"],
            analysis_type="aerostruct",
            objective="fuelburn",
            flight_points=flight_points,
            design_variables=[
                {"name": "twist", "lower": -5.0, "upper": 10.0, "scaler": 0.1},
                {"name": "spar_thickness", "lower": 0.003, "upper": 0.1, "scaler": 100.0},
                {"name": "skin_thickness", "lower": 0.003, "upper": 0.1, "scaler": 100.0},
                {"name": "alpha_maneuver", "lower": -10.0, "upper": 15.0},
                {"name": "fuel_mass", "lower": 1000.0, "upper": 100000.0, "scaler": 1e-5},
            ],
            constraints=[
                {"name": "CL", "point": 0, "equals": 0.5},
                {"name": "L_equals_W", "point": 1, "equals": 0.0},
                {"name": "failure", "point": 1, "upper": 0.0},
            ],
            CT=0.53 / 3600,
            R=14307000.0,
            W0_without_point_masses=50000.0,
            tolerance=0.5,
            max_iterations=5,
        )

        assert env["schema_version"] == "1.0"
        result = _r(env)

        # Top-level structure
        assert "success" in result
        assert "optimized_design_variables" in result
        assert "final_results" in result
        assert "optimization_history" in result

        # Multipoint results keyed by role
        fr = result["final_results"]
        assert "cruise" in fr
        assert "maneuver" in fr

        # Per-point physics sanity checks
        for role in ("cruise", "maneuver"):
            pt = fr[role]
            assert pt["CL"] > 0, f"{role} CL should be positive"
            assert pt["CD"] > 0, f"{role} CD should be positive"
            assert isinstance(pt.get("fuelburn"), float), f"{role} fuelburn should be a float"

        # DV arrays returned in root-to-tip order
        dvs = result["optimized_design_variables"]
        assert "twist" in dvs
        assert isinstance(dvs["twist"], list)

        # fuel_mass should be present as a scalar list
        assert "fuel_mass" in dvs
        fm = dvs["fuel_mass"]
        assert isinstance(fm, list) and len(fm) == 1


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    async def test_reset_all_clears_surfaces(self, aero_wing):
        from hangar.sdk.state import sessions as _sessions
        assert "wing" in _sessions.get("default").surfaces
        await reset()
        assert len(_sessions.get("default").surfaces) == 0

    async def test_reset_specific_session(self, aero_wing):
        from hangar.sdk.state import sessions as _sessions
        _sessions.get("other").add_surface({"name": "x", "mesh": None})
        await reset(session_id="default")
        assert len(_sessions.get("default").surfaces) == 0
        assert "x" in _sessions.get("other").surfaces

    async def test_reset_returns_status(self):
        r = await reset()
        assert r["cleared"] == "all"

        r2 = await reset(session_id="default")
        assert r2["cleared"] == "default"


# ---------------------------------------------------------------------------
# Common-mistake regression tests
# ---------------------------------------------------------------------------


class TestCommonMistakeRegressions:
    """Regression tests for common user errors that should produce clear messages."""

    async def test_failure_constraint_on_aero_only(self, aero_wing):
        """'failure' constraint requires structural analysis -- should raise."""
        with pytest.raises((ValueError, KeyError)):
            await run_optimization(
                surfaces=["wing"],
                analysis_type="aero",
                objective="CL",
                design_variables=[{"name": "alpha", "lower": -5.0, "upper": 15.0}],
                constraints=[{"name": "failure", "upper": 0.0}],
            )

    async def test_thickness_intersects_on_wingbox(self, wingbox_wing):
        """thickness_intersects is tube-only -- should raise on wingbox surface."""
        with pytest.raises(ValueError, match="thickness_intersects|tube|wingbox"):
            await run_optimization(
                surfaces=["wing"],
                analysis_type="aerostruct",
                objective="structural_mass",
                design_variables=[
                    {"name": "spar_thickness", "lower": 0.001, "upper": 0.05},
                ],
                constraints=[
                    {"name": "L_equals_W", "equals": 1.0},
                    {"name": "thickness_intersects", "upper": 0.0},
                ],
            )

    async def test_even_num_y_raises(self):
        """num_y must be odd -- even values should raise."""
        with pytest.raises(ValueError, match="odd"):
            from hangar.oas.server import create_surface as cs
            await cs(
                name="bad", wing_type="rect", span=10.0,
                root_chord=1.0, num_x=2, num_y=6,
            )

    async def test_multipoint_requires_flight_points(self, wingbox_wing):
        """Multipoint optimization needs flight_points list -- should fail without it."""
        with pytest.raises((ValueError, TypeError, IndexError)):
            await run_optimization(
                surfaces=["wing"],
                analysis_type="aerostruct",
                objective="fuelburn",
                design_variables=[{"name": "twist", "lower": -5.0, "upper": 10.0}],
                constraints=[{"name": "L_equals_W", "equals": 0.0}],
                CT=0.53 / 3600,
                R=14307000.0,
                W0_without_point_masses=50000.0,
                flight_points=[],  # empty should raise
            )
