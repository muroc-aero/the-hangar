"""Tests for the OAS aero-only (AeroPoint) factory."""

from __future__ import annotations

import pytest

from hangar.omd.factories.oas_aero import build_oas_aeropoint


@pytest.mark.slow
def test_build_oas_aeropoint_runs():
    """Build and run a minimal OAS aero-only problem."""
    component_config = {
        "surfaces": [
            {
                "name": "wing",
                "wing_type": "rect",
                "num_x": 2,
                "num_y": 7,
                "span": 10.0,
                "root_chord": 1.0,
                "symmetry": True,
                "with_viscous": True,
                "CD0": 0.015,
            }
        ]
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)

    assert metadata["point_name"] == "aero_point_0"
    assert metadata["surface_names"] == ["wing"]

    prob.setup()
    prob.run_model()

    # AeroPoint promotes CL, CD to the point level
    CL = float(prob.get_val("aero_point_0.CL")[0])
    CD = float(prob.get_val("aero_point_0.CD")[0])

    assert CL > 0, f"CL should be positive, got {CL}"
    assert CD > 0, f"CD should be positive, got {CD}"
    assert CL / CD > 1, f"L/D should be > 1, got {CL/CD}"


def test_build_oas_aeropoint_missing_surfaces():
    with pytest.raises(ValueError, match="surfaces"):
        build_oas_aeropoint({}, {})
