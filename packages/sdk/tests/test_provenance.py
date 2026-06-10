"""Tests for the provenance tracking system.

Migrated from: OpenAeroStruct/oas_mcp/tests/test_provenance.py

Import mapping applied:
  - oas_mcp.provenance.capture -> hangar.sdk.provenance.middleware
  - oas_mcp.provenance.db -> hangar.sdk.provenance.db
  - oas_mcp.provenance.tools -> hangar.oas.tools.session
"""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import numpy as np
import pytest

from hangar.sdk.provenance.middleware import (
    _prov_session_id,
    _safe_json,
    capture_tool,
    set_default_session_id,
)
from hangar.sdk.provenance.db import (
    build_session_elements,
    get_requirements,
    get_session_graph,
    get_session_meta,
    init_db,
    list_sessions,
    record_decision,
    record_requirements,
    record_session,
    record_tool_call,
    session_exists,
    update_session_project,
)
from hangar.sdk.provenance.flush import GRAPH_FILENAME, flush_session_graph
from hangar.oas.tools.session import export_session_graph, log_decision, start_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(prefix="ts") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _make_call_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DB layer tests
# ---------------------------------------------------------------------------


def test_init_db_creates_tables(tmp_path):
    """init_db creates the 3 required tables."""
    import sqlite3

    db = tmp_path / "prov.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"sessions", "tool_calls", "decisions", "requirements"}.issubset(tables)
    conn.close()


def test_record_and_get_requirements_round_trip(tmp_path):
    """Requirements persist with their value type preserved and in set order."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    reqs = [
        {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
        {"path": "surfaces.wing.failure", "operator": "<", "value": 1.0},
    ]
    record_requirements(sid, reqs)

    got = get_requirements(sid)
    assert got == [
        {"path": "CL", "operator": ">=", "value": 0.4, "label": "min_CL"},
        {"path": "surfaces.wing.failure", "operator": "<", "value": 1.0, "label": None},
    ]


def test_record_requirements_replaces_prior_set(tmp_path):
    """A second call overwrites the full set, mirroring runtime semantics."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    record_requirements(sid, [{"path": "CL", "operator": ">=", "value": 0.4}])
    record_requirements(sid, [
        {"path": "L_over_D", "operator": ">", "value": 18.0, "label": "ld"},
    ])

    got = get_requirements(sid)
    assert len(got) == 1
    assert got[0]["path"] == "L_over_D" and got[0]["value"] == 18.0


