"""Evaluation test: Provenance chain (Eval 8).

Verifies the PROV-Agent DAG is correctly recorded after a run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan
from hangar.omd.db import init_analysis_db, query_provenance_dag

pytestmark = [pytest.mark.eval]

FIXTURES = Path(__file__).parent / "fixtures"


def test_provenance_chain(tmp_path):
    """After a run, the DAG has plan entity + run entity + execute activity + edges."""
    db_path = tmp_path / "analysis.db"
    plan_dir = FIXTURES / "paraboloid_analysis"
    out = tmp_path / "plan.yaml"
    assemble_plan(plan_dir, output=out)

    result = run_plan(out, mode="analysis",
                      recording_level="minimal",
                      db_path=db_path)

    assert result["status"] == "completed"
    run_id = result["run_id"]

    dag = query_provenance_dag("plan-paraboloid-analysis")

    # Should have at least 2 entities: plan + run_record
    entity_types = {e["entity_type"] for e in dag["entities"]}
    assert "plan" in entity_types
    assert "run_record" in entity_types

    # Should have at least 1 activity: execute
    activity_types = {a["activity_type"] for a in dag["activities"]}
    assert "execute" in activity_types

    # Should have at least 2 edges: used + wasGeneratedBy
    relations = {e["relation"] for e in dag["edges"]}
    assert "used" in relations
    assert "wasGeneratedBy" in relations

    # Run entity should match our run_id
    run_entities = [e for e in dag["entities"] if e["entity_type"] == "run_record"]
    assert any(e["entity_id"] == run_id for e in run_entities)

    # All timestamps should be valid ISO format
    for entity in dag["entities"]:
        assert entity["created_at"] is not None
        assert "T" in entity["created_at"]
