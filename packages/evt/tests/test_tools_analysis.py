"""Tests for the analysis tools (run_mission_analysis, run_sizing)."""

import pytest

from hangar.evt.results import SEGMENT_KEYS
from hangar.evt.tools.analysis import run_mission_analysis, run_sizing
from hangar.evt.tools.vehicle import load_vehicle_template, set_power


async def test_mission_requires_config():
    with pytest.raises(ValueError, match="No vehicle defined"):
        await run_mission_analysis()


async def test_mission_envelope_shape(loaded_vehicle):
    env = await run_mission_analysis()
    assert env["schema_version"] == "1.0"
    assert env["tool_name"] == "run_mission_analysis"
    assert env["run_id"]
    r = env["results"]
    assert set(r["energy_kw_hr"]) == set(SEGMENT_KEYS)
    assert set(r["avg_electric_power_kw"]) == set(SEGMENT_KEYS)
    assert len(r["mass_breakdown_kg"]) == 15
    assert r["totals"]["total_mission_energy_kw_hr"] > 0
    assert "geometry" in r and "aero" in r and "propulsion" in r
    assert env["validation"]["passed"] is True


async def test_mission_matches_direct_api(loaded_vehicle):
    # Byte-for-byte against the upstream baseline numbers.
    r = (await run_mission_analysis())["results"]
    assert r["energy_kw_hr"]["cruise"] == pytest.approx(124.289885, rel=1e-6)
    assert r["totals"]["total_mission_energy_kw_hr"] == pytest.approx(166.77776, rel=1e-6)


async def test_sizing_envelope_and_convergence(loaded_vehicle):
    env = await run_sizing()
    r = env["results"]
    assert r["converged"] is True
    assert r["iterations"] == 37
    assert r["sized_mtow_kg"] == pytest.approx(4076.0876, rel=1e-5)
    assert len(r["history"]) == r["iterations"]
    assert env["validation"]["passed"] is True


async def test_sizing_diverges_on_bad_inputs(loaded_vehicle):
    # A tiny battery specific energy makes battery mass explode -> divergence.
    await set_power(params={"batt_spec_energy_w_h_p_kg": 60.0})
    with pytest.raises(ValueError):
        await run_sizing()
