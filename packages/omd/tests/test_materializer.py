"""Tests for the plan materializer."""

from __future__ import annotations

import pytest

from hangar.omd.materializer import materialize


# ---------------------------------------------------------------------------
# Minimal OAS plan for testing
# ---------------------------------------------------------------------------

MINIMAL_OAS_PLAN = {
    "metadata": {"id": "test-wing", "name": "Test Wing", "version": 1},
    "components": [
        {
            "id": "wing",
            "type": "oas/AerostructPoint",
            "config": {
                "surfaces": [
                    {
                        "name": "wing",
                        "wing_type": "rect",
                        "num_x": 2,
                        "num_y": 5,
                        "span": 10.0,
                        "root_chord": 1.0,
                        "symmetry": True,
                        "fem_model_type": "tube",
                        "E": 70.0e9,
                        "G": 30.0e9,
                        "yield_stress": 500.0e6,
                        "mrho": 3000.0,
                        "thickness_cp": [0.05, 0.1, 0.05],
                    }
                ]
            },
        }
    ],
    "operating_points": {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    },
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_materialize_analysis(tmp_path):
    """Materialize and run a simple OAS aerostruct analysis."""
    rec_path = tmp_path / "recorder.sql"
    prob, metadata = materialize(
        MINIMAL_OAS_PLAN,
        recording_level="minimal",
        recorder_path=rec_path,
    )

    assert metadata["point_name"] == "AS_point_0"
    assert "wing" in metadata["surface_names"]

    prob.run_model()

    CL = prob.get_val("AS_point_0.CL")[0]
    CD = prob.get_val("AS_point_0.CD")[0]
    assert CL > 0
    assert CD > 0

    prob.record("final")
    prob.cleanup()


@pytest.mark.slow
def test_materialize_with_solvers(tmp_path):
    """Materialize a plan with explicit solver configuration."""
    plan = {
        **MINIMAL_OAS_PLAN,
        "solvers": {
            "nonlinear": {
                "type": "NewtonSolver",
                "options": {"maxiter": 10, "atol": 1e-6},
            },
            "linear": {"type": "DirectSolver"},
        },
    }

    prob, metadata = materialize(
        plan,
        recording_level="minimal",
        recorder_path=tmp_path / "recorder.sql",
    )

    # Apply solvers post-setup
    from hangar.omd.materializer import apply_solvers_post_setup
    apply_solvers_post_setup(prob, metadata)

    prob.run_model()
    CL = prob.get_val("AS_point_0.CL")[0]
    assert CL > 0
    prob.cleanup()


def test_materialize_missing_components():
    with pytest.raises(ValueError, match="at least one component"):
        materialize({"metadata": {"id": "x", "name": "x", "version": 1}, "components": []})


def test_materialize_two_paraboloids_composite():
    """Two paraboloid components composed: a feeds b via connection."""
    plan = {
        "metadata": {"id": "two-parab", "name": "two paraboloids", "version": 1},
        "components": [
            {"id": "a", "type": "paraboloid/Paraboloid", "config": {}},
            {"id": "b", "type": "paraboloid/Paraboloid", "config": {}},
        ],
        "connections": [
            {"src": "a.f_xy", "tgt": "b.x"},
        ],
        "operating_points": {"x": 3.0, "y": -4.0},
    }
    prob, metadata = materialize(plan)
    assert metadata.get("_composite") is True
    assert "a" in metadata["component_ids"]
    assert "b" in metadata["component_ids"]

    # Set inputs on component 'a'
    prob.set_val("a.x", 3.0)
    prob.set_val("a.y", -4.0)
    # Set y for component 'b' (x comes from connection)
    prob.set_val("b.y", 0.0)

    prob.run_model()

    # a: f(3, -4) = (3-3)^2 + 3*(-4) + (-4+4)^2 - 3 = -15
    a_out = float(prob.get_val("a.f_xy"))
    assert abs(a_out - (-15.0)) < 1e-8, f"a.f_xy = {a_out}"

    # b: x = -15 (from connection), y = 0
    # f(-15, 0) = (-15-3)^2 + (-15)*0 + (0+4)^2 - 3 = 324 + 0 + 16 - 3 = 337
    b_out = float(prob.get_val("b.f_xy"))
    assert abs(b_out - 337.0) < 1e-8, f"b.f_xy = {b_out}"
