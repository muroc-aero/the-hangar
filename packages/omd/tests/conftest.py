"""Shared fixtures for hangar-omd tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolate_omd_data(tmp_path, monkeypatch):
    """Redirect all omd data paths to per-test temp directory."""
    monkeypatch.setenv("OMD_DB_PATH", str(tmp_path / "analysis.db"))
    monkeypatch.setenv("OMD_PLAN_STORE", str(tmp_path / "plans"))
    monkeypatch.setenv("OMD_RECORDINGS_DIR", str(tmp_path / "recordings"))
    yield tmp_path


@pytest.fixture
def fixtures_dir():
    """Return the path to test fixture plan directories."""
    return FIXTURES_DIR


@pytest.fixture
def stub_deck(monkeypatch):
    """Replace the ~20-minute pyCycle off-design sweep with 8 fake points.

    Structural and wiring questions about a propulsion slot do not depend on
    the deck's contents, only on the shape of the model the slot builds.
    """
    import numpy as np

    import hangar.omd.pyc.surrogate as surrogate

    n = 8
    r = np.linspace(0.0, 1.0, n)
    deck = {
        "alt_ft": r * 40000.0,
        "MN": 0.2 + r * 0.65,
        "throttle": 0.15 + r * 0.85,
        "thrust_lbf": 2000.0 + r * 8000.0,
        "fuel_flow_lbm_s": 0.4 + r * 1.6,
        "T4_degR": 1800.0 + r * 1057.0,
        "converged": np.ones(n, dtype=bool),
    }
    surrogate.clear_deck_cache()
    monkeypatch.setattr(
        surrogate, "generate_deck",
        lambda **kw: {k: v.copy() for k, v in deck.items()},
    )
    yield deck
    surrogate.clear_deck_cache()


@pytest.fixture
def stub_vlm(monkeypatch):
    """Replace the OAS VLM training grid (216 runs) with constant CL/CD."""
    from openconcept.aerodynamics.openaerostruct import drag_polar

    def cheap(self, inputs, outputs):
        outputs["CL_train"][:] = 0.5
        outputs["CD_train"][:] = 0.02

    monkeypatch.setattr(drag_polar.VLMDataGen, "compute", cheap)
