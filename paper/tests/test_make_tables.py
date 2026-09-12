"""Lane C (agent) column sourcing.

The agent column and sandboxed_evals.md are two readings of the same arm, so
the loader that turns records into one number per metric is the seam where a
quiet mistake would put a wrong value in a paper table.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from make_tables import (  # noqa: E402
    _with_agent_provenance,
    load_agent_from_records,
)

ARM = ("claude", "claude-opus-5")


def _record(case, seed, scores, harness="claude", model="claude-opus-5"):
    return {"case": case, "harness": harness, "model": model, "seed": seed,
            "passed": True, "scores": scores}


def _score(key, lane_a, agent):
    rel = abs(agent - lane_a) / abs(lane_a) if lane_a else 0.0
    return {"key": key, "lane_a": lane_a, "agent": agent, "rel_err": rel,
            "verdict": "PASS"}


def _write(path: Path, records, mtime: int):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    os.utime(path, (mtime, mtime))


def test_worst_seed_is_reported_not_the_median(tmp_path):
    """Two seeds nail CD and one is 2.7% off. The parity column must show the
    disagreement -- the pass rate is the other table's job."""
    _write(tmp_path / "oas_aero_rect_20260911T160732Z.jsonl", [
        _record("oas_aero_rect", 0, [_score("CD", 0.0350873, 0.0341362)]),
        _record("oas_aero_rect", 1, [_score("CD", 0.0350873, 0.0350873)]),
        _record("oas_aero_rect", 2, [_score("CD", 0.0350873, 0.0350873)]),
    ], mtime=2_000)
    agent = load_agent_from_records(tmp_path, *ARM)
    entry = agent[("oas_aero_rect", "CD")]
    assert entry["agent"] == pytest.approx(0.0341362)
    assert entry["n_seeds"] == 3
    assert entry["source"] == "arm"


def test_the_newest_file_that_has_the_arm_wins_not_just_the_newest(tmp_path):
    """results/ holds every arm side by side. A newer gemma file for the same
    case must not shadow the anchor arm's numbers."""
    _write(tmp_path / "paraboloid_20260910T194825Z.jsonl", [
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 39.0)]),
    ], mtime=1_000)
    _write(tmp_path / "paraboloid_20260911T102757Z.jsonl", [
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 12.0)],
                harness="opencode", model="gemma4:26b-mlx"),
    ], mtime=9_000)
    agent = load_agent_from_records(tmp_path, *ARM)
    assert agent[("paraboloid_analysis", "f_xy")]["agent"] == 39.0


def test_a_newer_file_for_the_same_case_supersedes_an_older_one(tmp_path):
    _write(tmp_path / "paraboloid_20260910T194825Z.jsonl", [
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 38.0)]),
    ], mtime=1_000)
    _write(tmp_path / "paraboloid_20260911T160225Z.jsonl", [
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 39.0)]),
    ], mtime=2_000)
    agent = load_agent_from_records(tmp_path, *ARM)
    assert agent[("paraboloid_analysis", "f_xy")]["agent"] == 39.0


def test_a_resumed_file_uses_the_retry_not_the_superseded_row(tmp_path):
    """Same de-duplication the eval tooling applies: last row per seed wins."""
    path = tmp_path / "paraboloid_20260911T160225Z.jsonl"
    _write(path, [
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 1.0)]),
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 39.0)]),
    ], mtime=2_000)
    agent = load_agent_from_records(tmp_path, *ARM)
    assert agent[("paraboloid_analysis", "f_xy")]["agent"] == 39.0


def test_unmapped_metrics_and_ungraded_values_are_dropped(tmp_path):
    _write(tmp_path / "paraboloid_20260911T160225Z.jsonl", [
        _record("paraboloid", 0, [
            _score("analysis_f_xy", 39.0, 39.0),
            {"key": "not_a_table_metric", "lane_a": 1.0, "agent": 1.0,
             "rel_err": 0.0, "verdict": "PASS"},
            {"key": "opt_f_xy", "lane_a": -27.3, "agent": None,
             "rel_err": None, "verdict": "FAIL"},
        ]),
    ], mtime=2_000)
    agent = load_agent_from_records(tmp_path, *ARM)
    assert set(agent) == {("paraboloid_analysis", "f_xy")}


def test_an_arm_that_never_ran_yields_nothing(tmp_path):
    _write(tmp_path / "paraboloid_20260911T160225Z.jsonl", [
        _record("paraboloid", 0, [_score("analysis_f_xy", 39.0, 39.0)],
                harness="opencode", model="qwen3:8b"),
    ], mtime=2_000)
    assert load_agent_from_records(tmp_path, *ARM) == {}


# --- provenance note ---------------------------------------------------------


def test_the_note_names_the_arm_behind_the_column():
    agent = {
        ("paraboloid_analysis", "f_xy"): {"source": "arm", "n_seeds": 3},
        ("oas_aero_rect", "CD"): {"source": "arm", "n_seeds": 3},
    }
    note = _with_agent_provenance("", agent, "claude-opus-5")
    assert "claude-opus-5" in note and "3 seeds" in note
    assert "worst seed" in note
    # A case the arm never ran is blank, not borrowed from somewhere else.
    assert "--" in note


def test_the_note_keeps_the_lane_parity_provenance_it_was_given():
    agent = {("paraboloid_analysis", "f_xy"): {"source": "arm", "n_seeds": 3}}
    note = _with_agent_provenance("generated from lane_parity.jsonl (git abc)",
                                  agent, "claude-opus-5")
    assert note.startswith("generated from lane_parity.jsonl (git abc)")


def test_no_agent_data_leaves_the_note_alone():
    assert _with_agent_provenance("original", {}, "claude-opus-5") == "original"
