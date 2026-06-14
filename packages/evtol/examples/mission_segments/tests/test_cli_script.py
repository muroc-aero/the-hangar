"""CLI evaluation: run the Lane B JSON workflows through evtol-cli script mode.

Drives the real CLI entry point in a subprocess so the command-line path
(registry build, script parsing, in-memory state sharing across steps, JSON
output) is exercised end to end, not just the in-process tool functions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_LANE_B = Path(__file__).resolve().parents[1] / "lane_b"


def _run_script(script_name: str, out_path: Path) -> list:
    """Run a lane_b JSON workflow via evtol-cli and return parsed step results."""
    script = _LANE_B / script_name
    proc = subprocess.run(
        [
            sys.executable, "-c", "from hangar.evtol.cli import main; main()",
            "--save-to", str(out_path), "run-script", str(script),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"evtol-cli failed:\n{proc.stderr}"
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.mark.slow
@pytest.mark.parity
def test_cli_mission_script(tmp_path):
    results = _run_script("mission_analysis.json", tmp_path / "mission.json")
    # Two steps: load_vehicle_template, run_mission_analysis.
    assert len(results) == 2
    mission = results[-1]
    assert mission.get("ok") is True, mission
    payload = mission["result"]["results"]
    assert "cruise" in payload["energy_kw_hr"]
    assert payload["totals"]["total_mission_energy_kw_hr"] > 0


@pytest.mark.slow
@pytest.mark.parity
def test_cli_sizing_script(tmp_path):
    results = _run_script("sizing.json", tmp_path / "sizing.json")
    assert len(results) == 2
    sizing = results[-1]
    assert sizing.get("ok") is True, sizing
    payload = sizing["result"]["results"]
    assert payload["converged"] is True
    assert payload["sized_mtow_kg"] > 0