def test_record_requirements_accepts_target_alias(tmp_path):
    """pyc-style requirements use ``target`` for the comparison value."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    record_requirements(sid, [
        {"path": "performance.TSFC", "operator": "<", "target": 0.6, "label": "tsfc"},
    ])
    got = get_requirements(sid)
    assert got[0]["value"] == 0.6


def test_get_requirements_empty_for_unknown_session(tmp_path):
    init_db(tmp_path / "prov.db")
    assert get_requirements("nope") == []


def test_record_and_retrieve_tool_call(tmp_path):
    """Record a tool call and verify it appears in get_session_graph."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    call_id = _make_call_id()
    record_tool_call(
        call_id=call_id,
        session_id=sid,
        seq=0,
        tool_name="run_aero_analysis",
        inputs_json='{"surfaces": ["wing"]}',
        outputs_json='{"CL": 0.5}',
        status="ok",
        error_msg=None,
        started_at="2025-01-01T00:00:00+00:00",
        duration_s=1.23,
    )

    graph = get_session_graph(sid)
    nodes = graph["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["type"] == "tool_call"
    assert nodes[0]["tool_name"] == "run_aero_analysis"
    assert nodes[0]["id"] == call_id


def test_record_decision_with_prior_call(tmp_path):
    """Decision with prior_call_id creates an 'informs' edge."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    call_id = _make_call_id()
    record_tool_call(
        call_id=call_id,
        session_id=sid,
        seq=0,
        tool_name="run_aero_analysis",
        inputs_json="{}",
        outputs_json="{}",
        status="ok",
        error_msg=None,
        started_at="2025-01-01T00:00:00+00:00",
        duration_s=1.0,
    )

    dec_id = str(uuid.uuid4())
    record_decision(
        decision_id=dec_id,
        session_id=sid,
        seq=1,
        decision_type="result_interpretation",
        reasoning="CL looks good",
        prior_call_id=call_id,
        selected_action="proceed",
        confidence="high",
    )

    graph = get_session_graph(sid)
    edges = graph["edges"]
    informs_edges = [e for e in edges if e["label"] == "informs"]
    assert len(informs_edges) == 1
    assert informs_edges[0]["source"] == call_id
    assert informs_edges[0]["target"] == dec_id


def test_get_session_graph_edge_logic(tmp_path):
    """All 3 edge types are correctly generated."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    # Sequence: tool_call0 -> decision1 -> tool_call2 -> tool_call3
    cid0 = _make_call_id()
    cid2 = _make_call_id()
    cid3 = _make_call_id()
    dec1 = str(uuid.uuid4())

    record_tool_call(cid0, sid, 0, "create_surface", "{}", "{}", "ok", None, "2025-01-01T00:00:00+00:00", 0.1)
    record_decision(dec1, sid, 1, "mesh_resolution", "use fine mesh", cid0, "num_y=15", "medium")
    record_tool_call(cid2, sid, 2, "run_aero_analysis", "{}", "{}", "ok", None, "2025-01-01T00:00:01+00:00", 1.0)
    record_tool_call(cid3, sid, 3, "compute_drag_polar", "{}", "{}", "ok", None, "2025-01-01T00:00:02+00:00", 5.0)

    graph = get_session_graph(sid)
    edges = graph["edges"]
    labels = {e["label"] for e in edges}

    assert "informs" in labels   # cid0 -> dec1
    assert "decides" in labels   # dec1 -> cid2
    assert "sequence" in labels  # cid2 -> cid3


def test_build_session_elements(tmp_path):
    """build_session_elements returns normalized Cytoscape elements."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    cid0 = _make_call_id()
    dec1 = str(uuid.uuid4())
    cid2 = _make_call_id()
    record_tool_call(cid0, sid, 0, "create_surface", "{}", "{}", "ok", None,
                     "2025-01-01T00:00:00+00:00", 0.1)
    record_decision(dec1, sid, 1, "mesh_resolution", "use a fine mesh for accuracy",
                    cid0, "num_y=15", "medium")
    record_tool_call(cid2, sid, 2, "run_aero_analysis", "{}", "{}", "ok", None,
                     "2025-01-01T00:00:01+00:00", 1.0)

    elements = build_session_elements(sid)
    assert set(elements) == {"nodes", "edges"}

    # Cytoscape-native form; normalized `kind` style key on every node.
    by_id = {n["data"]["id"]: n["data"] for n in elements["nodes"]}
    assert by_id[cid0]["kind"] == "tool_call"
    assert by_id[cid0]["label"] == "create_surface"
    assert by_id[dec1]["kind"] == "decision"
    # decision label carries the reasoning so the node is legible.
    assert "fine mesh" in by_id[dec1]["label"]

    # Edges carry a `relation` and reference only existing nodes.
    node_ids = set(by_id)
    for e in elements["edges"]:
        assert e["data"]["relation"] in {"informs", "decides", "sequence", "cross_tool"}
        assert e["data"]["source"] in node_ids
        assert e["data"]["target"] in node_ids


def test_list_sessions(tmp_path):
    """list_sessions returns all sessions with counts."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid, notes="test session")
    cid = _make_call_id()
    record_tool_call(cid, sid, 0, "reset", "{}", "{}", "ok", None, "2025-01-01T00:00:00+00:00", 0.01)

    sessions = list_sessions()
    match = [s for s in sessions if s["session_id"] == sid]
    assert len(match) == 1
    assert match[0]["tool_call_count"] == 1
    assert match[0]["decision_count"] == 0


# ---------------------------------------------------------------------------
# capture_tool decorator tests
# ---------------------------------------------------------------------------


def test_capture_decorator_preserves_signature(tmp_path):
    """@capture_tool must not alter the function's __signature__."""
    init_db(tmp_path / "prov.db")

    async def my_tool(x: int, y: str = "hello") -> dict:
        return {}

    wrapped = capture_tool(my_tool)
    # eval_str=True resolves PEP 563 string annotations to actual types
    assert inspect.signature(wrapped) == inspect.signature(my_tool, eval_str=True)


@pytest.mark.asyncio
async def test_capture_decorator_records_on_success(tmp_path):
    """A successful call is recorded with status='ok'."""
    import sqlite3

    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    token = _prov_session_id.set(sid)

    try:

        @capture_tool
        async def my_tool(x: int) -> dict:
            return {"result": x * 2}

        await my_tool(x=3)

        db_conn = sqlite3.connect(str(tmp_path / "prov.db"))
        rows = db_conn.execute(
            "SELECT * FROM tool_calls WHERE session_id=? AND tool_name='my_tool'", (sid,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][6] == "ok"  # status column
        db_conn.close()
    finally:
        _prov_session_id.reset(token)


@pytest.mark.asyncio
async def test_capture_decorator_records_on_error(tmp_path):
    """A failing call is recorded with status='error'."""
    import sqlite3

    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    token = _prov_session_id.set(sid)

    try:

        @capture_tool
        async def failing_tool() -> dict:
            raise ValueError("intentional failure")

        with pytest.raises(ValueError):
            await failing_tool()

        db_conn = sqlite3.connect(str(tmp_path / "prov.db"))
        rows = db_conn.execute(
            "SELECT * FROM tool_calls WHERE session_id=?", (sid,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][6] == "error"  # status
        assert "intentional failure" in (rows[0][7] or "")
        db_conn.close()
    finally:
        _prov_session_id.reset(token)


@pytest.mark.asyncio
async def test_capture_decorator_returns_error_envelope_for_hangar_errors(tmp_path):
    """Typed HangarError subclasses become error envelopes, not raised exceptions."""
    import sqlite3

    from hangar.sdk.errors import UserInputError

    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    token = _prov_session_id.set(sid)

    try:

        @capture_tool
        async def rejecting_tool() -> dict:
            raise UserInputError(
                "num_nodes must be odd", details={"field": "num_nodes", "value": 4}
            )

        result = await rejecting_tool()

        assert result["results"] is None
        assert result["run_id"] is None
        assert result["error"]["code"] == "USER_INPUT_ERROR"
        assert result["error"]["message"] == "num_nodes must be odd"
        assert result["error"]["details"] == {"field": "num_nodes", "value": 4}
        assert result["_provenance"]["session_id"] == sid

        # Provenance still records the call as an error.
        db_conn = sqlite3.connect(str(tmp_path / "prov.db"))
        rows = db_conn.execute(
            "SELECT status, error_msg FROM tool_calls WHERE session_id=?", (sid,)
        ).fetchall()
        db_conn.close()
        assert rows == [("error", "num_nodes must be odd")]
    finally:
        _prov_session_id.reset(token)


@pytest.mark.asyncio
async def test_capture_decorator_injects_provenance(tmp_path):
    """_provenance dict is injected into returned dict on success."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)
    token = _prov_session_id.set(sid)

    try:

        @capture_tool
        async def my_tool() -> dict:
            return {"CL": 0.5}

        result = await my_tool()
        assert "_provenance" in result
        assert "call_id" in result["_provenance"]
        assert result["_provenance"]["session_id"] == sid
    finally:
        _prov_session_id.reset(token)


@pytest.mark.asyncio
async def test_start_session_overrides_startup_seeded_default(tmp_path):
    """start_session must win over a process default seeded at server startup.

    Regression: the OAS/OCP/pyc servers used to seed _prov_session_id (ContextVar)
    at startup with an "auto-XXXX" session.  Because the ContextVar has priority
    over the module-level state, every later tool call in the main asyncio task
    wrote to the auto session even after start_session(). Servers now seed via
    set_default_session_id() so start_session() (which records the per-user
    active session) can override.
    """
    import sqlite3

    init_db(tmp_path / "prov.db")
    # Simulate server startup: seed only the per-process fallback.
    set_default_session_id("auto-deadbeef")
    record_session("auto-deadbeef")

    # User starts a real session.
    started = await start_session(notes="real session")
    user_sid = started["session_id"]

    # A tool call after start_session must land in the user's session.
    @capture_tool
    async def my_tool(x: int) -> dict:
        return {"result": x * 2}

    await my_tool(x=3)

    conn = sqlite3.connect(str(tmp_path / "prov.db"))
    user_rows = conn.execute(
        "SELECT 1 FROM tool_calls WHERE session_id=? AND tool_name='my_tool'",
        (user_sid,),
    ).fetchall()
    auto_rows = conn.execute(
        "SELECT 1 FROM tool_calls WHERE session_id='auto-deadbeef' AND tool_name='my_tool'"
    ).fetchall()
    conn.close()

    assert len(user_rows) == 1, "tool call should land in the user's started session"
    assert len(auto_rows) == 0, "tool call must NOT leak into the startup-seeded auto session"


def test_safe_json_handles_numpy():
    """_safe_json serialises numpy arrays and scalars without error."""
    obj = {
        "arr": np.array([1.0, 2.0, 3.0]),
        "scalar": np.float32(3.14),
        "int": np.int64(42),
    }
    result = _safe_json(obj)
    import json

    parsed = json.loads(result)
    assert parsed["arr"] == [1.0, 2.0, 3.0]
    assert abs(parsed["scalar"] - 3.14) < 0.01
    assert parsed["int"] == 42


# ---------------------------------------------------------------------------
# tools.py tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_creates_record(tmp_path):
    """start_session creates a DB record and sets the context var."""
    init_db(tmp_path / "prov.db")
    result = await start_session(notes="unit test")
    sid = result["session_id"]
    assert sid.startswith("sess-")
    assert _prov_session_id.get() == sid


@pytest.mark.asyncio
async def test_log_decision_records_decision(tmp_path):
    """log_decision returns a decision_id and writes to DB."""
    import sqlite3

    init_db(tmp_path / "prov.db")
    sess = await start_session()
    sid = sess["session_id"]

    result = await log_decision(
        decision_type="dv_selection",
        reasoning="chose twist for minimum drag",
        selected_action="twist_cp",
        confidence="high",
    )
    assert "decision_id" in result

    db_conn = sqlite3.connect(str(tmp_path / "prov.db"))
    rows = db_conn.execute(
        "SELECT * FROM decisions WHERE session_id=?", (sid,)
    ).fetchall()
    assert len(rows) == 1
    db_conn.close()


@pytest.mark.asyncio
async def test_export_session_graph_writes_file(tmp_path, monkeypatch):
    """export_session_graph writes graph to artifact dir and returns pointer."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("OAS_DATA_DIR", str(data_dir))

    init_db(tmp_path / "prov.db")
    sess = await start_session(notes="export test")
    sid = sess["session_id"]

    # Add a tool call manually
    cid = _make_call_id()
    record_tool_call(cid, sid, 0, "create_surface", "{}", "{}", "ok", None, "2025-01-01T00:00:00+00:00", 0.1)

    result = await export_session_graph(session_id=sid)

    # Returns pointer, not full graph
    assert "nodes" not in result
    assert "edges" not in result
    assert result["node_count"] == 1
    assert result["edge_count"] == 0
    assert result["session_id"] == sid

    # Graph file exists on disk
    graph_path = result["graph_path"]
    assert graph_path is not None
    assert Path(graph_path).exists()
    assert GRAPH_FILENAME in graph_path


# ---------------------------------------------------------------------------
# flush_session_graph tests
# ---------------------------------------------------------------------------


def test_flush_session_graph_writes_file(tmp_path):
    """flush_session_graph writes valid JSON to the artifact directory."""
    import json

    data_dir = tmp_path / "data"
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid, user="testuser", project="proj1")
    cid = _make_call_id()
    record_tool_call(cid, sid, 0, "create_surface", "{}", "{}", "ok", None, "2025-01-01T00:00:00+00:00", 0.1)

    result = flush_session_graph(sid, data_dir=data_dir)

    assert result["node_count"] == 1
    assert result["edge_count"] == 0
    assert result["path"] is not None

    p = Path(result["path"])
    assert p.exists()
    graph = json.loads(p.read_text())
    assert len(graph["nodes"]) == 1
    assert "testuser" in result["path"]
    assert "proj1" in result["path"]


def test_flush_session_graph_idempotent(tmp_path):
    """Calling flush twice succeeds and overwrites cleanly."""
    data_dir = tmp_path / "data"
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    r1 = flush_session_graph(sid, data_dir=data_dir)
    r2 = flush_session_graph(sid, data_dir=data_dir)

    assert r1["path"] == r2["path"]
    assert Path(r2["path"]).exists()


def test_flush_session_graph_resolves_user_project_from_db(tmp_path):
    """When user/project not passed, they are resolved from the DB."""
    data_dir = tmp_path / "data"
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid, user="alice", project="wing_study")

    result = flush_session_graph(sid, data_dir=data_dir)

    assert "alice" in result["path"]
    assert "wing_study" in result["path"]


def test_flush_session_graph_empty_session(tmp_path):
    """Flushing a session with no tool calls returns node_count=0."""
    data_dir = tmp_path / "data"
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid)

    result = flush_session_graph(sid, data_dir=data_dir)

    assert result["node_count"] == 0
    assert result["edge_count"] == 0
    assert result["path"] is not None


