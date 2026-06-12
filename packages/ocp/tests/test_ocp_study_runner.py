"""Smoke tests for the ocp script-based study runner (no solver time).

``generate`` builds the real OCP tool registry and validates every case
script against it, so these catch registry/import breakage without paying
for mission analyses. End-to-end execution of the shared script runner is
covered in the sdk and oas suites.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import hangar.ocp.study_runner  # noqa: F401  (registers the "ocp" runner)
from hangar.sdk.study.orchestrate import generate_study


@pytest.fixture(autouse=True)
def isolate_prov_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HANGAR_PROV_DB", str(tmp_path / "prov.db"))


def _study(tmp_path: Path, mission_tool: str = "configure_mission") -> Path:
    steps = [
        {"id": "ac", "tool": "load_aircraft_template",
         "args": {"template": "kingair"}},
        {"id": "prop", "tool": "set_propulsion_architecture",
         "args": {"architecture": "turboprop"}},
        {"id": "mission", "tool": mission_tool,
         "args": {"mission_type": "basic", "cruise_range_nm": 300.0}},
        {"id": "run", "tool": "run_mission_analysis", "args": {}},
    ]
    study = {
        "metadata": {"id": "ocp-range-smoke", "name": "OCP range sweep",
                     "version": 1},
        "defaults": {"runner": "ocp", "spec": {"steps": steps}},
        "cases": [
            {"matrix": {
                "id_template": "r{range:g}",
                "axes": {"range": {"values": [200.0, 400.0]}},
                "bind": {"range": ["steps[mission].args.cruise_range_nm"]},
            }},
        ],
        "outputs": [{"name": "fuel_kg", "path": "run:results.fuel_burn_kg"}],
    }
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(study))
    return path


def test_generate_builds_registry_and_binds_range(tmp_path):
    path = _study(tmp_path)
    result = generate_study(path, store_root=tmp_path / "store")
    assert len(result["generated"]) == 2
    ranges = sorted(
        json.loads(Path(item["artifact"]).read_text())[2]["args"]["cruise_range_nm"]
        for item in result["generated"])
    assert ranges == [200.0, 400.0]


def test_generate_rejects_unknown_tool(tmp_path):
    path = _study(tmp_path, mission_tool="configure_missoin")  # typo
    with pytest.raises(ValueError, match="configure_missoin"):
        generate_study(path, store_root=tmp_path / "store")
