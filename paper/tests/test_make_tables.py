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


# --- LaTeX rendering -------------------------------------------------------
#
# The .tex files are pasted into the paper unedited, so a mistake here is a
# mistake in the paper. What matters is that the float is self-contained, that
# a group's example name spans exactly its own rows, and that dropping the
# agent pair leaves a table that still says what it is.

from make_tables import (  # noqa: E402
    build_evals_rows,
    without_agent_columns,
    write_lane_parity_tex,
)

PARITY_HEADER = ["Example", "Tools", "Metric", "Lane A", "Lane B", "rel diff B",
                 "Lane C (scripted)", "rel diff C", "Lane C (agent)",
                 "rel diff agent"]

PARITY_ROWS = [
    ["Paraboloid analysis", "OpenMDAO", "f_xy", "39", "39", "0", "39", "0",
     "39", "0"],
    ["Paraboloid optimization", "OpenMDAO/SLSQP", "x", "6.66667", "--", "--",
     "--", "--", "6.66667", "3.7e-08"],
    ["", "", "f_xy", "-27.3333", "-27.3333", "0", "-27.3333", "0", "-27.3333",
     "4.4e-15"],
    ["Caravan 3-phase mission", "OCP", "fuel_burn_kg", "171.309", "171.309",
     "0", "171.309", "0", "171.309", "7.9e-07"],
    ["", "", "MTOW_kg", "3970", "3970", "0", "3970", "0", "3970", "0"],
]


def _parity_tex(tmp_path, header=None, rows=None, note="") -> str:
    out = tmp_path / "lane_parity.tex"
    write_lane_parity_tex(out, header or PARITY_HEADER, rows or PARITY_ROWS,
                          note)
    return out.read_text()


def test_the_tex_is_a_float_that_can_be_pasted_in_as_is(tmp_path):
    tex = _parity_tex(tmp_path, note="generated from somewhere")
    assert r"\begin{table*}[htbp]" in tex
    assert r"\label{tab:lane-parity}" in tex
    assert r"\caption{Three-lane parity" in tex
    assert r"\begin{tabularx}{\textwidth}{Y Y l r r r r r r r}" in tex
    # the provenance note survives, as a comment above the float
    assert tex.splitlines()[0] == "% generated from somewhere"


def test_an_example_name_spans_exactly_its_own_rows(tmp_path):
    tex = _parity_tex(tmp_path)
    # two metrics -> a 2-row span; one metric -> no \multirow at all, so a
    # name that wraps makes the row taller instead of running into the next
    # group.
    assert r"\multirow{2}{\linewidth}{\textbf{Paraboloid optimization}}" in tex
    assert r"\multirow{2}{\linewidth}{\textbf{Caravan three-phase mission}}" in tex
    assert r"\multirow" not in tex.split("Paraboloid analysis")[0].splitlines()[-1]


def test_metric_keys_are_rendered_with_their_units(tmp_path):
    tex = _parity_tex(tmp_path)
    assert "& fuel (kg) &" in tex
    assert "& MTOW (kg) &" in tex
    assert "fuel\\_burn\\_kg" not in tex
    # an unmapped key still has to be escaped rather than pasted raw
    assert "f\\_xy" in tex


def test_the_caption_claims_the_agent_column_only_when_it_is_there(tmp_path):
    with_agent = _parity_tex(tmp_path)
    assert "effect-graded" in with_agent
    header, rows = without_agent_columns(PARITY_HEADER, PARITY_ROWS)
    assert "effect-graded" not in _parity_tex(tmp_path, header, rows)


def test_dropping_the_agent_pair_drops_the_rows_only_it_compared(tmp_path):
    header, rows = without_agent_columns(PARITY_HEADER, PARITY_ROWS)
    assert header == PARITY_HEADER[:8]
    assert [r[2] for r in rows] == ["f_xy", "f_xy", "fuel_burn_kg", "MTOW_kg"]


def test_a_dropped_lead_row_hands_its_example_name_to_the_next(tmp_path):
    # "x" led the Paraboloid optimization group and only the agent had a value
    # for it; the name has to move down to f_xy rather than vanish with it.
    _, rows = without_agent_columns(PARITY_HEADER, PARITY_ROWS)
    opt = [r for r in rows if r[3] == "-27.3333"][0]
    assert opt[0] == "Paraboloid optimization"
    assert opt[1] == "OpenMDAO/SLSQP"


def test_the_evals_table_follows_the_parity_table_order(tmp_path):
    def summary(case, model):
        return {"case": case, "harness": "claude", "model": model,
                "n_seeds": 1, "n_passed": 1, "n_harness_errors": 0,
                "n_needs_review": 0}

    (tmp_path / "a_summary.json").write_text(json.dumps([
        summary("pyc_turbojet", "m"), summary("paraboloid", "m"),
        summary("oas_aero_rect", "m"), summary("evt_native_sizing", "m"),
    ]))
    _, rows = build_evals_rows(tmp_path)
    # presentation order from CASE_INFO, not alphabetical by slug -- the two
    # tables are two readings of one arm and have to line up.
    assert [r[0] for r in rows] == ["paraboloid", "oas_aero_rect",
                                    "pyc_turbojet", "evt_native_sizing"]