# ---------------------------------------------------------------------------
# DB schema tests
# ---------------------------------------------------------------------------


def test_project_column_exists(tmp_path):
    """The sessions table has a project column after init_db."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid, project="myproject")

    meta = get_session_meta(sid)
    assert meta is not None
    assert meta["project"] == "myproject"


def test_update_session_project(tmp_path):
    """update_session_project changes the project in the DB."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid, project="old")

    update_session_project(sid, "new")
    meta = get_session_meta(sid)
    assert meta["project"] == "new"


def test_session_exists(tmp_path):
    """session_exists returns correct boolean."""
    init_db(tmp_path / "prov.db")
    sid = _make_session()
    assert not session_exists(sid)
    record_session(sid)
    assert session_exists(sid)


# ---------------------------------------------------------------------------
# start_session join tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_session_join_existing(tmp_path):
    """start_session with an existing session_id joins instead of creating."""
    init_db(tmp_path / "prov.db")
    sess1 = await start_session(notes="original")
    sid = sess1["session_id"]

    sess2 = await start_session(session_id=sid)
    assert sess2["session_id"] == sid
    assert sess2["joined"] is True

    # Only one session record in DB
    sessions = list_sessions()
    matches = [s for s in sessions if s["session_id"] == sid]
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_start_session_create_with_explicit_id(tmp_path):
    """start_session with a new explicit session_id creates it."""
    init_db(tmp_path / "prov.db")
    result = await start_session(session_id="custom-id-123", notes="custom")
    assert result["session_id"] == "custom-id-123"
    assert result["joined"] is False
    assert session_exists("custom-id-123")


