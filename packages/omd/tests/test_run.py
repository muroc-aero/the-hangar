"""Tests for plan execution (omd run)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hangar.omd.run import run_plan
from hangar.omd.db import init_analysis_db, query_provenance_dag, query_run_results


def _write_plan(tmp_path: Path) -> Path:
    """Write a minimal OAS aerostruct plan to a temp file."""
    plan = {
        "metadata": {"id": "test-run", "name": "Test Run", "version": 1},
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
    plan_path = tmp_path / "plan.yaml"
    with open(plan_path, "w") as f:
        yaml.dump(plan, f)
    return plan_path


@pytest.mark.slow
def test_run_analysis(tmp_path):
    """Run a complete analysis and verify results are recorded."""
    db_path = tmp_path / "analysis.db"
    plan_path = _write_plan(tmp_path)

    result = run_plan(plan_path, mode="analysis",
                      recording_level="minimal", db_path=db_path)

    assert result["status"] == "completed"
    assert result["run_id"] is not None
    assert result["errors"] == []
    assert result["summary"]["CL"] > 0
    assert result["summary"]["CD"] > 0

    # Verify provenance was recorded
    dag = query_provenance_dag("test-run")
    assert len(dag["entities"]) >= 2  # plan + run_record
    assert len(dag["activities"]) >= 1  # execute
    assert len(dag["edges"]) >= 2  # used, wasGeneratedBy


@pytest.mark.slow
def test_run_invalid_plan(tmp_path):
    """Run with an invalid plan YAML."""
    db_path = tmp_path / "analysis.db"
    bad_plan = tmp_path / "bad.yaml"
    bad_plan.write_text(yaml.dump({"metadata": {"id": "x"}}))

    result = run_plan(bad_plan, db_path=db_path)
    assert result["status"] == "failed"
    assert len(result["errors"]) > 0


def _write_ocp_plan(tmp_path: Path, num_nodes: int = 3) -> Path:
    """Write a minimal OCP BasicMission plan."""
    plan = {
        "metadata": {"id": "test-ocp-profile", "name": "Profile Test", "version": 1},
        "components": [
            {
                "id": "mission",
                "type": "ocp/BasicMission",
                "config": {
                    "aircraft_template": "caravan",
                    "architecture": "turboprop",
                    "num_nodes": num_nodes,
                    "mission_params": {
                        "cruise_altitude_ft": 18000,
                        "mission_range_NM": 250,
                        "climb_vs_ftmin": 850,
                        "climb_Ueas_kn": 104,
                        "cruise_Ueas_kn": 129,
                        "descent_vs_ftmin": 400,
                        "descent_Ueas_kn": 100,
                    },
                },
            }
        ],
        "solvers": {
            "nonlinear": {"type": "NewtonSolver", "options": {"maxiter": 20}},
            "linear": {"type": "DirectSolver"},
        },
    }
    plan_path = tmp_path / "plan.yaml"
    with open(plan_path, "w") as f:
        yaml.dump(plan, f)
    return plan_path


@pytest.mark.slow
def test_ocp_profile_extraction(tmp_path):
    """Verify per-phase profiles are extracted from OCP missions."""
    db_path = tmp_path / "analysis.db"
    plan_path = _write_ocp_plan(tmp_path, num_nodes=3)

    result = run_plan(plan_path, mode="analysis",
                      recording_level="minimal", db_path=db_path)

    assert result["status"] == "completed", result.get("errors", [])
    summary = result["summary"]
    assert "profiles" in summary, f"No profiles in summary: {list(summary.keys())}"

    profiles = summary["profiles"]
    for phase in ["climb", "cruise", "descent"]:
        assert phase in profiles, f"Missing phase {phase} in profiles"
        phase_data = profiles[phase]
        assert "altitude_m" in phase_data
        assert "thrust_kN" in phase_data
        assert "drag_N" in phase_data
        # Each array should have num_nodes elements
        assert len(phase_data["altitude_m"]) == 3
