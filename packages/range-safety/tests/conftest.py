"""Shared fixtures for hangar-range-safety tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_omd_data(tmp_path, monkeypatch):
    """Redirect all omd data paths to per-test temp directory."""
    monkeypatch.setenv("OMD_DB_PATH", str(tmp_path / "analysis.db"))
    monkeypatch.setenv("OMD_PLAN_STORE", str(tmp_path / "plans"))
    monkeypatch.setenv("OMD_RECORDINGS_DIR", str(tmp_path / "recordings"))
    yield tmp_path


@pytest.fixture
def catalog_dir():
    """Return the path to the repo catalog directory."""
    here = Path(__file__).resolve()
    # Walk up to find catalog/
    for parent in here.parents:
        candidate = parent / "catalog"
        if candidate.is_dir():
            return candidate
    return here.parents[3] / "catalog"


@pytest.fixture
def valid_aero_plan():
    """A minimal valid aero-only plan."""
    return {
        "metadata": {"id": "test-aero", "name": "Test aero", "version": 1},
        "components": [
            {
                "id": "wing",
                "type": "oas/AeroPoint",
                "config": {
                    "surfaces": [
                        {
                            "name": "wing",
                            "wing_type": "rect",
                            "num_y": 7,
                            "span": 10.0,
                            "symmetry": True,
                        }
                    ]
                },
            }
        ],
        "operating_points": {
            "velocity": 248.136,
            "alpha": 5.0,
            "Mach_number": 0.84,
            "rho": 0.38,
        },
    }


@pytest.fixture
def valid_aerostruct_plan():
    """A minimal valid aerostruct plan with optimization."""
    return {
        "metadata": {"id": "test-aerostruct", "name": "Test aerostruct", "version": 1},
        "components": [
            {
                "id": "wing",
                "type": "oas/AerostructPoint",
                "config": {
                    "surfaces": [
                        {
                            "name": "wing",
                            "wing_type": "rect",
                            "num_y": 7,
                            "span": 10.0,
                            "symmetry": True,
                            "fem_model_type": "tube",
                            "E": 70e9,
                            "G": 30e9,
                            "yield_stress": 500e6,
                            "mrho": 3000.0,
                            "thickness_cp": [0.01, 0.02, 0.01],
                        }
                    ]
                },
            }
        ],
        "operating_points": {
            "velocity": 248.136,
            "alpha": 5.0,
            "Mach_number": 0.84,
            "rho": 0.38,
        },
        "solvers": {
            "nonlinear": {"type": "NewtonSolver", "options": {"maxiter": 20}},
            "linear": {"type": "DirectSolver"},
        },
        "requirements": [
            {"id": "R1", "text": "Minimize structural mass", "traces_to": ["structural_mass"]},
            {"id": "R2", "text": "Failure index safe", "traces_to": ["failure"]},
        ],
        "design_variables": [
            {
                "name": "twist_cp",
                "lower": -10.0,
                "upper": 15.0,
                "traces_to": ["R1"],
            },
            {
                "name": "thickness_cp",
                "lower": 0.001,
                "upper": 0.5,
                "scaler": 10.0,
                "traces_to": ["R2"],
            },
        ],
        "constraints": [
            {"name": "failure", "upper": 0.0, "traces_to": ["R2"]},
        ],
        "objective": {
            "name": "structural_mass",
            "scaler": 1e-4,
            "traces_to": ["R1"],
        },
        "optimizer": {"type": "SLSQP", "options": {"maxiter": 50}},
    }
