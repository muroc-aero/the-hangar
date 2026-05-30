"""Tests for provenance visualization."""

from __future__ import annotations

from pathlib import Path

import yaml

from hangar.omd.db import (
    init_analysis_db,
    record_entity,
    record_activity,
    add_prov_edge,
)
from hangar.omd.provenance import (
    build_provenance_elements,
    provenance_timeline,
    provenance_dag_html,
    provenance_diff,
)


def _setup_dag(tmp_path):
    """Create a multi-version provenance scenario."""
    db_path = tmp_path / "test.db"
    init_analysis_db(db_path)

    # Plan v1
    plan_v1 = tmp_path / "plan_v1.yaml"
    plan_v1.write_text(yaml.dump({
        "metadata": {"id": "test-plan", "name": "Test", "version": 1},
        "components": [{"id": "wing", "type": "oas/AerostructPoint", "config": {}}],
        "operating_points": {"alpha": 5.0},
    }))

    record_entity("test-plan/v1", "plan", "have-agent",
                   plan_id="test-plan", version=1, content_hash="abc",
                   storage_ref=str(plan_v1))

    # Draft activity
    record_activity("act-draft-001", "draft", "have-agent")
    add_prov_edge("wasGeneratedBy", "test-plan/v1", "act-draft-001")

    # Validate
    record_activity("act-validate-001", "validate", "range-safety")
    add_prov_edge("used", "act-validate-001", "test-plan/v1")

    # Execute
    record_activity("act-exec-001", "execute", "omd")
    add_prov_edge("used", "act-exec-001", "test-plan/v1")
    record_entity("run-001", "run_record", "omd", plan_id="test-plan")
    add_prov_edge("wasGeneratedBy", "run-001", "act-exec-001")

    # Plan v2 (revised)
    plan_v2 = tmp_path / "plan_v2.yaml"
    plan_v2.write_text(yaml.dump({
        "metadata": {"id": "test-plan", "name": "Test", "version": 2},
        "components": [{"id": "wing", "type": "oas/AerostructPoint", "config": {}}],
        "operating_points": {"alpha": 7.0},
    }))

    record_entity("test-plan/v2", "plan", "have-agent",
                   plan_id="test-plan", version=2, content_hash="def",
                   storage_ref=str(plan_v2))
    add_prov_edge("wasDerivedFrom", "test-plan/v2", "test-plan/v1")

    return db_path


def test_provenance_timeline(tmp_path):
    db_path = _setup_dag(tmp_path)
    text = provenance_timeline("test-plan", db_path=db_path)

    assert "test-plan" in text
    assert "DRAFT" in text
    assert "EXECUTE" in text
    assert "run-001" in text


def test_provenance_timeline_empty(tmp_path):
    db_path = tmp_path / "empty.db"
    init_analysis_db(db_path)
    text = provenance_timeline("nonexistent", db_path=db_path)
    assert "No provenance found" in text


def test_provenance_dag_html(tmp_path):
    db_path = _setup_dag(tmp_path)
    output = tmp_path / "dag.html"
    result = provenance_dag_html("test-plan", output, db_path=db_path)

    assert result.exists()
    content = result.read_text()
    assert "cytoscape" in content
    assert "test-plan" in content


def test_build_provenance_elements(tmp_path):
    db_path = _setup_dag(tmp_path)
    elements = build_provenance_elements("test-plan", db_path=db_path)

    assert set(elements) == {"nodes", "edges"}
    # Cytoscape-native element form: every element is {"data": {...}}.
    node_ids = {n["data"]["id"] for n in elements["nodes"]}
    assert "test-plan/v1" in node_ids and "run-001" in node_ids

    # Plan entities carry an entity_type; activities are typed too.
    plan_node = next(n["data"] for n in elements["nodes"] if n["data"]["id"] == "test-plan/v1")
    assert plan_node["entity_type"] == "plan"

    # No edge references a missing node (dangling edges are dropped).
    for e in elements["edges"]:
        assert e["data"]["source"] in node_ids
        assert e["data"]["target"] in node_ids

    # The wasDerivedFrom replan edge is present (reversed for layout: old->new).
    derived = [e["data"] for e in elements["edges"] if e["data"]["relation"] == "wasDerivedFrom"]
    assert derived and derived[0]["source"] == "test-plan/v1" and derived[0]["target"] == "test-plan/v2"


def test_provenance_diff(tmp_path):
    db_path = _setup_dag(tmp_path)
    result = provenance_diff("test-plan", 1, 2, db_path=db_path)

    assert result["plan_id"] == "test-plan"
    assert result["version_a"] == 1
    assert result["version_b"] == 2
    assert result["content_changed"] is True
    # operating_points changed from alpha=5.0 to alpha=7.0
    assert any(c["key"] == "operating_points" and c["action"] == "modified"
               for c in result["changes"])


def test_provenance_diff_missing_version(tmp_path):
    db_path = _setup_dag(tmp_path)
    result = provenance_diff("test-plan", 1, 99, db_path=db_path)
    assert result["entity_b"] is None
