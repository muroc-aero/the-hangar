"""Tests for composite material support."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hangar.omd.factories.oas import _plan_config_to_surface_dict, build_oas_aerostruct

GOLDEN_DIR = Path(__file__).parent / "golden"


# T300/5208 carbon-epoxy typical properties
_COMPOSITE_SURFACE_CONFIG = {
    "name": "wing",
    "wing_type": "CRM",
    "num_x": 2,
    "num_y": 5,
    "symmetry": True,
    "fem_model_type": "wingbox",
    "mrho": 1600.0,
    "safety_factor": 1.5,
    "spar_thickness_cp": [0.004, 0.005, 0.008],
    "skin_thickness_cp": [0.005, 0.010, 0.015],
    # Composite laminate properties
    "use_composite": True,
    "ply_angles": [0.0, 45.0, -45.0, 90.0],
    "ply_fractions": [0.25, 0.25, 0.25, 0.25],
    "E1": 181.0e9,       # Pa, fiber longitudinal
    "E2": 10.3e9,        # Pa, matrix transverse
    "nu12": 0.28,
    "G12": 7.17e9,       # Pa, shear
    "sigma_t1": 1500.0e6,
    "sigma_c1": 1500.0e6,
    "sigma_t2": 40.0e6,
    "sigma_c2": 246.0e6,
    "sigma_12max": 68.0e6,
}


def test_composite_surface_dict():
    """Composite surface config produces correct surface dict."""
    surface = _plan_config_to_surface_dict(_COMPOSITE_SURFACE_CONFIG)

    # Should have camelCase useComposite flag
    assert surface["useComposite"] is True

    # E and G should be overwritten by compute_composite_stiffness
    assert surface["E"] > 0
    assert surface["G"] > 0

    # Effective E should be somewhere between E2 and E1
    # For a quasi-isotropic layup, it's typically ~70 GPa for carbon
    assert surface["E"] > 10e9
    assert surface["E"] < 200e9

    # Ply parameters should be passed through
    assert surface["ply_angles"] == [0.0, 45.0, -45.0, 90.0]
    assert surface["ply_fractions"] == [0.25, 0.25, 0.25, 0.25]

    # Strength parameters should be present
    assert surface["sigma_t1"] == 1500.0e6
    assert surface["sigma_c1"] == 1500.0e6


def test_composite_not_enabled():
    """Without use_composite, surface should not have useComposite."""
    config = {
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
    }
    surface = _plan_config_to_surface_dict(config)
    assert "useComposite" not in surface


@pytest.mark.slow
def test_composite_wingbox_runs():
    """Composite wingbox problem builds and runs successfully."""
    component_config = {"surfaces": [_COMPOSITE_SURFACE_CONFIG]}
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

    CL = float(prob.get_val("AS_point_0.CL")[0])
    assert CL > 0, f"CL should be > 0, got {CL}"

    # For composite wingbox, tsaiwu_sr should be in the model outputs
    # Check that the failure output exists and is finite
    failure = prob.get_val("AS_point_0.wing_perf.failure")
    assert np.all(np.isfinite(failure)), f"Failure should be finite, got {failure}"

    prob.cleanup()


@pytest.mark.slow
def test_composite_golden():
    """Composite wingbox analysis matches golden reference values."""
    golden_path = GOLDEN_DIR / "golden_composite.json"
    with open(golden_path) as f:
        golden = json.load(f)

    expected = golden["expected"]
    tols = golden["tolerances"]

    component_config = {"surfaces": [_COMPOSITE_SURFACE_CONFIG]}
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
        "W0": 25000.0,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)
    prob.setup()
    prob.run_model()

    CL = float(prob.get_val("AS_point_0.CL")[0])
    CD = float(prob.get_val("AS_point_0.CD")[0])
    failure = float(np.max(prob.get_val("AS_point_0.wing_perf.failure")))
    mass = float(np.sum(prob.get_val("wing.structural_mass")))

    prob.cleanup()

    assert CL == pytest.approx(expected["CL"], rel=tols["CL"]["rel"])
    assert CD == pytest.approx(expected["CD"], rel=tols["CD"]["rel"])
    assert failure == pytest.approx(expected["failure"], abs=tols["failure"]["abs"])
    assert mass == pytest.approx(expected["structural_mass_kg"],
                                  rel=tols["structural_mass_kg"]["rel"])
