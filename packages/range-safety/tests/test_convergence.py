"""Tests for convergence assertions."""

from __future__ import annotations

from pathlib import Path

from hangar.omd.db import (
    init_analysis_db,
    record_entity,
    record_run_case,
)
from hangar.range_safety.assertions.convergence import assert_convergence


def _setup_good_run(db_path: Path) -> str:
    """Insert a converged optimization run into the DB."""
    init_analysis_db(db_path)
    run_id = "run-good-001"
    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="test",
        plan_id="test-plan",
    )
    # Driver cases: objective improving
    record_run_case(run_id, 0, "driver", {
        "structural_mass": 100.0,
        "twist_cp": [5.0, 5.0, 5.0],
    })
    record_run_case(run_id, 1, "driver", {
        "structural_mass": 80.0,
        "twist_cp": [3.0, 4.0, 3.0],
    })
    record_run_case(run_id, 2, "driver", {
        "structural_mass": 70.0,
        "twist_cp": [2.0, 3.0, 2.0],
    })
    # Final case
    record_run_case(run_id, 3, "final", {
        "structural_mass": 70.0,
        "twist_cp": [2.0, 3.0, 2.0],
        "failure": -0.5,
    })
    return run_id


def _setup_bad_run(db_path: Path) -> str:
    """Insert a run with NaN values."""
    init_analysis_db(db_path)
    run_id = "run-bad-001"
    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="test",
        plan_id="test-plan",
    )
    record_run_case(run_id, 0, "final", {
        "structural_mass": None,  # NaN sentinel
        "CL": 0.5,
    })
    return run_id


def test_good_run_passes(isolate_omd_data):
    """Converged run passes all checks."""
    db_path = isolate_omd_data / "analysis.db"
    run_id = _setup_good_run(db_path)
    result = assert_convergence(run_id, db_path=db_path)
    assert result["passed"] is True
    assert all(c["passed"] for c in result["checks"])


def test_nonexistent_run_fails(isolate_omd_data):
    """Missing run ID fails."""
    db_path = isolate_omd_data / "analysis.db"
    init_analysis_db(db_path)
    result = assert_convergence("nonexistent-run", db_path=db_path)
    assert result["passed"] is False
    assert any(c["name"] == "run_exists" and not c["passed"] for c in result["checks"])


def test_nan_values_fail(isolate_omd_data):
    """NaN in final case fails."""
    db_path = isolate_omd_data / "analysis.db"
    run_id = _setup_bad_run(db_path)
    result = assert_convergence(run_id, db_path=db_path)
    assert result["passed"] is False
    assert any(c["name"] == "no_nan_values" and not c["passed"] for c in result["checks"])


def test_objective_worsened_fails(isolate_omd_data):
    """Objective getting worse fails."""
    db_path = isolate_omd_data / "analysis.db"
    init_analysis_db(db_path)
    run_id = "run-worse-001"
    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="test",
        plan_id="test-plan",
    )
    record_run_case(run_id, 0, "driver", {"structural_mass": 50.0})
    record_run_case(run_id, 1, "driver", {"structural_mass": 100.0})
    record_run_case(run_id, 2, "final", {"structural_mass": 100.0})
    result = assert_convergence(run_id, db_path=db_path)
    failed = [c for c in result["checks"] if c["name"] == "objective_improved"]
    assert len(failed) == 1
    assert failed[0]["passed"] is False
