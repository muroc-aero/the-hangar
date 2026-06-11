"""Tests for the results-reader DB seam: init idempotence and user scoping."""

from __future__ import annotations

from hangar.results_reader import db


def _insert_entity(entity_id, plan_id, user=None, entity_type="plan"):
    conn = db._get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO entities "
        "(entity_id, entity_type, created_at, created_by, plan_id, user) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (entity_id, entity_type, db._now(), "test", plan_id, user),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# init_analysis_db idempotence
# ---------------------------------------------------------------------------


class TestInitIdempotence:
    def test_same_path_keeps_thread_local_connections(self, tmp_path):
        """Re-init at the same path must not orphan existing connections."""
        path = tmp_path / "analysis.db"
        db.init_analysis_db(path)
        conn1 = db._get_conn()
        db.init_analysis_db(path)
        assert db._get_conn() is conn1

    def test_path_change_rebinds(self, tmp_path):
        db.init_analysis_db(tmp_path / "a.db")
        conn1 = db._get_conn()
        db.init_analysis_db(tmp_path / "b.db")
        assert db._get_conn() is not conn1
        assert db.get_db_path() == tmp_path / "b.db"

    def test_missing_file_recreated(self, tmp_path):
        path = tmp_path / "analysis.db"
        db.init_analysis_db(path)
        # Drop the thread-local conn so the file can be removed cleanly
        db._get_conn().close()
        path.unlink()
        db.init_analysis_db(path)
        assert path.exists()
        # Schema is usable again
        _insert_entity("p/v1", "p")
        assert db.query_entity("p/v1") is not None


# ---------------------------------------------------------------------------
# user column + scoping helpers
# ---------------------------------------------------------------------------


class TestUserScoping:
    def test_user_column_migrates_old_db(self, tmp_path):
        """A DB created before the user column gains it on init."""
        import sqlite3

        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE entities ("
            "entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, "
            "created_at TEXT NOT NULL, created_by TEXT NOT NULL, "
            "plan_id TEXT, version INTEGER, content_hash TEXT, storage_ref TEXT)"
        )
        conn.commit()
        conn.close()

        db.init_analysis_db(path)
        _insert_entity("p/v1", "p", user="alice")
        assert db.query_entity("p/v1")["user"] == "alice"

    def test_query_plan_ids_scoped(self, tmp_path):
        db.init_analysis_db(tmp_path / "analysis.db")
        _insert_entity("a-plan/v1", "a-plan", user="alice")
        _insert_entity("b-plan/v1", "b-plan", user="bob")
        _insert_entity("legacy/v1", "legacy", user=None)

        assert db.query_plan_ids(None) == ["a-plan", "b-plan", "legacy"]
        assert db.query_plan_ids("alice") == ["a-plan", "legacy"]
        assert db.query_plan_ids("bob") == ["b-plan", "legacy"]
        assert db.query_plan_ids("carol") == ["legacy"]

    def test_plan_visible_to(self, tmp_path):
        db.init_analysis_db(tmp_path / "analysis.db")
        _insert_entity("a-plan/v1", "a-plan", user="alice")
        _insert_entity("legacy/v1", "legacy", user=None)

        assert db.plan_visible_to("a-plan", None)
        assert db.plan_visible_to("a-plan", "alice")
        assert not db.plan_visible_to("a-plan", "bob")
        # Ownerless pre-scoping plans stay visible to everyone
        assert db.plan_visible_to("legacy", "bob")
        # Unknown plans are not visible to scoped users
        assert not db.plan_visible_to("nope", "bob")

    def test_entity_visible_to(self):
        assert db.entity_visible_to(None, "alice")  # existence check is caller's
        assert db.entity_visible_to({"user": None}, "alice")
        assert db.entity_visible_to({"user": "alice"}, "alice")
        assert not db.entity_visible_to({"user": "bob"}, "alice")
        assert db.entity_visible_to({"user": "bob"}, None)  # unscoped sees all
