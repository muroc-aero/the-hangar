"""
Unit tests for ArtifactStore.

Migrated from: OpenAeroStruct/oas_mcp/tests/test_artifacts.py

No OpenAeroStruct or OpenMDAO required -- these tests only exercise
hangar.sdk.artifacts.store and run instantly.

Import mapping applied:
  - oas_mcp.core.artifacts -> hangar.sdk.artifacts.store
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from hangar.sdk.artifacts.store import ARTIFACT_SCHEMA_VERSION, ArtifactStore, _make_run_id


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


def test_save_returns_non_empty_run_id(store):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5})
    assert run_id and isinstance(run_id, str)


def test_save_creates_artifact_file(store, tmp_path):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5})
    artifact_file = tmp_path / "default" / "default" / "s1" / f"{run_id}.json"
    assert artifact_file.exists()


def test_save_artifact_contains_metadata_and_results(store, tmp_path):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {"alpha": 5.0}, {"CL": 0.5, "CD": 0.02}
    )
    with (tmp_path / "default" / "default" / "s1" / f"{run_id}.json").open() as f:
        data = json.load(f)

    assert data["metadata"]["run_id"] == run_id
    assert data["metadata"]["analysis_type"] == "aero"
    assert data["metadata"]["tool_name"] == "run_aero_analysis"
    assert data["metadata"]["surfaces"] == ["wing"]
    assert data["metadata"]["parameters"] == {"alpha": 5.0}
    assert data["metadata"]["user"] == "default"
    assert data["metadata"]["project"] == "default"
    assert data["results"]["CL"] == pytest.approx(0.5)
    assert data["results"]["CD"] == pytest.approx(0.02)


def test_save_creates_index_entry(store, tmp_path):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    index_file = tmp_path / "default" / "default" / "s1" / "index.json"
    assert index_file.exists()
    with index_file.open() as f:
        index = json.load(f)
    assert any(e["run_id"] == run_id for e in index)


def test_save_with_user_and_project(store, tmp_path):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {}, {},
        user="alice", project="proj1",
    )
    artifact_file = tmp_path / "alice" / "proj1" / "s1" / f"{run_id}.json"
    assert artifact_file.exists()
    with artifact_file.open() as f:
        data = json.load(f)
    assert data["metadata"]["user"] == "alice"
    assert data["metadata"]["project"] == "proj1"


def test_save_with_name(store, tmp_path):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {}, {},
        name="baseline",
    )
    with (tmp_path / "default" / "default" / "s1" / f"{run_id}.json").open() as f:
        data = json.load(f)
    assert data["metadata"]["name"] == "baseline"

    # name should appear in index entry too
    index_file = tmp_path / "default" / "default" / "s1" / "index.json"
    with index_file.open() as f:
        index = json.load(f)
    entry = next(e for e in index if e["run_id"] == run_id)
    assert entry["name"] == "baseline"


def test_save_with_validation_and_telemetry(store, tmp_path):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5},
        validation={"passed": True, "findings": []},
        telemetry={"elapsed_s": 0.1},
    )
    with (tmp_path / "default" / "default" / "s1" / f"{run_id}.json").open() as f:
        data = json.load(f)
    assert data["validation"] == {"passed": True, "findings": []}
    assert data["telemetry"] == {"elapsed_s": 0.1}


def test_save_with_pregenerated_run_id(store, tmp_path):
    pre_id = _make_run_id()
    returned_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {}, {}, run_id=pre_id
    )
    assert returned_id == pre_id
    artifact_file = tmp_path / "default" / "default" / "s1" / f"{pre_id}.json"
    assert artifact_file.exists()


def test_save_deduplicates_index(store, tmp_path):
    """Calling save twice with the same run_id should not create duplicate index entries."""
    pre_id = _make_run_id()
    store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5}, run_id=pre_id)
    store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.6}, run_id=pre_id)

    index_file = tmp_path / "default" / "default" / "s1" / "index.json"
    with index_file.open() as f:
        index = json.load(f)
    matching = [e for e in index if e["run_id"] == pre_id]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_all_sessions(store):
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    r2 = store.save("s1", "drag_polar", "compute_drag_polar", ["wing"], {}, {})
    r3 = store.save("s2", "aerostruct", "run_aerostruct_analysis", ["wing"], {}, {})

    ids = {e["run_id"] for e in store.list()}
    assert {r1, r2, r3} <= ids


def test_list_filter_by_session(store):
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    r2 = store.save("s2", "aero", "run_aero_analysis", ["wing"], {}, {})

    ids = {e["run_id"] for e in store.list(session_id="s1")}
    assert r1 in ids
    assert r2 not in ids


def test_list_filter_by_analysis_type(store):
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    r2 = store.save("s1", "drag_polar", "compute_drag_polar", ["wing"], {}, {})

    ids = {e["run_id"] for e in store.list(session_id="s1", analysis_type="aero")}
    assert r1 in ids
    assert r2 not in ids


def test_list_filter_by_user_and_project(store):
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {}, user="alice", project="p1")
    r2 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {}, user="bob", project="p2")

    alice_ids = {e["run_id"] for e in store.list(user="alice")}
    assert r1 in alice_ids
    assert r2 not in alice_ids

    p1_ids = {e["run_id"] for e in store.list(project="p1")}
    assert r1 in p1_ids
    assert r2 not in p1_ids


def test_list_empty_session(store):
    entries = store.list(session_id="no_such_session")
    assert entries == []


# ---------------------------------------------------------------------------
# get / get_summary
# ---------------------------------------------------------------------------


def test_get_full_artifact(store):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {"alpha": 5.0}, {"CL": 0.5})
    artifact = store.get(run_id, session_id="s1")

    assert artifact is not None
    assert artifact["metadata"]["run_id"] == run_id
    assert artifact["results"]["CL"] == pytest.approx(0.5)


def test_get_without_session_hint(store):
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.3})
    r2 = store.save("s2", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.7})

    assert store.get(r1) is not None
    assert store.get(r2) is not None


def test_get_not_found(store):
    assert store.get("nonexistent_run_id", session_id="s1") is None


def test_get_summary_contains_metadata_only(store):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {"alpha": 5.0}, {"CL": 0.5})
    summary = store.get_summary(run_id, session_id="s1")

    assert summary is not None
    assert summary["run_id"] == run_id
    assert "results" not in summary


def test_get_summary_not_found(store):
    assert store.get_summary("bad_id", session_id="s1") is None


def test_get_artifact_with_validation_and_telemetry(store):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5},
        validation={"passed": True},
        telemetry={"elapsed_s": 0.05},
    )
    artifact = store.get(run_id)
    assert artifact["validation"] == {"passed": True}
    assert artifact["telemetry"] == {"elapsed_s": 0.05}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_file_and_index_entry(store, tmp_path):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    artifact_file = tmp_path / "default" / "default" / "s1" / f"{run_id}.json"
    assert artifact_file.exists()

    deleted = store.delete(run_id, session_id="s1")
    assert deleted is True
    assert not artifact_file.exists()

    with (tmp_path / "default" / "default" / "s1" / "index.json").open() as f:
        index = json.load(f)
    assert all(e["run_id"] != run_id for e in index)


def test_delete_without_session_hint(store, tmp_path):
    run_id = store.save("s2", "aero", "run_aero_analysis", ["wing"], {}, {})
    deleted = store.delete(run_id)
    assert deleted is True
    assert not (tmp_path / "default" / "default" / "s2" / f"{run_id}.json").exists()


def test_delete_not_found(store):
    assert store.delete("nonexistent_id", session_id="s1") is False


# ---------------------------------------------------------------------------
# numpy serialisation
# ---------------------------------------------------------------------------


def test_numpy_array_serialised_to_list(store, tmp_path):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {},
        {"array": np.array([1.0, 2.0, 3.0])},
    )
    with (tmp_path / "default" / "default" / "s1" / f"{run_id}.json").open() as f:
        data = json.load(f)
    assert data["results"]["array"] == [1.0, 2.0, 3.0]


def test_numpy_scalar_serialised(store, tmp_path):
    run_id = store.save(
        "s1", "aero", "run_aero_analysis", ["wing"], {},
        {"scalar": np.float64(0.42), "int_val": np.int32(7)},
    )
    with (tmp_path / "default" / "default" / "s1" / f"{run_id}.json").open() as f:
        data = json.load(f)
    assert data["results"]["scalar"] == pytest.approx(0.42)
    assert data["results"]["int_val"] == 7


# ---------------------------------------------------------------------------
# index self-healing
# ---------------------------------------------------------------------------


def test_index_rebuilt_when_missing(store, tmp_path):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.6})
    # Delete the index file
    (tmp_path / "default" / "default" / "s1" / "index.json").unlink()

    entries = store.list(session_id="s1")
    assert any(e["run_id"] == run_id for e in entries)


def test_index_rebuilt_when_corrupt(store, tmp_path):
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.6})
    # Corrupt the index
    (tmp_path / "default" / "default" / "s1" / "index.json").write_text("not valid json {{{")

    entries = store.list(session_id="s1")
    assert any(e["run_id"] == run_id for e in entries)


def test_rebuild_index_deduplicates(store, tmp_path):
    """_rebuild_index should not produce duplicate run_id entries."""
    pre_id = _make_run_id()
    # Write the artifact file manually (simulating a previous crash mid-index-update)
    store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {}, run_id=pre_id)

    # Corrupt/delete the index to force a rebuild
    (tmp_path / "default" / "default" / "s1" / "index.json").unlink()

    entries = store.list(session_id="s1")
    matching = [e for e in entries if e["run_id"] == pre_id]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# path traversal prevention
# ---------------------------------------------------------------------------


def test_path_traversal_in_project_rejected(store):
    with pytest.raises(ValueError, match="unsafe characters"):
        store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {},
                   user="alice", project="../../etc")


def test_path_traversal_in_session_id_rejected(store):
    with pytest.raises(ValueError, match="unsafe characters"):
        store.save("../../../tmp", "aero", "run_aero_analysis", ["wing"], {}, {},
                   user="alice", project="default")


def test_slash_in_user_rejected(store):
    with pytest.raises(ValueError, match="unsafe characters"):
        store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {},
                   user="alice/bob", project="default")


# ---------------------------------------------------------------------------
# run_id entropy
# ---------------------------------------------------------------------------


def test_run_id_has_sufficient_entropy():
    """run_id suffix should be at least 16 hex chars (8 bytes)."""
    rid = _make_run_id()
    suffix = rid.split("_", 1)[1]
    assert len(suffix) >= 16


# ---------------------------------------------------------------------------
# user scoping
# ---------------------------------------------------------------------------


def test_get_scoped_to_user(store):
    """get() with user filter cannot access another user's artifact."""
    rid = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5},
                     user="alice", project="p1")
    # alice can access
    assert store.get(rid, user="alice") is not None
    # bob cannot
    assert store.get(rid, user="bob") is None


