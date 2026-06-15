"""Tests for session, artifact, and requirements tools."""

import pytest

from hangar.evt.tools.analysis import run_mission_analysis
from hangar.evt.tools.session import (
    get_artifact, get_detailed_results, get_run, list_artifacts,
    record_conclusion, set_requirements,
)


async def test_artifact_roundtrip(loaded_vehicle):
    env = await run_mission_analysis()
    run_id = env["run_id"]

    listed = await list_artifacts()
    assert listed["count"] >= 1

    art = await get_artifact(run_id)
    assert art["results"]["totals"]["total_mission_energy_kw_hr"] > 0

    run = await get_run(run_id)
    assert run["run_id"] == run_id
    assert run["outputs"] is not None


async def test_detailed_results_summary_mode(loaded_vehicle):
    run_id = (await run_mission_analysis())["run_id"]
    summary = await get_detailed_results(run_id, detail_level="summary")
    # summary drops nested dicts/lists.
    assert all(
        not isinstance(v, (list, dict)) for v in summary["results"].values()
    )


async def test_requirements_inject_findings(loaded_vehicle):
    # Impossible energy budget -> failed requirement appears in validation.
    await set_requirements(requirements=[
        {"label": "energy budget", "path": "totals.total_mission_energy_kw_hr",
         "operator": "<", "value": 1.0},
    ])
    env = await run_mission_analysis()
    assert env["validation"]["passed"] is False


async def test_record_conclusion(loaded_vehicle):
    await set_requirements(requirements=[
        {"label": "energy budget", "path": "totals.total_mission_energy_kw_hr",
         "operator": "<", "value": 500.0},
    ])
    run_id = (await run_mission_analysis())["run_id"]
    out = await record_conclusion(run_id, narrative="within budget")
    assert "verdict" in out