# ---------------------------------------------------------------------------
# DB default location tests
# ---------------------------------------------------------------------------


def test_init_db_default_uses_data_dir(tmp_path, monkeypatch):
    """Without OAS_PROV_DB, init_db uses $OAS_DATA_DIR/.provenance/."""
    data_dir = tmp_path / "artifacts"
    monkeypatch.setenv("OAS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OAS_PROV_DB", raising=False)
    # Ensure no legacy DB interferes
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "fakehome")

    init_db()

    expected = data_dir / ".provenance" / "sessions.db"
    assert expected.exists()


def test_init_db_legacy_fallback(tmp_path, monkeypatch):
    """If legacy DB exists but new default doesn't, use legacy and warn."""

    fake_home = tmp_path / "fakehome"
    legacy_dir = fake_home / ".oas_provenance"
    legacy_dir.mkdir(parents=True)
    legacy_db = legacy_dir / "sessions.db"
    # Create a minimal SQLite DB at the legacy location
    import sqlite3
    conn = sqlite3.connect(str(legacy_db))
    conn.close()

    data_dir = tmp_path / "artifacts"
    monkeypatch.setenv("OAS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("OAS_PROV_DB", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    init_db()

    # The legacy DB should still be there and be usable
    assert legacy_db.exists()


# ---------------------------------------------------------------------------
# Periodic middleware flush tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_tool_periodic_flush(tmp_path, monkeypatch):
    """@capture_tool flushes the graph every _FLUSH_EVERY calls."""
    import hangar.sdk.provenance.middleware as mw

    data_dir = tmp_path / "data"
    monkeypatch.setenv("OAS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(mw, "_FLUSH_EVERY", 2)

    init_db(tmp_path / "prov.db")
    sid = _make_session()
    record_session(sid, user="default", project="default")
    token = _prov_session_id.set(sid)
    mw._flush_counter.clear()

    try:

        @capture_tool
        async def dummy_tool() -> dict:
            return {"ok": True}

        # Call 1: no flush yet
        await dummy_tool()
        graph_path = data_dir / "default" / "default" / sid / GRAPH_FILENAME
        # After 1 call, graph may or may not exist (flush at count=2)

        # Call 2: should trigger flush
        await dummy_tool()
        assert graph_path.exists(), "Graph should be flushed after 2 calls"
    finally:
        _prov_session_id.reset(token)
        mw._flush_counter.clear()
