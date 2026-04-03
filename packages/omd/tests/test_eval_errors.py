"""Evaluation test: Error handling (Eval 10).

Verifies structured error messages for bad plans.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hangar.omd.plan_schema import validate_plan, load_and_validate
from hangar.omd.run import run_plan

pytestmark = [pytest.mark.eval]


def test_missing_required_field(tmp_path):
    """Missing metadata produces structured error with field path."""
    plan = {"components": [{"id": "x", "type": "t", "config": {}}]}
    errors = validate_plan(plan)
    assert len(errors) >= 1
    assert any("metadata" in e["message"] for e in errors)
    # Each error has path and message keys
    for e in errors:
        assert "path" in e
        assert "message" in e


def test_unknown_component_type(tmp_path):
    """Unknown type gives structured error listing available types."""
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(yaml.dump({
        "metadata": {"id": "x", "name": "x", "version": 1},
        "components": [{"id": "c", "type": "nonexistent/Widget", "config": {}}],
    }))
    result = run_plan(plan_path, db_path=tmp_path / "analysis.db")
    assert result["status"] == "failed"
    assert len(result["errors"]) >= 1
    # Error should mention the unknown type
    assert any("nonexistent" in e["message"] for e in result["errors"])


def test_schema_validation_error(tmp_path):
    """Schema violation gives error with field path."""
    plan = {
        "metadata": {"id": "x", "name": "x", "version": "not_an_int"},
        "components": [{"id": "c", "type": "t", "config": {}}],
    }
    errors = validate_plan(plan)
    assert len(errors) >= 1
    assert any("version" in e["path"] for e in errors)


def test_invalid_yaml(tmp_path):
    """Non-dict YAML gives structured error."""
    plan_path = tmp_path / "bad.yaml"
    plan_path.write_text("- just\n- a\n- list\n")
    result = run_plan(plan_path, db_path=tmp_path / "analysis.db")
    assert result["status"] == "failed"
    assert len(result["errors"]) >= 1


def test_empty_components(tmp_path):
    """Empty components array gives structured error."""
    plan_path = tmp_path / "empty.yaml"
    plan_path.write_text(yaml.dump({
        "metadata": {"id": "x", "name": "x", "version": 1},
        "components": [],
    }))
    result = run_plan(plan_path, db_path=tmp_path / "analysis.db")
    assert result["status"] == "failed"