def test_delete_scoped_to_user(store):
    """delete() with user filter cannot delete another user's artifact."""
    rid = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {},
                     user="alice", project="p1")
    # bob's delete fails
    assert store.delete(rid, user="bob") is False
    # artifact still exists for alice
    assert store.get(rid, user="alice") is not None


# ---------------------------------------------------------------------------
# artifact schema versioning
# ---------------------------------------------------------------------------


def test_save_includes_artifact_schema_version(store, tmp_path):
    """Saved artifacts should contain artifact_schema_version at the top level."""
    run_id = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"CL": 0.5})
    with (tmp_path / "default" / "default" / "s1" / f"{run_id}.json").open() as f:
        data = json.load(f)
    assert data["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION


def test_get_migrates_legacy_artifact(store, tmp_path):
    """Artifacts written without artifact_schema_version should be treated as 1.0."""
    # Manually write a legacy artifact (no version key)
    session_dir = tmp_path / "default" / "default" / "s1"
    session_dir.mkdir(parents=True)
    run_id = "20260101T000000_legacy00000000"
    legacy = {
        "metadata": {
            "run_id": run_id,
            "session_id": "s1",
            "user": "default",
            "project": "default",
            "analysis_type": "aero",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "surfaces": ["wing"],
            "tool_name": "run_aero_analysis",
            "parameters": {},
        },
        "results": {"CL": 0.42},
    }
    with (session_dir / f"{run_id}.json").open("w") as f:
        json.dump(legacy, f)

    artifact = store.get(run_id, session_id="s1")
    assert artifact is not None
    assert artifact["artifact_schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# cleanup (retention policy)
# ---------------------------------------------------------------------------


def test_cleanup_max_count(store):
    """cleanup with max_count should delete the oldest artifacts."""
    ids = []
    for i in range(5):
        rid = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"i": i})
        ids.append(rid)

    deleted = store.cleanup("default", "default", "s1", max_count=3)
    assert len(deleted) == 2
    # Exactly 3 should remain
    remaining = store.list(session_id="s1")
    assert len(remaining) == 3
    # Deleted and remaining should partition the original set
    remaining_ids = {e["run_id"] for e in remaining}
    assert remaining_ids | set(deleted) == set(ids)
    assert remaining_ids & set(deleted) == set()


