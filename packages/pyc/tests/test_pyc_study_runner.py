"""Smoke tests for the pyc script-based study runner (no solver time).

``generate`` builds the real pyCycle tool registry and validates every
case script against it, so these catch registry/import breakage without
paying for cycle solves. End-to-end execution of the shared script runner
is covered in the sdk and oas suites.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import hangar.pyc.study_runner  # noqa: F401  (registers the "pyc" runner)
from hangar.sdk.study.orchestrate import generate_study


@pytest.fixture(autouse=True)
def isolate_prov_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HANGAR_PROV_DB", str(tmp_path / "prov.db"))


def _study(tmp_path: Path, design_tool: str = "run_design_point") -> Path:
    steps = [
        {"id": "engine", "tool": "create_engine",
         "args": {"name": "tj", "archetype": "turbojet"}},
        {"id": "design", "tool": design_tool,
         "args": {"engine_name": "tj", "T4_target": 3000.0}},
    ]
    study = {
        "metadata": {"id": "pyc-t4-smoke", "name": "pyCycle T4 sweep",
                     "version": 1},
        "defaults": {"runner": "pyc", "spec": {"steps": steps}},
        "cases": [
            {"matrix": {
                "id_template": "t{T4:g}",
                "axes": {"T4": {"values": [2800.0, 3200.0]}},
                "bind": {"T4": ["steps[design].args.T4_target"]},
            }},
        ],
        "outputs": [
            {"name": "TSFC", "path": "design:results.performance.TSFC"},
        ],
    }
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(study))
    return path


def test_generate_builds_registry_and_binds_t4(tmp_path):
    path = _study(tmp_path)
    result = generate_study(path, store_root=tmp_path / "store")
    assert len(result["generated"]) == 2
    t4s = sorted(
        json.loads(Path(item["artifact"]).read_text())[1]["args"]["T4_target"]
        for item in result["generated"])
    assert t4s == [2800.0, 3200.0]


def test_generate_rejects_unknown_tool(tmp_path):
    path = _study(tmp_path, design_tool="run_desgin_point")  # typo
    with pytest.raises(ValueError, match="run_desgin_point"):
        generate_study(path, store_root=tmp_path / "store")
