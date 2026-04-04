"""Tests for range-safety CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from hangar.omd.db import init_analysis_db, record_entity, record_run_case
from hangar.range_safety.cli import cli


def _write_plan(tmp_path: Path, plan: dict) -> Path:
    """Write a plan dict to a YAML file and return its path."""
    plan_path = tmp_path / "plan.yaml"
    with open(plan_path, "w") as f:
        yaml.dump(plan, f)
    return plan_path


def test_validate_valid_plan(isolate_omd_data, valid_aero_plan, catalog_dir):
    """Validate command succeeds for a valid plan."""
    plan_path = _write_plan(isolate_omd_data, valid_aero_plan)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "validate", str(plan_path), "--catalog-dir", str(catalog_dir),
    ])
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] in ("pass", "warn")


def test_validate_bad_plan(isolate_omd_data, catalog_dir):
    """Validate command fails for a plan with errors."""
    bad_plan = {
        "metadata": {"id": "test", "name": "Test", "version": 1},
        "components": [
            {
                "id": "wing",
                "type": "oas/NonexistentType",
                "config": {"surfaces": [{"name": "w", "num_y": 6}]},
            }
        ],
    }
    plan_path = _write_plan(isolate_omd_data, bad_plan)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "validate", str(plan_path), "--catalog-dir", str(catalog_dir),
    ])
    assert result.exit_code == 1
    output = json.loads(result.output)
    assert output["status"] == "fail"
    assert output["error_count"] > 0


def test_assert_good_run(isolate_omd_data, valid_aerostruct_plan):
    """Assert command succeeds for a converged run."""
    db_path = isolate_omd_data / "analysis.db"
    init_analysis_db(db_path)

    run_id = "run-cli-good"
    record_entity(
        entity_id=run_id,
        entity_type="run_record",
        created_by="test",
        plan_id="test-plan",
    )
    record_run_case(run_id, 0, "driver", {"structural_mass": 100.0})
    record_run_case(run_id, 1, "driver", {"structural_mass": 70.0})
    record_run_case(run_id, 2, "final", {
        "structural_mass": 70.0,
        "failure": -0.5,
    })

    plan_path = _write_plan(isolate_omd_data, valid_aerostruct_plan)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "assert", run_id,
        "--plan", str(plan_path),
        "--db", str(db_path),
    ])
    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["status"] == "pass"