def test_cleanup_noop_under_limit(store):
    """cleanup should not delete anything when count is under the limit."""
    for _ in range(2):
        store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})

    deleted = store.cleanup("default", "default", "s1", max_count=5)
    assert deleted == []
    assert len(store.list(session_id="s1")) == 2


def test_cleanup_returns_deleted_ids(store):
    """cleanup should return the run_ids of deleted artifacts."""
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    r2 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    r3 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})

    deleted = store.cleanup("default", "default", "s1", max_count=1)
    assert len(deleted) == 2
    # Exactly one should survive
    all_ids = {r1, r2, r3}
    survived = all_ids - set(deleted)
    assert len(survived) == 1
    # Deleted files are actually gone; survivor still exists
    for rid in deleted:
        assert store.get(rid) is None
    for rid in survived:
        assert store.get(rid) is not None


def test_cleanup_max_age(store, tmp_path):
    """cleanup with max_age_days=0 should delete all artifacts (they're all 'old')."""
    r1 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    r2 = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})

    # max_age_days=0 means cutoff = now, so all artifacts with timestamp < now are deleted
    deleted = store.cleanup("default", "default", "s1", max_age_days=0)
    assert len(deleted) == 2
    assert store.list(session_id="s1") == []


def test_cleanup_no_args_is_noop(store):
    """cleanup with neither max_count nor max_age_days does nothing."""
    store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {})
    deleted = store.cleanup("default", "default", "s1")
    assert deleted == []


