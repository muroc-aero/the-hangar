"""Tests for hangar.omd.plan_review completeness checker."""

from __future__ import annotations

import json
import shutil

from hangar.omd.assemble import assemble_plan
from hangar.omd.plan_review import (
    format_findings_json,
    format_findings_text,
    review_plan,
    review_plan_file,
)


def _assemble(fixtures_dir, tmp_path, name):
    """Copy a fixture to tmp and assemble it. Return (plan_dir, plan)."""
    work = tmp_path / name
    shutil.copytree(fixtures_dir / name, work)
    result = assemble_plan(work)
    assert result["errors"] == [], result["errors"]
    return work, result["plan"]


def test_enriched_fixture_has_no_warn_or_missing(fixtures_dir, tmp_path):
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_enriched")
    findings = review_plan(plan)
    warns_and_missing = [f for f in findings
                         if f.severity in {"WARN", "MISSING"}]
    assert not warns_and_missing, [
        f"{f.section}/{f.severity}: {f.message}" for f in warns_and_missing
    ]


def test_standard_fixture_reports_missing_sections(fixtures_dir, tmp_path):
    """The existing unenriched fixtures should produce MISSING + WARN findings."""
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_optimization")
    findings = review_plan(plan)
    sections = {f.section for f in findings}
    # analysis_plan is expected to be missing
    assert "analysis_plan" in sections
    # rationale is missing in this fixture
    assert "rationale" in sections


def test_decision_without_element_path_warns(fixtures_dir, tmp_path):
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_optimization")
    # Inject a decision without element_path and re-run.
    plan["decisions"] = [{
        "id": "dec-x",
        "decision": "something",
        "rationale": "reason",
        "stage": "mesh_selection",
    }]
    findings = review_plan(plan)
    assert any(f.section == "graph" and "element_path" in f.message
               for f in findings)


def test_unresolvable_element_path_warns(fixtures_dir, tmp_path):
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_enriched")
    plan["decisions"].append({
        "id": "dec-bad",
        "stage": "mesh_selection",
        "decision": "x",
        "element_path": "components[nonexistent].config.num_y",
    })
    findings = review_plan(plan)
    assert any(f.section == "graph" and "unresolvable" in f.message
               for f in findings)


def test_phase_depends_on_unknown_phase_is_error(fixtures_dir, tmp_path):
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_enriched")
    plan["analysis_plan"]["phases"].append({
        "id": "phase-3",
        "depends_on": ["phase-does-not-exist"],
    })
    findings = review_plan(plan)
    assert any(f.section == "analysis_plan" and f.severity == "ERROR"
               for f in findings)


def test_unusual_stage_warns(fixtures_dir, tmp_path):
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_enriched")
    plan["decisions"].append({
        "id": "dec-unusual",
        "stage": "completely_made_up_stage",
        "decision": "x",
        "element_path": "objective",
    })
    findings = review_plan(plan)
    assert any(
        f.section == "decisions"
        and "outside the recommended set" in f.message
        for f in findings
    )


def test_format_text_and_json_shape(fixtures_dir, tmp_path):
    _, plan = _assemble(fixtures_dir, tmp_path, "oas_aerostruct_optimization")
    findings = review_plan(plan)
    text = format_findings_text(plan, findings)
    assert "Plan: plan-oas-aerostruct-opt" in text
    payload = json.loads(format_findings_json(plan, findings))
    assert payload["plan_id"] == "plan-oas-aerostruct-opt"
    assert payload["summary"]["total"] == len(findings)


def test_review_plan_file_on_directory(fixtures_dir, tmp_path):
    work = tmp_path / "enriched"
    shutil.copytree(fixtures_dir / "oas_aerostruct_enriched", work)
    assemble_plan(work)
    plan, findings = review_plan_file(work)
    assert plan["metadata"]["id"] == "plan-oas-aerostruct-enriched"
    assert all(f.severity not in {"WARN", "MISSING"} for f in findings)
