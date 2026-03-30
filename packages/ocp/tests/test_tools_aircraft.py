"""Tests for aircraft definition tools."""

import pytest
from hangar.ocp.tools.aircraft import (
    list_aircraft_templates,
    load_aircraft_template,
    define_aircraft,
)
from hangar.ocp.state import sessions


@pytest.fixture(autouse=True)
def reset_sessions():
    sessions.reset()
    yield
    sessions.reset()


async def test_list_templates():
    result = await list_aircraft_templates()
    assert result["count"] == 4
    assert "caravan" in result["templates"]
    assert "b738" in result["templates"]


async def test_load_caravan_template():
    result = await load_aircraft_template("caravan")
    assert result["template"] == "caravan"
    assert result["default_architecture"] == "turboprop"
    session = sessions.get("default")
    assert session.aircraft_data is not None
    assert session.aircraft_template == "caravan"


async def test_load_with_overrides():
    result = await load_aircraft_template(
        "caravan",
        overrides={"ac": {"weights": {"MTOW": {"value": 5000, "units": "kg"}}}},
    )
    session = sessions.get("default")
    assert session.aircraft_data["ac"]["weights"]["MTOW"]["value"] == 5000


async def test_load_invalid_template():
    with pytest.raises(ValueError, match="Unknown"):
        await load_aircraft_template("concorde")


async def test_define_custom_aircraft():
    result = await define_aircraft(S_ref=30.0, MTOW=5000.0, engine_rating=800)
    session = sessions.get("default")
    assert session.aircraft_data is not None
    assert session.aircraft_data["ac"]["geom"]["wing"]["S_ref"]["value"] == 30.0
    assert session.aircraft_data["ac"]["weights"]["MTOW"]["value"] == 5000.0
    assert session.aircraft_template is None
