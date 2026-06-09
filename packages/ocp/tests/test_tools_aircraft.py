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
    # Overriding an existing field is silent -- no warnings.
    assert "warnings" not in result


async def test_overrides_warn_on_mission_calibration_keys():
    """structural_fudge / takeoff_throttle in overrides are a no-op and must warn."""
    result = await load_aircraft_template(
        "kingair",
        overrides={"structural_fudge": 1.67, "takeoff_throttle": 0.75},
    )
    warnings = result.get("warnings", [])
    assert len(warnings) == 2
    joined = " ".join(warnings)
    assert "structural_fudge" in joined
    assert "takeoff_throttle" in joined
    # The warning must point the agent to the correct tool.
    assert "configure_mission" in joined


async def test_overrides_warn_on_unknown_field():
    """An override path absent from the template warns as a no-op."""
    result = await load_aircraft_template(
        "caravan",
        overrides={"ac": {"weights": {"made_up_field": {"value": 1.0}}}},
    )
    warnings = result.get("warnings", [])
    assert len(warnings) == 1
    assert "ac|weights|made_up_field" in warnings[0]
    assert "no effect" in warnings[0]


async def test_overrides_flat_alias_points_to_nested_path():
    """A flat key like prop_rpm warns with the real nested path, not 'unknown'."""
    result = await load_aircraft_template("kingair", overrides={"prop_rpm": 1900})
    warnings = result.get("warnings", [])
    assert len(warnings) == 1
    assert "ac|propulsion|propeller|rpm" in warnings[0]
    assert "template already sets" in warnings[0]


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
