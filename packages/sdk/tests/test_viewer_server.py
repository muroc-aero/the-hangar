"""Tests for hangar.sdk.viz.viewer_server result-shaping logic.

Regression coverage for the multipoint-flatten bug:
single-point and multipoint optimization artifacts both produced via the same
``generate_plot_png`` path, but the flatten step at viewer_server.py:124 used
to clobber the ``final_results`` key for multipoint runs, so
``plot_multipoint_comparison`` rendered "Multipoint results not available"
and any sectional-data plot (lift, stress, deflection) found no
``surfaces`` dict and rendered "No stress data available".
"""

from __future__ import annotations

from unittest.mock import patch

from hangar.sdk.viz.plotting import PlotResult
from hangar.sdk.viz.viewer_server import (
    _shape_optimization_results,
    generate_plot_png,
)

# Minimal valid PNG (1x1 transparent pixel) — bytes the Image type accepts.
_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xfa\xcf"
    b"\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _fake_plot_result(plot_type: str) -> PlotResult:
    """Return a PlotResult whose ``image.data`` is a valid PNG byte string."""
    from mcp.server.fastmcp.utilities.types import Image as _Image

    return PlotResult(
        image=_Image(data=_MIN_PNG, format="png"),
        metadata={"plot_type": plot_type},
    )


# ---------------------------------------------------------------------------
# _shape_optimization_results
# ---------------------------------------------------------------------------


class TestShapeOptimizationResults:
    def test_empty_input_returns_empty(self):
        assert _shape_optimization_results({}) == {}

    def test_singlepoint_returned_unchanged(self):
        """Single-point: ``final_results`` is flat — return as-is, no
        ``final_results`` key added."""
        fr = {
            "CL": 0.5,
            "CD": 0.02,
            "L_over_D": 25.0,
            "surfaces": {"wing": {"CL": 0.5, "CD": 0.02}},
        }
        out = _shape_optimization_results(fr)
        assert out["CL"] == 0.5
        assert out["surfaces"]["wing"]["CL"] == 0.5
        # We did not invent a final_results key for single-point.
        assert "final_results" not in out
        # And we returned a shallow copy, not the same object.
        assert out is not fr

    def test_multipoint_exposes_cruise_at_top(self):
        """Multipoint: cruise fields exposed at top so single-point plots work,
        and ``final_results`` preserved so multipoint plots work."""
        fr = {
            "cruise": {
                "CL": 0.5,
                "CD": 0.029,
                "surfaces": {"wing": {"CL": 0.5, "failure": -0.6}},
            },
            "maneuver": {
                "CL": 1.25,
                "CD": 0.052,
                "surfaces": {"wing": {"CL": 1.25, "failure": 0.0}},
            },
        }
        out = _shape_optimization_results(fr)
        # Primary (cruise) point exposed at top.
        assert out["CL"] == 0.5
        assert out["CD"] == 0.029
        assert out["surfaces"]["wing"]["failure"] == -0.6
        # Full multipoint dict preserved for plot_multipoint_comparison.
        assert "final_results" in out
        assert set(out["final_results"]) == {"cruise", "maneuver"}
        assert out["final_results"]["maneuver"]["CL"] == 1.25

    def test_multipoint_without_cruise_falls_back_to_first_role(self):
        """If there's no ``cruise`` role, use whichever role comes first."""
        fr = {
            "takeoff": {"CL": 1.4, "surfaces": {"wing": {"CL": 1.4}}},
            "landing": {"CL": 1.6, "surfaces": {"wing": {"CL": 1.6}}},
        }
        out = _shape_optimization_results(fr)
        assert out["CL"] == 1.4  # takeoff is first
        assert set(out["final_results"]) == {"takeoff", "landing"}


# ---------------------------------------------------------------------------
# generate_plot_png: end-to-end multipoint regression
# ---------------------------------------------------------------------------


def _multipoint_artifact() -> dict:
    """Minimal optimization artifact matching the on-disk schema."""
    return {
        "metadata": {"analysis_type": "optimization"},
        "results": {
            "success": True,
            "optimized_design_variables": {
                "chord": [1.0, 0.9, 0.3],
                "thickness": [0.004, 0.003, 0.003],
                "alpha": [5.0],
                "alpha_maneuver": [12.0],
            },
            "optimization_history": {
                "num_iterations": 10,
                "objective_values": [350.0, 200.0],
                "dv_history": {},
                "constraint_history": {},
                "initial_dvs": {},
            },
            "final_results": {
                "cruise": {
                    "CL": 0.5,
                    "CD": 0.029,
                    "L_over_D": 17.2,
                    "fuelburn": 200.0,
                    "structural_mass": 100.0,
                    "surfaces": {
                        "wing": {
                            "CL": 0.5,
                            "CD": 0.029,
                            "failure": -0.6,
                            "tip_deflection_m": 0.4,
                        }
                    },
                },
                "maneuver": {
                    "CL": 1.25,
                    "CD": 0.052,
                    "L_over_D": 24.0,
                    "fuelburn": 142.0,
                    "structural_mass": 100.0,
                    "surfaces": {
                        "wing": {
                            "CL": 1.25,
                            "CD": 0.052,
                            "failure": 0.0,
                            "tip_deflection_m": 1.2,
                        }
                    },
                },
            },
            "standard_detail": {
                "sectional_data": {
                    "wing": {
                        "y_span_norm": [0.0, 0.5, 1.0],
                        "Cl": [0.5, 0.5, 0.4],
                        "lift_loading": [0.5, 0.5, 0.4],
                        "vonmises_MPa": [120.0, 80.0, 10.0],
                        "failure_index": [-0.6, -0.7, -0.95],
                        "deflection_m": [0.0, 0.15, 0.4],
                    }
                },
            },
        },
    }


