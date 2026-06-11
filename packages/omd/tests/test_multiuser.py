"""Multi-user concurrency tests for omd: workspace namespacing, per-user
scoping of the analysis DB and /omd-* views, and atomic plan versioning."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from hangar.sdk.auth.oidc import _current_user_ctx


@contextmanager
def as_user(name: str):
    """Impersonate an authenticated user the way verify_token() does."""
    token = _current_user_ctx.set(name)
    try:
        yield
    finally:
        _current_user_ctx.reset(token)


@pytest.fixture(autouse=True)
def isolate_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "omd_data"))
    yield


def _insert_legacy_entity(entity_id, plan_id):
    """Insert a pre-scoping entity row (NULL user) directly."""
    from hangar.omd.db import _get_conn, _now

    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO entities "
        "(entity_id, entity_type, created_at, created_by, plan_id, user) "
        "VALUES (?, 'plan', ?, 'test', ?, NULL)",
        (entity_id, _now(), plan_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Workspace namespacing (per user)
# ---------------------------------------------------------------------------


class TestWorkspaceNamespacing:
    def test_workspace_dir_keyed_per_user(self):
        from hangar.omd.tools._helpers import workspace_dir

        with as_user("alice"):
            ws_a = workspace_dir()
        with as_user("bob"):
            ws_b = workspace_dir()
        assert ws_a != ws_b
        assert ws_a.name == "alice" and ws_b.name == "bob"
        assert ws_a.parent == ws_b.parent

    def test_plan_init_same_id_does_not_clobber(self):
        from hangar.omd.plan_mutate import init_plan
        from hangar.omd.tools._helpers import workspace_dir

        with as_user("alice"):
            init_plan(workspace_dir() / "study1", plan_id="study1", name="alice study")
        with as_user("bob"):
            init_plan(workspace_dir() / "study1", plan_id="study1", name="bob study")

        import yaml

        with as_user("alice"):
            meta = yaml.safe_load(
                (workspace_dir() / "study1" / "metadata.yaml").read_text()
            )
        assert meta["name"] == "alice study"

    def test_email_username_maps_to_safe_dirname(self):
        from hangar.omd.tools._helpers import _user_dir_name

        assert _user_dir_name("alice@example.com") == "alice@example.com"
        assert "/" not in _user_dir_name("../../etc")
        assert _user_dir_name("..") == "anonymous"


# ---------------------------------------------------------------------------
# Per-user scoping: writers and viewer routes
# ---------------------------------------------------------------------------


class TestEntityUserStamping:
    def test_record_entity_stamps_current_user(self):
        from hangar.omd.db import init_analysis_db, query_entity, record_entity

        init_analysis_db()
        with as_user("alice"):
            record_entity("stamp-plan/v1", "plan", "omd", plan_id="stamp-plan")
        assert query_entity("stamp-plan/v1")["user"] == "alice"

    def test_explicit_user_wins(self):
        from hangar.omd.db import init_analysis_db, query_entity, record_entity

        init_analysis_db()
        with as_user("alice"):
            record_entity("x/v1", "plan", "omd", plan_id="x", user="carol")
        assert query_entity("x/v1")["user"] == "carol"


class TestViewerRouteScoping:
    def _seed(self):
        from hangar.omd.db import init_analysis_db, record_entity

        init_analysis_db()
        with as_user("alice"):
            record_entity("alice-plan/v1", "plan", "omd", plan_id="alice-plan")
        with as_user("bob"):
            record_entity("bob-plan/v1", "plan", "omd", plan_id="bob-plan")
        _insert_legacy_entity("legacy-plan/v1", "legacy-plan")

    def test_provenance_index_lists_only_visible_plans(self):
        from hangar.omd.cli.server_routes import _omd_provenance_handler

        self._seed()
        status, _, body = _omd_provenance_handler({}, user="alice")
        assert status == 200
        assert b"alice-plan" in body
        assert b"legacy-plan" in body
        assert b"bob-plan" not in body

    def test_provenance_index_unscoped_lists_all(self):
        from hangar.omd.cli.server_routes import _omd_provenance_handler

        self._seed()
        status, _, body = _omd_provenance_handler({}, user=None)
        assert b"alice-plan" in body and b"bob-plan" in body

    def test_foreign_plan_reads_as_404(self):
        from hangar.omd.cli.server_routes import (
            _omd_plan_detail_handler,
            _omd_provenance_handler,
        )

        self._seed()
        status, _, _ = _omd_plan_detail_handler(
            {"plan_id": ["bob-plan"]}, user="alice"
        )
        assert status == 404
        status, _, _ = _omd_provenance_handler(
            {"plan_id": ["bob-plan"]}, user="alice"
        )
        assert status == 404

    def test_foreign_run_reads_as_404(self):
        from hangar.omd.cli.server_routes import _omd_n2_handler, _omd_plots_handler
        from hangar.omd.db import init_analysis_db, record_entity

        init_analysis_db()
        with as_user("bob"):
            record_entity("run-bob-1", "run_record", "omd", plan_id="bob-plan")
        for handler in (_omd_plots_handler, _omd_n2_handler):
            status, _, _ = handler({"run_id": ["run-bob-1"]}, user="alice")
            assert status == 404

    def test_legacy_handler_signature_still_works(self):
        """Handlers must stay callable as (qs) — the stdio daemon contract."""
        from hangar.omd.cli.server_routes import _omd_provenance_handler

        self._seed()
        status, _, body = _omd_provenance_handler({})
        assert status == 200
        assert b"alice-plan" in body and b"bob-plan" in body


# ---------------------------------------------------------------------------
# Atomic plan version allocation
# ---------------------------------------------------------------------------


class TestAtomicVersionAllocation:
    def test_concurrent_allocations_are_unique(self, tmp_path):
        from hangar.omd.assemble import _allocate_version

        dirs = [tmp_path / f"plan-dir-{i}" for i in range(8)]
        for d in dirs:
            d.mkdir()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda d: _allocate_version(d, "shared-plan"), dirs)
            )

        versions = [v for v, _ in results]
        assert len(set(versions)) == len(versions)
        assert all(path is not None for _, path in results)

    def test_allocation_continues_from_existing_store_versions(self, tmp_path):
        from hangar.omd.assemble import _allocate_version
        from hangar.omd.db import plan_store_dir

        store = plan_store_dir() / "p1"
        store.mkdir(parents=True)
        (store / "v3.yaml").write_text("metadata: {}\n")

        plan_dir = tmp_path / "pd"
        plan_dir.mkdir()
        version, reserved = _allocate_version(plan_dir, "p1")
        assert version == 4
        assert reserved == store / "v4.yaml"

    def test_assemble_plan_fills_reserved_slot(self, fixtures_dir, tmp_path):
        import shutil

        from hangar.omd.assemble import assemble_plan
        from hangar.omd.db import plan_store_dir

        src = fixtures_dir / "paraboloid_analysis"
        if not src.exists():
            pytest.skip("paraboloid_analysis fixture not available")
        plan_dir = tmp_path / "paraboloid"
        shutil.copytree(src, plan_dir)

        result = assemble_plan(plan_dir)
        assert result["errors"] == []
        store_path = result["store_path"]
        assert store_path is not None
        from pathlib import Path

        assert Path(store_path).read_bytes() == Path(result["output_path"]).read_bytes()
        assert not list(plan_store_dir().rglob("*.tmp"))
