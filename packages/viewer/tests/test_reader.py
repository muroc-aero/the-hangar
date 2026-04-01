"""Tests for the MultiDBProvenanceReader."""

import sqlite3
import pytest
from pathlib import Path
from hangar.viewer.reader import MultiDBProvenanceReader, parse_db_spec


def _create_test_db(path: Path, tool: str, session_id: str, calls: list[dict]):
    """Create a minimal provenance SQLite DB for testing."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, notes TEXT, oas_session_id TEXT,
            started_at TEXT NOT NULL, user TEXT DEFAULT '', project TEXT DEFAULT 'default',
            tool TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tool_calls (
            call_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
            tool_name TEXT NOT NULL, inputs_json TEXT, outputs_json TEXT,
            status TEXT DEFAULT 'ok', error_msg TEXT, started_at TEXT NOT NULL,
            duration_s REAL, tool TEXT DEFAULT '',
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
            decision_type TEXT NOT NULL, reasoning TEXT, prior_call_id TEXT,
            selected_action TEXT, confidence TEXT DEFAULT 'medium',
            recorded_at TEXT NOT NULL, tool TEXT DEFAULT '',
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
        CREATE TABLE IF NOT EXISTS cross_references (
            ref_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            source_call_id TEXT NOT NULL, source_tool TEXT NOT NULL,
            target_call_id TEXT, target_tool TEXT NOT NULL,
            variables_json TEXT, notes TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO sessions(session_id, notes, started_at, tool) VALUES (?,?,?,?)",
        (session_id, "test", "2026-01-01T00:00:00Z", tool),
    )
    for c in calls:
        # Use seq-derived timestamp so cross-DB ordering by started_at is correct
        ts = c.get("started_at", f"2026-01-01T00:00:{c['seq']:02d}Z")
        conn.execute(
            "INSERT INTO tool_calls(call_id, session_id, seq, tool_name, started_at, tool) "
            "VALUES (?,?,?,?,?,?)",
            (c["call_id"], session_id, c["seq"], c["tool_name"], ts, tool),
        )
    conn.commit()
    conn.close()


class TestMultiDBProvenanceReader:
    def test_list_sessions_merges(self, tmp_path):
        """Sessions with the same ID from different DBs are merged."""
        sid = "sess-shared"
        db_oas = tmp_path / "oas.db"
        db_ocp = tmp_path / "ocp.db"

        _create_test_db(db_oas, "oas", sid, [
            {"call_id": "c1", "seq": 0, "tool_name": "run_aero_analysis"},
        ])
        _create_test_db(db_ocp, "ocp", sid, [
            {"call_id": "c2", "seq": 1, "tool_name": "run_mission_analysis"},
        ])

        reader = MultiDBProvenanceReader({"oas": db_oas, "ocp": db_ocp})
        sessions = reader.list_sessions()

        assert len(sessions) == 1
        s = sessions[0]
        assert s["session_id"] == sid
        assert sorted(s["tools"]) == ["oas", "ocp"]
        assert s["tool_call_count"] == 2

    def test_get_session_graph_merges_nodes(self, tmp_path):
        """Graph merges tool_call nodes from multiple DBs."""
        sid = "sess-merged"
        db_oas = tmp_path / "oas.db"
        db_pyc = tmp_path / "pyc.db"

        _create_test_db(db_oas, "oas", sid, [
            {"call_id": "oas-c1", "seq": 2, "tool_name": "run_aero_analysis"},
        ])
        _create_test_db(db_pyc, "pyc", sid, [
            {"call_id": "pyc-c1", "seq": 0, "tool_name": "create_engine"},
            {"call_id": "pyc-c2", "seq": 1, "tool_name": "run_design_point"},
        ])

        reader = MultiDBProvenanceReader({"oas": db_oas, "pyc": db_pyc})
        graph = reader.get_session_graph(sid)

        assert len(graph["nodes"]) == 3
        # Sorted by seq
        assert graph["nodes"][0]["tool_name"] == "create_engine"
        assert graph["nodes"][0]["tool"] == "pyc"
        assert graph["nodes"][1]["tool_name"] == "run_design_point"
        assert graph["nodes"][2]["tool_name"] == "run_aero_analysis"
        assert graph["nodes"][2]["tool"] == "oas"

        # Sequence edges between consecutive tool calls
        seq_edges = [e for e in graph["edges"] if e["label"] == "sequence"]
        assert len(seq_edges) == 2

    def test_get_session_graph_cross_references(self, tmp_path):
        """Cross-reference edges are included in merged graph."""
        sid = "sess-xref"
        db_oas = tmp_path / "oas.db"

        _create_test_db(db_oas, "oas", sid, [
            {"call_id": "oas-c1", "seq": 0, "tool_name": "run_aero_analysis"},
        ])

        # Add a cross-reference
        conn = sqlite3.connect(str(db_oas))
        conn.execute(
            "INSERT INTO cross_references(ref_id, session_id, source_call_id, source_tool, "
            "target_call_id, target_tool, variables_json, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("xref-1", sid, "pyc-c1", "pyc", "oas-c1", "oas", '{"Fn": 25000}', "thrust handoff",
             "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        conn.close()

        reader = MultiDBProvenanceReader({"oas": db_oas})
        graph = reader.get_session_graph(sid)

        xref_edges = [e for e in graph["edges"] if e["label"] == "cross_tool"]
        assert len(xref_edges) == 1
        assert xref_edges[0]["source_tool"] == "pyc"
        assert xref_edges[0]["target_tool"] == "oas"
        assert xref_edges[0]["variables"] == {"Fn": 25000}

    def test_missing_db_graceful(self, tmp_path):
        """Missing DB files are handled gracefully."""
        reader = MultiDBProvenanceReader({
            "oas": tmp_path / "nonexistent.db",
        })
        sessions = reader.list_sessions()
        assert sessions == []

    def test_separate_sessions(self, tmp_path):
        """Sessions that only exist in one DB appear with a single tool."""
        db_oas = tmp_path / "oas.db"
        db_ocp = tmp_path / "ocp.db"

        _create_test_db(db_oas, "oas", "sess-oas-only", [
            {"call_id": "c1", "seq": 0, "tool_name": "run_aero_analysis"},
        ])
        _create_test_db(db_ocp, "ocp", "sess-ocp-only", [
            {"call_id": "c2", "seq": 0, "tool_name": "run_mission_analysis"},
        ])

        reader = MultiDBProvenanceReader({"oas": db_oas, "ocp": db_ocp})
        sessions = reader.list_sessions()

        assert len(sessions) == 2
        by_id = {s["session_id"]: s for s in sessions}
        assert by_id["sess-oas-only"]["tools"] == ["oas"]
        assert by_id["sess-ocp-only"]["tools"] == ["ocp"]


class TestParseDbSpec:
    def test_basic(self):
        result = parse_db_spec("oas=/data/oas/prov.db,ocp=/data/ocp/prov.db")
        assert result == {
            "oas": Path("/data/oas/prov.db"),
            "ocp": Path("/data/ocp/prov.db"),
        }

    def test_whitespace(self):
        result = parse_db_spec("  oas = /data/oas/prov.db , ocp = /data/ocp/prov.db  ")
        assert len(result) == 2

    def test_empty(self):
        assert parse_db_spec("") == {}

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid DB spec"):
            parse_db_spec("no-equals-sign")
