"""Tests for vehicle/config definition tools."""

import pytest

from hangar.evt.state import sessions as _sessions
from hangar.evt.tools.vehicle import (
    define_vehicle, list_vehicle_templates, load_vehicle_template,
    set_environment, set_power, set_propulsion,
)
from hangar.evt.tools.mission import configure_mission


async def test_list_templates():
    out = await list_vehicle_templates()
    assert "test_all" in out["templates"]
    assert out["count"] >= 1


async def test_load_template_populates_all_sections():
    out = await load_vehicle_template(template="test_all")
    assert set(out["sections"]) == {"aircraft", "mission", "power", "propulsion", "environ"}
    cfg = _sessions.get("default").config
    assert cfg["aircraft"]["max_takeoff_mass_kg"] == 3175.0


async def test_load_unknown_template_raises():
    with pytest.raises(ValueError, match="Unknown vehicle template"):
        await load_vehicle_template(template="does_not_exist")


async def test_setters_merge_overrides(loaded_vehicle):
    await define_vehicle(params={"payload_kg": 400.0})
    await set_power(params={"batt_spec_energy_w_h_p_kg": 280.0})
    await set_propulsion(params={"rotor_count": 8})
    await configure_mission(params={"cruise_s": 720.0})
    await set_environment(params={"air_density_sea_lvl_kg_p_m3": 1.18})
    cfg = _sessions.get("default").config
    assert cfg["aircraft"]["payload_kg"] == 400.0
    assert cfg["power"]["batt_spec_energy_w_h_p_kg"] == 280.0
    assert cfg["propulsion"]["rotor_count"] == 8
    assert cfg["mission"]["cruise_s"] == 720.0
    assert cfg["environ"]["air_density_sea_lvl_kg_p_m3"] == 1.18


async def test_unknown_key_rejected_with_suggestion(loaded_vehicle):
    # evtolpy silently ignores unknown keys -- the wrapper must reject them.
    with pytest.raises(ValueError, match="Unknown aircraft parameter"):
        await define_vehicle(params={"payload_KG": 400.0})


async def test_fraction_out_of_range_rejected(loaded_vehicle):
    with pytest.raises(ValueError, match="fraction/efficiency"):
        await set_power(params={"epu_effic": 1.5})


async def test_battery_spec_energy_range_rejected(loaded_vehicle):
    with pytest.raises(ValueError, match="batt_spec_energy"):
        await set_power(params={"batt_spec_energy_w_h_p_kg": 5.0})


async def test_int_key_rejected_for_float(loaded_vehicle):
    with pytest.raises(ValueError, match="non-negative integer"):
        await set_propulsion(params={"rotor_count": 6.5})


async def test_empty_params_rejected(loaded_vehicle):
    with pytest.raises(ValueError, match="No parameters"):
        await define_vehicle(params={})
