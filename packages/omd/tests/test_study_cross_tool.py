"""Cross-tool studies: one spec mixing the omd plan runner and the oas
script runner, plus entry-point discovery in a fresh process.

This is the multi-tool promise of the study layer: different cases in the
same study dispatch to different runners, and runners load lazily from the
``hangar.study_runners`` entry-point group without the caller importing
any tool package.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from hangar.omd.assemble import assemble_plan
from hangar.sdk.study import StudyStore, run_study

FIXTURES = Path(__file__).parent / "fixtures"

# Tiny OAS surface (mirrors the oas test suite's SMALL_RECT).
SMALL_RECT = {
    "name": "wing", "wing_type": "rect", "span": 10.0, "root_chord": 1.0,
    "num_x": 2, "num_y": 5, "symmetry": True, "with_viscous": True,
}


@pytest.fixture()
def study_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HANGAR_STUDY_DIR", str(tmp_path / "studies"))
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "omd_data"))
    monkeypatch.setenv("HANGAR_PROV_DB", str(tmp_path / "prov.db"))
    from hangar.sdk.state import artifacts as _artifacts

    monkeypatch.setattr(_artifacts, "_data_dir", tmp_path / "artifacts")
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    result = assemble_plan(FIXTURES / "paraboloid_analysis",
                           output=base_dir / "plan.yaml")
    assert result["errors"] == []
    return tmp_path


def _mixed_study(tmp_path: Path) -> Path:
    study = {
        "metadata": {"id": "cross-tool-demo", "name": "Cross-tool",
                     "version": 1},
        "defaults": {"runner": "omd",
                     "spec": {"plan": "base/plan.yaml", "mode": "analysis",
                              "recording_level": "minimal"}},
        "cases": [
            {"matrix": {
                "id_template": "px{x:g}",
                "axes": {"x": {"values": [0.0, 1.0]}},
                "bind": {"x": ["operating_points.x"]},
            }},
            {"case": {
                "id": "wing-a4",
                "runner": "oas",
                "params": {"alpha": 4.0},
                "spec": {
                    "plan": None,  # not an omd case; clear the default
                    "steps": [
                        {"id": "surf", "tool": "create_surface",
                         "args": dict(SMALL_RECT)},
                        {"id": "an", "tool": "run_aero_analysis",
                         "args": {"surfaces": ["wing"], "alpha": 4.0}},
                    ],
                },
            }},
        ],
        "outputs": [
            {"name": "f_xy", "path": "paraboloid.f_xy"},
            {"name": "CL", "path": "an:results.CL"},
        ],
    }
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(study))
    return path


def test_mixed_runners_in_one_study(study_env):
    import hangar.oas.study_runner  # noqa: F401
    import hangar.omd.study_runner  # noqa: F401

    path = _mixed_study(study_env)
    result = run_study(path, workers=1)
    assert result["batch"] == {"ran": 3, "succeeded": 3, "failed": 0,
                               "requested": 3}

    state = StudyStore("cross-tool-demo").load_state()
    rows = {e["case_id"]: e for e in state["cases"].values()}
    assert rows["px0"]["runner"] == "omd"
    assert rows["wing-a4"]["runner"] == "oas"
    # Each runner fills the output columns it understands; the rest stay
    # empty, so the case table has one consistent schema across tools.
    assert rows["px0"]["outputs"]["f_xy"] is not None
    assert rows["px0"]["outputs"]["CL"] is None
    assert rows["wing-a4"]["outputs"]["CL"] is not None
    assert rows["wing-a4"]["outputs"]["f_xy"] is None
    # Both kinds of case carry a run_ref into their own tool's store.
    assert rows["px0"]["run_ref"] and rows["wing-a4"]["run_ref"]


@pytest.mark.slow
def test_entry_point_discovery_fresh_process(study_env, tmp_path):
    """hangar-study in a clean process: no tool imports, runner discovered."""
    study = {
        "metadata": {"id": "discovery-demo", "name": "Discovery", "version": 1},
        "defaults": {"runner": "omd",
                     "spec": {"plan": "base/plan.yaml", "mode": "analysis",
                              "recording_level": "minimal"}},
        "cases": [
            {"case": {"id": "one", "params": {},
                      "spec": {"set": {"operating_points.x": 1.0}}}},
        ],
        "outputs": [{"name": "f_xy", "path": "paraboloid.f_xy"}],
    }
    path = tmp_path / "discovery.yaml"
    path.write_text(yaml.safe_dump(study))

    env = dict(os.environ)
    env.update({
        "HANGAR_STUDY_DIR": str(tmp_path / "studies"),
        "OMD_DATA_ROOT": str(tmp_path / "omd_data"),
        "HANGAR_PROV_DB": str(tmp_path / "prov.db"),
        "HANGAR_DATA_DIR": str(tmp_path / "hangar_data"),
    })
    proc = subprocess.run(
        [sys.executable, "-m", "hangar.sdk.study.cli", "run", str(path)],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "1/1 succeeded" in proc.stdout

    state = json.loads(
        (tmp_path / "studies" / "discovery-demo" / "state.json").read_text())
    entry = next(iter(state["cases"].values()))
    assert entry["status"] in ("completed", "converged")
    assert entry["outputs"]["f_xy"] is not None
