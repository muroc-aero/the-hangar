"""Tests for the process-wide matplotlib render lock and atomic file writes."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from starlette.requests import Request

from hangar.sdk.viz.render_lock import MPL_RENDER_LOCK, atomic_write_bytes

_PNG_MAGIC = b"\x89PNG"


class TestRenderLock:
    def test_lock_is_reentrant(self):
        with MPL_RENDER_LOCK:
            with MPL_RENDER_LOCK:
                pass  # an RLock must allow nested acquisition

    def test_concurrent_renders_produce_valid_pngs(self):
        """Two threads rendering at once must not mix figure state."""
        from hangar.sdk.viz.plotting import plot_convergence

        conv = {"residual_trace": [1.0, 0.1, 0.01], "converged": True,
                "final_residual": 0.01}

        def render(i):
            return plot_convergence(f"run-{i}", conv)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(render, range(8)))

        for r in results:
            assert r.image.data.startswith(_PNG_MAGIC)


class TestAtomicWrite:
    def test_writes_content_and_leaves_no_temp_files(self, tmp_path):
        target = tmp_path / "plot.png"
        atomic_write_bytes(target, b"abc")
        assert target.read_bytes() == b"abc"
        atomic_write_bytes(target, b"def")  # overwrite is atomic too
        assert target.read_bytes() == b"def"
        assert [p.name for p in tmp_path.iterdir()] == ["plot.png"]


# ---------------------------------------------------------------------------
# Custom viewer route contract: optional user keyword
# ---------------------------------------------------------------------------


def _request(query: str = "") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/x",
        "query_string": query.encode(),
        "headers": [],
    })


class TestCustomHandlerUserContract:
    def test_handler_with_user_kwarg_receives_effective_user(self, monkeypatch):
        from hangar.sdk.viz import viewer_routes

        monkeypatch.setattr(viewer_routes, "_effective_user", lambda req: "alice")
        seen = {}

        def handler(qs, *, user=None):
            seen["user"] = user
            seen["qs"] = qs
            return 200, "text/plain", b"ok"

        endpoint = viewer_routes._adapt_custom_handler(handler)
        resp = asyncio.run(endpoint(_request("a=1")))
        assert resp.status_code == 200
        assert seen["user"] == "alice"
        assert seen["qs"] == {"a": ["1"]}

    def test_handler_without_user_kwarg_still_served(self, monkeypatch):
        from hangar.sdk.viz import viewer_routes

        # Must not even be consulted for legacy handlers
        monkeypatch.setattr(
            viewer_routes, "_effective_user",
            lambda req: (_ for _ in ()).throw(AssertionError("not called")),
        )

        def handler(qs):
            return 200, "text/plain", b"legacy"

        endpoint = viewer_routes._adapt_custom_handler(handler)
        resp = asyncio.run(endpoint(_request()))
        assert resp.status_code == 200
        assert resp.body == b"legacy"
