"""Tests for input validators."""

import pytest

from hangar.evt.validators import (
    validate_section_params, validate_sweep_param, validate_template,
)


def test_validate_template_ok():
    validate_template("test_all")


def test_validate_template_bad():
    with pytest.raises(ValueError):
        validate_template("nope")


def test_section_params_unknown_key():
    with pytest.raises(ValueError, match="Unknown power parameter"):
        validate_section_params("power", {"epu_efficiency": 0.9})


def test_section_params_typo_suggestion():
    with pytest.raises(ValueError, match="did you mean"):
        validate_section_params("power", {"epu_effic_": 0.9})


def test_section_params_bool_rejected():
    with pytest.raises(ValueError, match="must be a number"):
        validate_section_params("power", {"epu_effic": True})


def test_section_params_ok():
    validate_section_params("propulsion", {"rotor_count": 8, "rotor_diameter_m": 2.5})


def test_sweep_param_ok():
    assert validate_sweep_param("power.batt_spec_energy_w_h_p_kg") == (
        "power", "batt_spec_energy_w_h_p_kg",
    )


def test_sweep_param_no_dot():
    with pytest.raises(ValueError, match="section.key"):
        validate_sweep_param("cruise_s")


def test_sweep_param_unknown_section():
    with pytest.raises(ValueError, match="Unknown sweep section"):
        validate_sweep_param("nope.key")