def test_generate_plot_png_multipoint_comparison_sees_both_points(tmp_path):
    """Regression: multipoint_comparison used to render the 'not available'
    placeholder for multipoint opts because the flatten step dropped
    ``final_results``.  After the fix, ``generate_plot`` receives a
    ``plot_results`` dict that still contains both points."""
    captured: dict = {}

    def fake_generate_plot(plot_type, run_id, plot_results, *args, **kwargs):
        captured["plot_type"] = plot_type
        captured["plot_results"] = plot_results
        return _fake_plot_result(plot_type)

    with patch("hangar.sdk.artifacts.store.ArtifactStore") as MockStore, \
         patch("hangar.sdk.viz.plotting.generate_plot", side_effect=fake_generate_plot):
        MockStore.return_value.get.return_value = _multipoint_artifact()
        png = generate_plot_png("rid", "multipoint_comparison")

    assert png is not None
    assert captured["plot_type"] == "multipoint_comparison"
    pr = captured["plot_results"]
    # The fix: final_results survives the flatten so plot_multipoint_comparison
    # sees both points.
    assert "final_results" in pr
    assert set(pr["final_results"]) == {"cruise", "maneuver"}
    assert pr["final_results"]["maneuver"]["CL"] == 1.25


def test_generate_plot_png_multipoint_lift_has_surfaces_and_sectional(tmp_path):
    """Regression: single-point plots on a multipoint opt artifact used to
    find an empty ``surfaces`` dict because the flatten step replaced the
    flat per-point payload with the role-keyed one.  After the fix, the
    cruise point's surfaces are at top level and sectional_data is injected."""
    captured: dict = {}

    def fake_generate_plot(plot_type, run_id, plot_results, *args, **kwargs):
        captured["plot_results"] = plot_results
        return _fake_plot_result(plot_type)

    with patch("hangar.sdk.artifacts.store.ArtifactStore") as MockStore, \
         patch("hangar.sdk.viz.plotting.generate_plot", side_effect=fake_generate_plot):
        MockStore.return_value.get.return_value = _multipoint_artifact()
        generate_plot_png("rid", "lift_distribution")

    pr = captured["plot_results"]
    # Cruise-point surfaces accessible the way single-point plots expect.
    assert "wing" in pr.get("surfaces", {})
    assert pr["surfaces"]["wing"]["failure"] == -0.6  # cruise, not maneuver
    # Sectional data injection happened on the right wing dict.
    assert "sectional_data" in pr["surfaces"]["wing"]
    assert pr["surfaces"]["wing"]["sectional_data"]["Cl"] == [0.5, 0.5, 0.4]
    # And the role-keyed payload is still around for cross-point plots.
    assert "final_results" in pr


def test_generate_plot_png_singlepoint_unchanged(tmp_path):
    """Single-point optimization artifacts shape exactly as they used to:
    flat top-level fields, no synthetic ``final_results`` key."""
    captured: dict = {}

    def fake_generate_plot(plot_type, run_id, plot_results, *args, **kwargs):
        captured["plot_results"] = plot_results
        return _fake_plot_result(plot_type)

    artifact = {
        "metadata": {"analysis_type": "optimization"},
        "results": {
            "success": True,
            "final_results": {
                "CL": 0.5,
                "CD": 0.02,
                "L_over_D": 25.0,
                "fuelburn": 180.0,
                "structural_mass": 90.0,
                "surfaces": {"wing": {"CL": 0.5, "CD": 0.02, "failure": -0.5}},
            },
            "optimization_history": {"num_iterations": 5, "objective_values": [200.0, 180.0]},
            "standard_detail": {
                "sectional_data": {
                    "wing": {"y_span_norm": [0.0, 1.0], "Cl": [0.5, 0.4]},
                }
            },
        },
    }

    with patch("hangar.sdk.artifacts.store.ArtifactStore") as MockStore, \
         patch("hangar.sdk.viz.plotting.generate_plot", side_effect=fake_generate_plot):
        MockStore.return_value.get.return_value = artifact
        generate_plot_png("rid", "lift_distribution")

    pr = captured["plot_results"]
    assert pr["CL"] == 0.5
    assert pr["surfaces"]["wing"]["CL"] == 0.5
    # No invented final_results key for single-point.
    assert "final_results" not in pr
