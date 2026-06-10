"""Tests for the OAS aerostructural factory."""

from __future__ import annotations

import pytest
import numpy as np

from hangar.omd.factories.oas import (
    build_oas_aerostruct,
    _plan_config_to_surface_dict,
    _generate_mesh,
)


# ---------------------------------------------------------------------------
# Mesh generation
# ---------------------------------------------------------------------------


def test_generate_mesh_rect():
    config = {"wing_type": "rect", "num_x": 2, "num_y": 5, "span": 10.0,
              "root_chord": 1.0, "symmetry": True}
    mesh, twist_cp = _generate_mesh(config)
    # With symmetry=True, OAS halves the mesh: (num_y+1)//2 = 3 spanwise points
    assert mesh.shape == (2, 3, 3)
    assert twist_cp is None


def test_generate_mesh_rejects_even_num_y():
    config = {"wing_type": "rect", "num_x": 2, "num_y": 4, "span": 10.0,
              "root_chord": 1.0, "symmetry": True}
    with pytest.raises(Exception):
        _generate_mesh(config)


# ---------------------------------------------------------------------------
# Surface dict construction
# ---------------------------------------------------------------------------


def test_plan_config_to_surface_dict():
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

    assert surface["name"] == "wing"
    assert "mesh" in surface
    assert surface["mesh"].shape == (2, 3, 3)  # symmetry halves: (5+1)//2=3
    assert surface["fem_model_type"] == "tube"
    assert surface["E"] == 70.0e9
    assert "yield" in surface  # yield_stress mapped to yield
    assert "twist_cp" in surface
    assert "thickness_cp" in surface


def test_surface_dict_with_custom_thickness():
    config = {
        "name": "wing",
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
    surface = _plan_config_to_surface_dict(config)
    np.testing.assert_array_equal(surface["thickness_cp"], [0.05, 0.1, 0.05])


# ---------------------------------------------------------------------------
# Full factory build
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_build_oas_aerostruct_runs():
    """Build and run a minimal OAS aerostruct problem."""
    component_config = {
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
    }
    operating_points = {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
        "re": 1.0e6,
        "rho": 0.38,
    }

    prob, metadata = build_oas_aerostruct(component_config, operating_points)

    assert metadata["point_name"] == "AS_point_0"
    assert metadata["surface_names"] == ["wing"]

    # Setup and run
    prob.setup()
    prob.run_model()

    # Check results are physically reasonable
    CL = prob.get_val("AS_point_0.CL")[0]
    CD = prob.get_val("AS_point_0.CD")[0]
    assert CL > 0, f"CL should be positive, got {CL}"
    assert CD > 0, f"CD should be positive, got {CD}"
    assert CL / CD > 1, f"L/D should be > 1, got {CL/CD}"


def test_build_oas_aerostruct_missing_surfaces():
    with pytest.raises(ValueError, match="surfaces"):
        build_oas_aerostruct({}, {})


# ---------------------------------------------------------------------------
# Unknown surface-config keys + chord_cp forwarding
# ---------------------------------------------------------------------------

_BASE_SURFACE_CONFIG = {
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


def test_unknown_surface_key_warns(caplog, monkeypatch):
    import logging

    # hangar.sdk.telemetry sets propagate=False on the "hangar" logger;
    # restore propagation so caplog's root handler sees the warning.
    monkeypatch.setattr(logging.getLogger("hangar"), "propagate", True)
    config = dict(_BASE_SURFACE_CONFIG)
    config["twist_pc"] = [0.0, 0.0]  # typo for twist_cp
    with caplog.at_level(logging.WARNING, logger="hangar.omd.factories.oas"):
        _plan_config_to_surface_dict(config)
    assert any("twist_pc" in r.message for r in caplog.records)


def test_known_surface_keys_do_not_warn(caplog, monkeypatch):
    import logging

    monkeypatch.setattr(logging.getLogger("hangar"), "propagate", True)
    config = dict(_BASE_SURFACE_CONFIG)
    config["twist_cp"] = [0.0, 0.0, 0.0]
    config["chord_cp"] = [1.0, 1.0, 1.0]
    with caplog.at_level(logging.WARNING, logger="hangar.omd.factories.oas"):
        _plan_config_to_surface_dict(config)
    assert not [r for r in caplog.records if "unrecognized" in r.message]


def test_chord_cp_forwarded_to_surface_dict():
    """chord_cp is advertised in var_paths, so the builder must forward it."""
    config = dict(_BASE_SURFACE_CONFIG)
    config["chord_cp"] = [1.0, 0.9, 0.8]
    surface = _plan_config_to_surface_dict(config)
    assert np.allclose(surface["chord_cp"], [1.0, 0.9, 0.8])
