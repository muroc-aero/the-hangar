"""Tests for drag polar sweep."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hangar.omd.polar import run_polar

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.mark.slow
def test_polar_basic():
    """Drag polar produces valid CL-CD data."""
    fixture = FIXTURES_DIR / "oas_aero_analysis"
    result = run_polar(
        fixture,
        alpha_start=-2.0,
        alpha_end=10.0,
        num_alpha=7,
    )

    assert len(result["alpha_deg"]) == 7
    assert len(result["CL"]) == 7
    assert len(result["CD"]) == 7
    assert len(result["L_over_D"]) == 7

    # CL should increase with alpha
    for i in range(1, len(result["CL"])):
        assert result["CL"][i] > result["CL"][i - 1], (
            f"CL not monotonically increasing: CL[{i}]={result['CL'][i]} "
            f"<= CL[{i-1}]={result['CL'][i-1]}"
        )

    # CD should be positive everywhere
    for i, cd in enumerate(result["CD"]):
        assert cd > 0, f"CD[{i}] = {cd} should be > 0"

    # Best L/D should be identified
    best = result["best_L_over_D"]
    assert best["L_over_D"] is not None
    assert best["L_over_D"] > 0


@pytest.mark.slow
def test_polar_aerostruct():
    """Drag polar works for aerostruct plans too."""
    fixture = FIXTURES_DIR / "oas_aerostruct_analysis"
    result = run_polar(
        fixture,
        alpha_start=0.0,
        alpha_end=8.0,
        num_alpha=5,
    )

    assert len(result["CL"]) == 5
    # CD should always be positive for aerostruct
    for cd in result["CD"]:
        assert cd > 0


def test_polar_invalid_num_alpha():
    """run_polar rejects num_alpha < 2."""
    with pytest.raises(ValueError, match="num_alpha must be >= 2"):
        run_polar(Path("dummy.yaml"), num_alpha=1)


@pytest.mark.slow
def test_polar_golden():
    """Drag polar matches golden reference values."""
    import numpy as np
    from hangar.omd.factories.oas_aero import build_oas_aeropoint

    golden_path = GOLDEN_DIR / "golden_polar.json"
    with open(golden_path) as f:
        golden = json.load(f)

    expected = golden["expected"]
    tols = golden["tolerances"]

    # Build same problem as golden generation script
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
        "alpha": 0.0,
        "Mach_number": 0.84,
        "re": 1e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aeropoint(component_config, operating_points)
    prob.setup()

    alphas = golden["alpha_deg"]
    CLs, CDs = [], []
    for a in alphas:
        prob.set_val("alpha", a, units="deg")
        prob.run_model()
        CLs.append(float(np.asarray(prob.get_val("aero_point_0.CL")).ravel()[0]))
        CDs.append(float(np.asarray(prob.get_val("aero_point_0.CD")).ravel()[0]))

    prob.cleanup()

    # Compare CL at each alpha
    for i, (got, exp) in enumerate(zip(CLs, expected["CL"])):
        assert got == pytest.approx(exp, rel=tols["CL"]["rel"]), (
            f"CL mismatch at alpha={alphas[i]}: got={got}, expected={exp}"
        )

    # Compare CD at each alpha
    for i, (got, exp) in enumerate(zip(CDs, expected["CD"])):
        assert got == pytest.approx(exp, rel=tols["CD"]["rel"]), (
            f"CD mismatch at alpha={alphas[i]}: got={got}, expected={exp}"
        )
