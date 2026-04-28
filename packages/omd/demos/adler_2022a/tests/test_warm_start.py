"""Unit tests for sweep.py's full-DV warm-start (Phase 1.8)."""
from __future__ import annotations

import json

import pandas as pd
import pytest


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """Build a fake prior CSV + per-design JSON dump in an isolated tmp
    results directory and rebind sweep's PER_DESIGN_DIR to it."""
    import sweep

    per_design_dir = tmp_path / "per_design"
    per_design_dir.mkdir()
    rng = 1500
    method = "single_point"
    cell_dir = per_design_dir / f"{rng}"
    cell_dir.mkdir()
    cell_payload = {
        "mission_range_nmi": float(rng),
        "method": method,
        "AR": 9.8,
        "taper": 0.16,
        "c4sweep_deg": 22.0,
        "twist_cp_deg": [0.0, 3.5, -2.0, 0.5],
        "toverc_cp": [0.030, 0.090, 0.110, 0.140],
        "skin_cp_m": [0.005, 0.012, 0.014, 0.016],
        "spar_cp_m": [0.004, 0.005, 0.006, 0.007],
        "W_wing_kg": 6500.0,
        "lift_dist_maneuver_N": None,
    }
    with open(cell_dir / f"{method}.json", "w") as f:
        json.dump(cell_payload, f)

    monkeypatch.setattr(sweep, "PER_DESIGN_DIR", per_design_dir)

    csv_rows = pd.DataFrame([{
        "mission_range_nmi": float(rng), "method": method,
        "converged": "True", "run_id": "fake",
        "fuel_burn_kg": 7000.0,
        "climb_fuel_kg": float("nan"),
        "cruise_fuel_kg": float("nan"),
        "descent_fuel_kg": float("nan"),
        "W_wing_maneuver_kg": 6500.0,
        "AR": 9.8, "taper": 0.16, "c4sweep_deg": 22.0,
        "wall_time_s": 1234.0, "error": "",
    }])

    return sweep, csv_rows, rng, method


def test_warm_for_returns_scalars_and_vectors(fake_run):
    sweep, csv_rows, rng, method = fake_run
    warm = sweep._warm_for(csv_rows, mission_range=float(rng), method=method)
    assert warm is not None
    # Scalars from CSV
    assert warm["AR"] == pytest.approx(9.8)
    assert warm["taper"] == pytest.approx(0.16)
    assert warm["c4sweep_deg"] == pytest.approx(22.0)
    # Vectors from per-design JSON, keyed by JSON key (per _WARM_VECTOR_FIELDS)
    assert warm["twist_cp_deg"] == [0.0, 3.5, -2.0, 0.5]
    assert warm["toverc_cp"] == [0.030, 0.090, 0.110, 0.140]
    assert len(warm["skin_cp_m"]) == 4
    assert len(warm["spar_cp_m"]) == 4


def test_read_warm_vectors_missing_file_returns_empty(fake_run):
    sweep, _, _, _ = fake_run
    out = sweep._read_warm_vectors(mission_range=99999.0, method="single_point")
    assert out == {}


def test_patch_plan_writes_vector_initials(fake_run):
    sweep, csv_rows, rng, method = fake_run
    base_plan = {
        "metadata": {"id": "test"},
        "components": [
            {"id": "design", "type": "oas/AerostructBreguet",
             "config": {"mission_range_nmi": 1.0}},
        ],
        "design_variables": [
            {"name": "ac|geom|wing|AR"},
            {"name": "ac|geom|wing|taper"},
            {"name": "ac|geom|wing|c4sweep"},
            {"name": "ac|geom|wing|twist"},
            {"name": "ac|geom|wing|toverc"},
            {"name": "ac|geom|wing|skin_thickness"},
            {"name": "ac|geom|wing|spar_thickness"},
        ],
    }
    warm = sweep._warm_for(csv_rows, mission_range=float(rng), method=method)
    patched = sweep._patch_plan(
        base_plan, mission_range=float(rng), method=method,
        fine_mesh=False, warm_dvs=warm,
    )
    by_name = {dv["name"]: dv for dv in patched["design_variables"]}
    # Scalar warm-starts
    assert by_name["ac|geom|wing|AR"]["initial"] == pytest.approx(9.8)
    assert by_name["ac|geom|wing|taper"]["initial"] == pytest.approx(0.16)
    assert by_name["ac|geom|wing|c4sweep"]["initial"] == pytest.approx(22.0)
    # Vector warm-starts (lists)
    twist_init = by_name["ac|geom|wing|twist"]["initial"]
    assert isinstance(twist_init, list) and len(twist_init) == 4
    assert twist_init == pytest.approx([0.0, 3.5, -2.0, 0.5])
    toverc_init = by_name["ac|geom|wing|toverc"]["initial"]
    assert toverc_init == pytest.approx([0.030, 0.090, 0.110, 0.140])
    assert isinstance(by_name["ac|geom|wing|skin_thickness"]["initial"], list)
    assert isinstance(by_name["ac|geom|wing|spar_thickness"]["initial"], list)


def test_patch_plan_no_warm_dvs_leaves_initial_unset(fake_run):
    sweep, _, _, _ = fake_run
    base_plan = {
        "metadata": {"id": "test"},
        "components": [
            {"id": "design", "type": "oas/AerostructBreguet", "config": {}},
        ],
        "design_variables": [
            {"name": "ac|geom|wing|AR"},
            {"name": "ac|geom|wing|twist"},
        ],
    }
    patched = sweep._patch_plan(
        base_plan, mission_range=300.0, method="single_point",
        fine_mesh=False, warm_dvs=None,
    )
    for dv in patched["design_variables"]:
        assert "initial" not in dv
