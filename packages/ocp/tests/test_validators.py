"""Tests for input validators."""

import pytest
from hangar.sdk.errors import UserInputError
from hangar.ocp.validators import (
    validate_architecture,
    validate_battery_specific_energy,
    validate_mission_params,
    validate_mission_type,
    validate_num_nodes,
    validate_session_ready_for_analysis,
    validate_aircraft_data_for_architecture,
)
from hangar.ocp.state import OcpSession


class TestValidateNumNodes:
    def test_odd_accepted(self):
        validate_num_nodes(3)
        validate_num_nodes(11)
        validate_num_nodes(21)

    def test_even_rejected(self):
        with pytest.raises(UserInputError, match="ODD"):
            validate_num_nodes(10)

    def test_too_small(self):
        with pytest.raises(UserInputError):
            validate_num_nodes(1)

    def test_too_large(self):
        with pytest.raises(UserInputError):
            validate_num_nodes(201)


class TestValidateArchitecture:
    def test_valid(self):
        validate_architecture("turboprop")
        validate_architecture("twin_series_hybrid")

    def test_invalid(self):
        with pytest.raises(UserInputError, match="Unknown"):
            validate_architecture("nuclear")


class TestValidateMissionType:
    def test_valid(self):
        validate_mission_type("full")
        validate_mission_type("basic")
        validate_mission_type("with_reserve")

    def test_invalid(self):
        with pytest.raises(UserInputError, match="Unknown"):
            validate_mission_type("supersonic")


class TestValidateMissionParams:
    def test_valid_params(self):
        validate_mission_params({
            "cruise_altitude_ft": 18000,
            "mission_range_NM": 250,
            "climb_vs_ftmin": 850,
        })

    def test_altitude_too_high(self):
        with pytest.raises(UserInputError, match="cruise_altitude"):
            validate_mission_params({"cruise_altitude_ft": 100000})

    def test_range_negative(self):
        with pytest.raises(UserInputError, match="mission_range"):
            validate_mission_params({"mission_range_NM": -10})


class TestValidateAircraftDataForArchitecture:
    def test_turboprop_valid(self):
        data = {
            "ac": {
                "propulsion": {
                    "engine": {"rating": {"value": 675}},
                    "propeller": {"diameter": {"value": 2.1}},
                },
            },
        }
        validate_aircraft_data_for_architecture(data, "turboprop")

    def test_turboprop_missing_propeller(self):
        data = {
            "ac": {
                "propulsion": {
                    "engine": {"rating": {"value": 675}},
                },
            },
        }
        with pytest.raises(UserInputError, match="propeller"):
            validate_aircraft_data_for_architecture(data, "turboprop")

    def test_hybrid_missing_motor(self):
        data = {
            "ac": {
                "propulsion": {
                    "engine": {"rating": {"value": 675}},
                    "propeller": {"diameter": {"value": 2.1}},
                },
                "weights": {},
            },
        }
        with pytest.raises(UserInputError, match="motor"):
            validate_aircraft_data_for_architecture(data, "series_hybrid")


class TestValidateSessionReady:
    def test_no_aircraft(self):
        session = OcpSession()
        with pytest.raises(UserInputError, match="aircraft"):
            validate_session_ready_for_analysis(session)

    def test_no_architecture(self):
        session = OcpSession(aircraft_data={"ac": {}})
        with pytest.raises(UserInputError, match="propulsion"):
            validate_session_ready_for_analysis(session)


class TestValidateBatterySpecEnergy:
    def test_valid(self):
        validate_battery_specific_energy(300)

    def test_too_low(self):
        with pytest.raises(UserInputError):
            validate_battery_specific_energy(10)

    def test_too_high(self):
        with pytest.raises(UserInputError):
            validate_battery_specific_energy(1000)
