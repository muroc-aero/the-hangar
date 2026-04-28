"""Unit tests for the oas/AerostructBreguet factory.

Covers:
  * UserInputError when a required aircraft / engine config key is
    missing (factory is aircraft-agnostic; no module-level defaults).
  * B738-config single_cruise_breguet analysis-mode parity at 1500 nmi
    (regression check: fuel_burn_kg == 7726.293493 to 6 decimals).
  * Non-B738 (caravan-class) analysis-mode smoke test: positive fuel
    burn and L = W*cos(gamma) at the cruise point.
"""

from __future__ import annotations

import pytest

from hangar.sdk.errors import UserInputError


@pytest.fixture
def b738_config() -> dict:
    """B738 paper-spec config for single_cruise_breguet."""
    return {
        "mode": "single_cruise_breguet",
        "mission_range_nmi": 1500.0,
        "MTOW_kg": 79002.0,
        "tsfc_g_per_kN_s": 17.76,
        "orig_W_wing_kg": 6561.57,
        "payload_kg": 17260.0,
        "flight_points": [
            {"mach": 0.78, "altitude_ft": 35000.0, "weight_fraction": 0.5,
             "gamma_deg": 0.0},
        ],
        "surface_grid": dict(num_x=3, num_y=7, num_twist=4, num_toverc=4,
                             num_skin=4, num_spar=4),
        "maneuver": dict(load_factor=2.5, mach=0.78, altitude_ft=20000.0,
                         num_x=3, num_y=7, num_twist=4, num_toverc=4,
                         num_skin=4, num_spar=4),
    }


@pytest.fixture
def caravan_config() -> dict:
    """Caravan-class small turboprop config (different MTOW, TSFC, mesh)."""
    return {
        "mode": "single_cruise_breguet",
        "mission_range_nmi": 600.0,
        "MTOW_kg": 3970.0,
        "tsfc_g_per_kN_s": 28.0,
        "orig_W_wing_kg": 350.0,
        "payload_kg": 800.0,
        "flight_points": [
            {"mach": 0.30, "altitude_ft": 17000.0, "weight_fraction": 0.5,
             "gamma_deg": 0.0},
        ],
        "surface_grid": dict(num_x=3, num_y=5, num_twist=4, num_toverc=4,
                             num_skin=4, num_spar=4),
        "maneuver": dict(load_factor=2.5, mach=0.30, altitude_ft=10000.0,
                         num_x=3, num_y=5, num_twist=4, num_toverc=4,
                         num_skin=4, num_spar=4),
    }


def _import_factory():
    pytest.importorskip("openconcept")
    pytest.importorskip("openaerostruct")
    from hangar.omd.factories.oas_aerostruct_breguet import (
        build_oas_aerostruct_breguet,
    )
    return build_oas_aerostruct_breguet


@pytest.mark.parametrize(
    "missing_key",
    ["mode", "MTOW_kg", "tsfc_g_per_kN_s", "orig_W_wing_kg",
     "payload_kg", "mission_range_nmi", "maneuver"],
)
def test_required_key_raises_user_input_error(b738_config, missing_key):
    build = _import_factory()
    cfg = dict(b738_config)
    cfg.pop(missing_key)
    with pytest.raises(UserInputError) as exc:
        build(cfg, {})
    assert missing_key in str(exc.value)


def test_unknown_mode_raises_user_input_error(b738_config):
    build = _import_factory()
    cfg = dict(b738_config)
    cfg["mode"] = "single_point"  # the old (paper-terminology) name
    with pytest.raises(UserInputError) as exc:
        build(cfg, {})
    assert "single_cruise_breguet" in str(exc.value) or "valid_modes" in str(exc.value.details)


def test_maneuver_block_missing_subkey_raises(b738_config):
    build = _import_factory()
    cfg = dict(b738_config)
    cfg["maneuver"] = dict(cfg["maneuver"])
    cfg["maneuver"].pop("load_factor")
    with pytest.raises(UserInputError) as exc:
        build(cfg, {})
    assert "load_factor" in str(exc.value)


@pytest.mark.slow
def test_b738_single_cruise_breguet_analysis_parity(b738_config):
    """Regression: B738 single_cruise_breguet at 1500 nmi default IVCs
    reproduces the pre-rename Phase 0 parity number (7726.293493 kg)."""
    build = _import_factory()
    prob, meta = build(b738_config, {})
    prob.setup(check=False, mode="fwd")
    prob.run_model()
    fuel = float(prob.get_val("breguet.fuel_burn_kg", units="kg"))
    # Phase 0 verified parity with lane_b run-20260428T090219-0ac31ea9
    assert fuel == pytest.approx(7726.293493, rel=1e-5)


@pytest.mark.slow
def test_caravan_class_analysis_runs(caravan_config):
    """Smoke: a non-B738 aircraft config builds + runs analysis-mode
    without crashing. Asserts positive fuel burn and L = W*cos(gamma)
    at the cruise point (lift balance). num_y=5 keeps the surrogate
    training cheap enough for CI."""
    build = _import_factory()
    prob, meta = build(caravan_config, {})
    prob.setup(check=False, mode="fwd")
    prob.run_model()

    fuel = float(prob.get_val("breguet.fuel_burn_kg", units="kg"))
    assert fuel > 0.0

    L_target = float(prob.get_val("cruise_0.lift_target.L_target", units="N"))
    MTOW = float(prob.get_val("ac|weights|MTOW", units="kg"))
    g = 9.807
    weight_fraction = 0.5
    fuel_fraction_estimate = 0.10
    expected_L = MTOW * (1.0 - weight_fraction * fuel_fraction_estimate) * g
    assert L_target == pytest.approx(expected_L, rel=1e-6)
