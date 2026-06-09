"""Tests for mission tools."""

import pytest
from hangar.ocp.tools.aircraft import load_aircraft_template
from hangar.ocp.tools.propulsion import set_propulsion_architecture
from hangar.ocp.tools.mission import configure_mission, run_mission_analysis
from hangar.ocp.state import sessions


@pytest.fixture(autouse=True)
def reset_sessions():
    sessions.reset()
    yield
    sessions.reset()


async def test_configure_mission():
    result = await configure_mission(
        mission_type="basic",
        cruise_altitude=20000,
        mission_range=300,
        num_nodes=11,
    )
    assert result["mission_type"] == "basic"
    assert result["cruise_altitude_ft"] == 20000
    assert result["num_nodes"] == 11
    assert "climb" in result["phases"]
    assert "v0v1" not in result["phases"]


async def test_configure_mission_even_nodes():
    with pytest.raises(Exception, match="ODD"):
        await configure_mission(num_nodes=10)


async def test_takeoff_throttle_inert_on_basic_mission_warns():
    result = await configure_mission(mission_type="basic", takeoff_throttle=0.75)
    warnings = result.get("warnings", [])
    assert any("takeoff_throttle" in w and "full" in w for w in warnings)


async def test_reserve_params_inert_outside_reserve_mission_warns():
    result = await configure_mission(mission_type="full", loiter_duration=30)
    warnings = result.get("warnings", [])
    assert any("loiter_duration" in w and "with_reserve" in w for w in warnings)


async def test_hybridization_inert_on_nonhybrid_warns():
    await load_aircraft_template("caravan")
    await set_propulsion_architecture("turboprop")
    result = await configure_mission(mission_type="basic", cruise_hybridization=0.3)
    warnings = result.get("warnings", [])
    assert any("cruise_hybridization" in w and "not hybrid" in w for w in warnings)


async def test_clean_mission_has_no_warnings():
    result = await configure_mission(mission_type="full", takeoff_throttle=0.75)
    assert "warnings" not in result


async def test_hybrid_params_inert_on_nonhybrid_architecture_warns():
    await load_aircraft_template("caravan")
    result = await set_propulsion_architecture("turboprop", battery_weight=500, motor_rating=400)
    warnings = result.get("warnings", [])
    assert any("battery_weight" in w for w in warnings)
    assert any("motor_rating" in w for w in warnings)


@pytest.mark.slow
async def test_run_caravan_mission_analysis():
    """End-to-end: load template, set arch, configure, run."""
    await load_aircraft_template("caravan")
    await set_propulsion_architecture("turboprop")
    await configure_mission(
        mission_type="basic",
        cruise_altitude=18000,
        mission_range=250,
        num_nodes=11,
    )
    result = await run_mission_analysis()

    assert result["schema_version"] == "1.0"
    assert result["tool_name"] == "run_mission_analysis"
    assert "run_id" in result
    assert result["results"]["fuel_burn_kg"] > 0
    assert result["results"]["OEW_kg"] > 0
    assert result["validation"]["passed"]
