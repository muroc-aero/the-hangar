"""Tests for stability derivative computation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hangar.omd.stability import compute_stability
from hangar.omd.factories.oas import build_oas_aerostruct
from hangar.omd.factories.oas_aero import build_oas_aeropoint

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.mark.slow
def test_stability_aero_positive_CL_alpha():
    """CL_alpha should be positive and in a reasonable range for a finite wing."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 7,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)
    prob.setup()
    prob.run_model()

    result = compute_stability(prob, metadata)
    prob.cleanup()

    # CL_alpha should be positive (3-6 per radian for typical finite wings)
    assert result["CL_alpha_per_rad"] > 0, (
        f"CL_alpha should be > 0, got {result['CL_alpha_per_rad']}"
    )
    assert 1.0 < result["CL_alpha_per_rad"] < 10.0, (
        f"CL_alpha={result['CL_alpha_per_rad']}/rad seems out of range"
    )


@pytest.mark.slow
def test_stability_aerostruct():
    """Stability derivatives work for aerostruct problems."""
    component_config = {
        "surfaces": [{
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
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    prob.setup()
    prob.run_model()

    result = compute_stability(prob, metadata)
    prob.cleanup()

    assert result["CL_alpha_per_rad"] > 0
    assert result["static_margin"] is not None


@pytest.mark.slow
def test_stability_restores_state():
    """Alpha and CL should be restored after stability computation."""
    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 5,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)
    prob.setup()
    prob.run_model()

    # Record pre-stability state
    alpha_before = float(prob.get_val("alpha", units="deg")[0])
    CL_before = float(np.asarray(prob.get_val("aero_point_0.CL")).ravel()[0])

    result = compute_stability(prob, metadata)

    # Verify state is restored
    alpha_after = float(prob.get_val("alpha", units="deg")[0])
    CL_after = float(np.asarray(prob.get_val("aero_point_0.CL")).ravel()[0])

    assert alpha_after == pytest.approx(alpha_before, abs=1e-10)
    assert CL_after == pytest.approx(CL_before, rel=1e-8)

    prob.cleanup()


@pytest.mark.slow
def test_stability_golden():
    """Stability derivatives match golden reference values."""
    golden_path = GOLDEN_DIR / "golden_stability.json"
    with open(golden_path) as f:
        golden = json.load(f)

    expected = golden["expected"]
    tols = golden["tolerances"]

    component_config = {
        "surfaces": [{
            "name": "wing",
            "wing_type": "rect",
            "num_x": 2,
            "num_y": 7,
            "span": 10.0,
            "root_chord": 1.0,
            "symmetry": True,
            "CD0": 0.01,
            "with_viscous": True,
        }],
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)
    prob.setup()
    prob.run_model()

    result = compute_stability(prob, metadata)
    prob.cleanup()

    assert result["CL_alpha_per_rad"] == pytest.approx(
        expected["CL_alpha_per_rad"], rel=tols["CL_alpha_per_rad"]["rel"]
    )
    assert result["CM_alpha_per_rad"] == pytest.approx(
        expected["CM_alpha_per_rad"], rel=tols["CM_alpha_per_rad"]["rel"]
    )
    if expected["static_margin"] is not None:
        assert result["static_margin"] == pytest.approx(
            expected["static_margin"], abs=tols["static_margin"]["abs"]
        )