def test_cleanup_respects_protected_run_ids(store):
    """Protected run_ids should never be deleted by cleanup."""
    ids = []
    for i in range(5):
        rid = store.save("s1", "aero", "run_aero_analysis", ["wing"], {}, {"i": i})
        ids.append(rid)

    # Sort to know which are "oldest" by run_id
    sorted_ids = sorted(ids)
    # Protect the oldest run_id -- it would normally be deleted
    protected = {sorted_ids[0]}

    deleted = store.cleanup("default", "default", "s1", max_count=3,
                            protected_run_ids=protected)
    assert sorted_ids[0] not in deleted  # protected, not deleted
    assert len(deleted) == 2  # still deletes 2 to reach max_count=3
    # Protected run still exists
    assert store.get(sorted_ids[0], session_id="s1") is not None


class TestJsonSafety:
    def test_inf_nan_sanitized_in_artifact_file(self, tmp_path):
        """inf/nan must not produce the invalid Infinity/NaN JSON literals."""
        store = ArtifactStore(data_dir=tmp_path)
        run_id = store.save(
            session_id="s1",
            analysis_type="aero",
            tool_name="t",
            surfaces=["wing"],
            parameters={"alpha": float("inf")},
            results={"CD": float("nan"), "arr": np.array([1.0, float("inf")])},
        )
        path = next((tmp_path / "default" / "default" / "s1").glob(f"{run_id}.json"))
        raw = path.read_text()
        assert "Infinity" not in raw
        assert "NaN" not in raw
        loaded = json.loads(raw)  # strict parser must accept it
        assert loaded["results"]["CD"] is None
        assert loaded["results"]["arr"] == [1.0, None]

    def test_get_continues_past_corrupt_file(self, tmp_path):
        """A corrupt artifact in one session dir must not hide a valid one elsewhere."""
        store = ArtifactStore(data_dir=tmp_path)
        run_id = store.save(
            session_id="s2",
            analysis_type="aero",
            tool_name="t",
            surfaces=[],
            parameters={},
            results={"CL": 0.5},
        )
        # Plant a corrupt file with the same run_id in a session dir that
        # sorts earlier than s2.
        bad_dir = tmp_path / "default" / "default" / "a_corrupt"
        bad_dir.mkdir(parents=True)
        (bad_dir / f"{run_id}.json").write_text("{not valid json")

        artifact = store.get(run_id)
        assert artifact is not None
        assert artifact["results"]["CL"] == 0.5
