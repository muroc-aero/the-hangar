"""Tests for plan assembly from modular YAML directories."""

from __future__ import annotations

from pathlib import Path

import yaml

from hangar.omd.assemble import assemble_plan, _merge_yaml_files, _compute_content_hash


def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)


def _make_plan_dir(tmp_path: Path) -> Path:
    """Create a minimal valid plan directory."""
    plan_dir = tmp_path / "test-plan"
    plan_dir.mkdir()

    _write_yaml(plan_dir / "metadata.yaml", {
        "id": "test-wing-001",
        "name": "Test Wing",
        "version": 1,
    })

    comp_dir = plan_dir / "components"
    comp_dir.mkdir()
    _write_yaml(comp_dir / "wing.yaml", {
        "id": "wing",
        "type": "oas/AerostructPoint",
        "config": {"surfaces": [{"name": "wing", "num_y": 5}]},
    })

    _write_yaml(plan_dir / "operating_points.yaml", {
        "velocity": 248.136,
        "alpha": 5.0,
        "Mach_number": 0.84,
    })

    return plan_dir


def test_merge_yaml_files(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    plan = _merge_yaml_files(plan_dir)

    assert "metadata" in plan
    assert plan["metadata"]["id"] == "test-wing-001"
    assert "components" in plan
    assert len(plan["components"]) == 1
    assert plan["components"][0]["id"] == "wing"
    assert "operating_points" in plan


def test_merge_optimization_file(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    _write_yaml(plan_dir / "optimization.yaml", {
        "design_variables": [{"name": "twist_cp", "lower": -10, "upper": 15}],
        "constraints": [{"name": "failure", "upper": 0.0}],
        "objective": {"name": "structural_mass", "scaler": 1e-4},
        "optimizer": {"type": "SLSQP"},
    })

    plan = _merge_yaml_files(plan_dir)
    assert "design_variables" in plan
    assert "constraints" in plan
    assert "objective" in plan
    assert "optimizer" in plan


def test_merge_multiple_components(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    comp_dir = plan_dir / "components"
    _write_yaml(comp_dir / "tail.yaml", {
        "id": "tail",
        "type": "oas/AerostructPoint",
        "config": {"surfaces": [{"name": "tail", "num_y": 3}]},
    })

    plan = _merge_yaml_files(plan_dir)
    assert len(plan["components"]) == 2
    ids = {c["id"] for c in plan["components"]}
    assert ids == {"wing", "tail"}


def test_content_hash_deterministic(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    plan = _merge_yaml_files(plan_dir)
    h1 = _compute_content_hash(plan)
    h2 = _compute_content_hash(plan)
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex


def test_content_hash_changes_with_content(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    plan = _merge_yaml_files(plan_dir)
    h1 = _compute_content_hash(plan)

    plan["operating_points"]["alpha"] = 10.0
    h2 = _compute_content_hash(plan)
    assert h1 != h2


def test_assemble_plan(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    result = assemble_plan(plan_dir)

    assert result["errors"] == []
    assert result["version"] == 1
    assert result["content_hash"] is not None
    assert Path(result["output_path"]).exists()

    # Verify assembled plan.yaml is valid YAML
    with open(result["output_path"]) as f:
        assembled = yaml.safe_load(f)
    assert assembled["metadata"]["version"] == 1


def test_assemble_plan_auto_version_increments(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)

    r1 = assemble_plan(plan_dir)
    assert r1["version"] == 1

    r2 = assemble_plan(plan_dir)
    assert r2["version"] == 2

    # Verify history files exist
    assert (plan_dir / "history" / "v1.yaml").exists()
    assert (plan_dir / "history" / "v2.yaml").exists()


def test_assemble_plan_custom_output(tmp_path):
    plan_dir = _make_plan_dir(tmp_path)
    out_path = tmp_path / "output" / "custom.yaml"
    result = assemble_plan(plan_dir, output=out_path)

    assert result["errors"] == []
    assert out_path.exists()


def test_assemble_plan_parent_version(tmp_path):
    """Second assembly sets parent_version pointing to v1."""
    plan_dir = _make_plan_dir(tmp_path)

    r1 = assemble_plan(plan_dir)
    assert r1["version"] == 1
    assert "parent_version" not in r1["plan"].get("metadata", {})

    r2 = assemble_plan(plan_dir)
    assert r2["version"] == 2
    assert r2["plan"]["metadata"]["parent_version"] == 1


def test_assemble_plan_validation_error(tmp_path):
    plan_dir = tmp_path / "bad-plan"
    plan_dir.mkdir()

    # Missing components -- only metadata
    _write_yaml(plan_dir / "metadata.yaml", {
        "id": "bad",
        "name": "Bad Plan",
        "version": 1,
    })

    result = assemble_plan(plan_dir)
    assert len(result["errors"]) > 0
    assert result["version"] is None


# ---------------------------------------------------------------------------
# Enriched-plan provenance recording
# ---------------------------------------------------------------------------


def _fetch_entities(db_path: Path, entity_type: str):
    import sqlite3
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            rows = conn.execute(
                "SELECT entity_id, metadata FROM entities WHERE entity_type = ?",
                (entity_type,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    return rows


def _fetch_edges(db_path: Path, relation: str):
    import sqlite3
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            rows = conn.execute(
                "SELECT subject_id, object_id FROM prov_edges WHERE relation = ?",
                (relation,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    return rows


def test_assemble_enriched_fixture_records_graph(fixtures_dir, tmp_path, monkeypatch):
    """End-to-end: enriched fixture -> provenance DB -> new entities / edges."""
    db_path = tmp_path / "analysis.db"
    monkeypatch.setenv("OMD_DB_PATH", str(db_path))

    # Work on a copy to avoid touching the tracked fixture's history/.
    import shutil
    work_dir = tmp_path / "enriched"
    shutil.copytree(fixtures_dir / "oas_aerostruct_enriched", work_dir)

    result = assemble_plan(work_dir)
    assert result["errors"] == []

    # New entity types
    phase_rows = _fetch_entities(db_path, "phase")
    assert len(phase_rows) == 2
    req_rows = _fetch_entities(db_path, "requirement")
    assert len(req_rows) == 2
    crit_rows = _fetch_entities(db_path, "acceptance_criterion")
    assert len(crit_rows) == 2
    elem_rows = _fetch_entities(db_path, "plan_element")
    # Three decisions all have element_path -> at least three plan_element rows
    assert len(elem_rows) >= 3

    # New edges
    justifies = _fetch_edges(db_path, "justifies")
    assert len(justifies) >= 3
    precedes = _fetch_edges(db_path, "precedes")
    # phase-1 -> phase-2 depends_on -> one precedes edge
    assert len(precedes) == 1
    has_crit = _fetch_edges(db_path, "has_criterion")
    assert len(has_crit) == 2


def test_assemble_non_enriched_plan_records_no_new_entities(tmp_path, monkeypatch):
    """Regression: plans without the new fields produce no new entities."""
    db_path = tmp_path / "analysis.db"
    monkeypatch.setenv("OMD_DB_PATH", str(db_path))

    plan_dir = _make_plan_dir(tmp_path)
    assemble_plan(plan_dir)

    assert _fetch_entities(db_path, "phase") == []
    assert _fetch_entities(db_path, "requirement") == []
    assert _fetch_entities(db_path, "acceptance_criterion") == []
    assert _fetch_entities(db_path, "plan_element") == []
    assert _fetch_edges(db_path, "justifies") == []
    assert _fetch_edges(db_path, "precedes") == []
    assert _fetch_edges(db_path, "has_criterion") == []
