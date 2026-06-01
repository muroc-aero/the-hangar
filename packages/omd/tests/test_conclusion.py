"""Tests for the conclusion artifact (concluding stage).

record_conclusion auto-derives a per-requirement verdict by evaluating the
plan's acceptance criteria against a run's final results, writes a conclusion
entity tied to the run, and emits satisfies/violates edges to the requirement
entities.
"""

from __future__ import annotations

import json

from hangar.omd.db import (
    add_prov_edge,
    init_analysis_db,
    query_entity,
    query_provenance_dag,
    record_entity,
    record_run_case,
)
from hangar.omd.run import record_conclusion, _compare


# ---------------------------------------------------------------------------
# Comparator helper
# ---------------------------------------------------------------------------


def test_compare_operators_and_unjudgeable():
    assert _compare(0.5, ">=", 0.4) is True
    assert _compare(0.02, "<=", 0.01) is False
    assert _compare(None, ">=", 0.4) is None       # missing value
    assert _compare(0.5, ">=", None) is None        # missing threshold
    assert _compare(0.5, "in", [0, 1]) is None      # non-numeric threshold


# ---------------------------------------------------------------------------
# Fixture: a plan with two primary requirements and a recorded run
# ---------------------------------------------------------------------------


_PLAN = {
    "metadata": {"id": "wing-study", "name": "Wing", "version": 1},
    "requirements": [
        {"id": "R1", "text": "cruise lift", "priority": "primary",
         "acceptance_criteria": [{"metric": "CL", "comparator": ">=", "threshold": 0.4}]},
        {"id": "R2", "text": "low drag", "priority": "primary",
         "acceptance_criteria": [{"metric": "CD", "comparator": "<=", "threshold": 0.01}]},
    ],
}


def _setup(db_path, final_data):
    init_analysis_db(db_path)
    plan_id = "wing-study"
    plan_entity = f"{plan_id}/v1"
    record_entity(plan_entity, "plan", "test", plan_id=plan_id, version=1)
    for req in _PLAN["requirements"]:
        record_entity(f"{plan_entity}/req/{req['id']}", "requirement", "test",
                      plan_id=plan_id, version=1, metadata=json.dumps(req))
    run_id = "run-001"
    record_entity(run_id, "run_record", "test", plan_id=plan_id)
    record_run_case(run_id, 0, "final", final_data)
    return plan_id, run_id


def test_conclusion_derives_verdicts_and_writes_edges(tmp_path):
    """R1 satisfied, R2 violated -> overall fails, with matching edges."""
    plan_id, run_id = _setup(tmp_path / "a.db", {"CL": 0.5, "CD": 0.02})

    result = record_conclusion(run_id, _PLAN, plan_id, narrative="drag too high")

    assert result["verdict"] == "fails"
    assert result["narrative"] == "drag too high"
    verdicts = {r["id"]: r["verdict"] for r in result["requirements"]}
    assert verdicts == {"R1": "satisfies", "R2": "violates"}

    # Conclusion entity persisted with metadata.
    ent = query_entity(f"conclusion-{run_id}")
    assert ent is not None and ent["entity_type"] == "conclusion"
    meta = json.loads(ent["metadata"])
    assert meta["verdict"] == "fails"

    # Edges: wasDerivedFrom the run, satisfies R1, violates R2.
    edges = query_provenance_dag(plan_id)["edges"]
    rels = {(e["relation"], e["object_id"]) for e in edges
            if e["subject_id"] == f"conclusion-{run_id}"}
    assert ("wasDerivedFrom", run_id) in rels
    assert ("satisfies", f"{plan_id}/v1/req/R1") in rels
    assert ("violates", f"{plan_id}/v1/req/R2") in rels


def test_conclusion_all_satisfied_meets(tmp_path):
    plan_id, run_id = _setup(tmp_path / "b.db", {"CL": 0.5, "CD": 0.005})
    result = record_conclusion(run_id, _PLAN, plan_id)
    assert result["verdict"] == "meets"
    assert all(r["verdict"] == "satisfies" for r in result["requirements"])


def test_conclusion_unjudgeable_requirement_is_open(tmp_path):
    """A requirement whose metric is absent gets no verdict and no edge."""
    plan_id, run_id = _setup(tmp_path / "c.db", {"CL": 0.5})  # no CD recorded

    result = record_conclusion(run_id, _PLAN, plan_id)
    verdicts = {r["id"]: r["verdict"] for r in result["requirements"]}
    assert verdicts["R1"] == "satisfies"
    assert verdicts["R2"] == "open"          # CD missing -> cannot judge
    # partial: not all satisfied, none violated.
    assert result["verdict"] == "partial"

    edges = query_provenance_dag(plan_id)["edges"]
    objs = {e["object_id"] for e in edges if e["subject_id"] == f"conclusion-{run_id}"}
    assert f"{plan_id}/v1/req/R2" not in objs   # no edge for the open requirement
