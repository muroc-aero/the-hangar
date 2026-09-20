"""Unit tests for the pyCycle -> Aviary engine deck bridge (no pyCycle runs).

The sweep itself is exercised by the avy_three_tool parity case; here the
spec normalization, cache key, deck sanity check and the Aviary EngineDeck
construction from a synthetic (monotone) table are covered.
"""

from __future__ import annotations

import numpy as np
import pytest

from hangar.omd.pyc.aviary_deck import (
    DEFAULT_AVIARY_GRID,
    STATIC_MN,
    check_deck_sanity,
    deck_cache_key,
    deck_spec,
    deck_to_named_values,
    dropped_conditions,
    get_or_generate_deck,
    usable_mask,
)


def _synthetic_deck(alts=(0.0, 20000.0, 35000.0), mns=(0.0, 0.5, 0.8),
                    thrs=(0.5, 0.75, 1.0)):
    a, m, t = np.meshgrid(alts, mns, thrs, indexing="ij")
    a, m, t = a.ravel(), m.ravel(), t.ravel()
    fn = 12000.0 * t * (1.0 - a / 60000.0) * (1.0 - 0.3 * m)
    return {
        "alt_ft": a, "MN": m, "throttle": t, "thrust_lbf": fn,
        "fuel_flow_lbm_s": fn * 0.4 / 3600.0, "T4_degR": 1800.0 + 1000.0 * t,
        "converged": np.ones(a.size, dtype=bool),
    }


def test_spec_resolves_defaults_and_rejects_unknown_keys():
    spec = deck_spec("pyc/hbtf", {"engine_params": {"thermo_method": "TABULAR"}})
    assert spec["archetype"] == "hbtf"
    assert spec["design_conditions"] == {
        "alt": 35000.0, "MN": 0.8, "Fn_target": 5900.0, "T4_target": 2857.0,
    }
    assert spec["grid"] == {k: [float(v) for v in vs] for k, vs in DEFAULT_AVIARY_GRID.items()}
    with pytest.raises(ValueError, match="unknown keys"):
        deck_spec("pyc/hbtf", {"design_alt": 1.0})
    with pytest.raises(ValueError, match="provider"):
        deck_spec("pyc/nope", {})


def test_spec_requires_sls_point_in_grid():
    with pytest.raises(ValueError, match="alt_ft 0, MN 0 and throttle 1.0"):
        deck_spec("pyc/hbtf", {"grid": {"alt_ft": [10000.0], "MN": [0.5], "throttle": [1.0]}})


def test_cache_key_is_a_function_of_the_full_spec():
    base = deck_spec("pyc/hbtf", {})
    assert deck_cache_key(base) == deck_cache_key(deck_spec("pyc/hbtf", {}))
    assert deck_cache_key(base) != deck_cache_key(deck_spec("pyc/hbtf", {"design_MN": 0.78}))
    assert deck_cache_key(base) != deck_cache_key(
        deck_spec("pyc/hbtf", {"engine_params": {"thermo_method": "TABULAR"}})
    )


def test_cache_round_trip_without_regeneration(tmp_path, monkeypatch):
    """A cached .npz is loaded without calling generate_deck."""
    import hangar.omd.pyc.surrogate as surrogate

    spec = deck_spec("pyc/hbtf", {})
    deck = _synthetic_deck()
    path = tmp_path / f"hbtf_{deck_cache_key(spec)}.npz"
    surrogate.save_deck(deck, path)

    def _boom(*a, **k):
        raise AssertionError("generate_deck must not run on a cache hit")

    monkeypatch.setattr(surrogate, "generate_deck", _boom)
    loaded, info = get_or_generate_deck(spec, cache=tmp_path)
    assert info["cache_hit"] is True and info["path"] == str(path)
    assert info["n_points"] == deck["MN"].size == info["n_converged"]
    np.testing.assert_allclose(loaded["thrust_lbf"], deck["thrust_lbf"])


def test_generation_substitutes_static_mach(tmp_path, monkeypatch):
    """Mach 0 in the grid reaches pyCycle as its near-zero static value."""
    import hangar.omd.pyc.surrogate as surrogate

    seen = {}

    def _fake(archetype, design_conditions, engine_params, grid_spec):
        seen.update(grid_spec)
        return _synthetic_deck(mns=tuple(grid_spec["MN"]))

    monkeypatch.setattr(surrogate, "generate_deck", _fake)
    spec = deck_spec("pyc/hbtf", {})
    _deck, info = get_or_generate_deck(spec, cache=tmp_path)
    assert min(seen["MN"]) == STATIC_MN
    assert info["cache_hit"] is False and (tmp_path / f"hbtf_{info['sha']}.npz").exists()


def test_sanity_check_flags_bad_flight_conditions():
    deck = _synthetic_deck()
    assert check_deck_sanity(deck) == []
    bad = {k: v.copy() for k, v in deck.items()}
    # stale point: identical thrust at every throttle of one condition
    sel = (bad["alt_ft"] == 0.0) & (bad["MN"] == 0.0)
    bad["thrust_lbf"][sel] = 10919.2
    # a lone survivor after dropping non-converged points is dropped too
    sel2 = (bad["alt_ft"] == 35000.0) & (bad["MN"] == 0.5)
    bad["converged"][np.where(sel2)[0][:2]] = False
    problems = check_deck_sanity(bad)
    assert len(problems) == 1 and "not increasing" in problems[0]
    assert dropped_conditions(bad) == ["alt 35000 ft, MN 0.500"]
    assert usable_mask(bad).sum() == bad["MN"].size - 3


def test_named_values_masks_and_converts_units():
    pytest.importorskip("aviary")
    deck = _synthetic_deck()
    deck["converged"][0] = False
    data, n_used = deck_to_named_values(deck)
    assert n_used == deck["MN"].size - 1
    ff, units = data.get_item("fuel_flow")
    assert units == "lb/h"
    np.testing.assert_allclose(ff, deck["fuel_flow_lbm_s"][1:] * 3600.0)


def test_engine_deck_from_aircraft_values():
    """Engine options come from the aircraft deck minus the file-deck trio;
    Aviary reads the reference SLS thrust off the table."""
    pytest.importorskip("aviary")
    from aviary.utils.process_input_decks import create_vehicle
    from aviary.variable_info.variables import Aircraft

    from hangar.omd.pyc.aviary_deck import (
        _pycycle_engine_deck_class,
        engine_options_from,
    )

    aircraft, _ = create_vehicle(
        "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv"
    )
    opts = engine_options_from(aircraft)
    for var in (Aircraft.Engine.DATA_FILE, Aircraft.Engine.REFERENCE_SLS_THRUST,
                Aircraft.Engine.SCALE_FACTOR):
        assert var not in opts
    assert opts.get_val(Aircraft.Engine.NUM_ENGINES) == 2
    assert opts.get_val(Aircraft.Engine.SCALED_SLS_THRUST, "lbf") == pytest.approx(22200.0)

    deck = _synthetic_deck()
    data, _n = deck_to_named_values(deck)
    engine = _pycycle_engine_deck_class()(name="pyc_hbtf", options=opts, data=data)
    # SLS max thrust of the synthetic table: 12000 lbf at alt 0 / MN 0 / thr 1
    assert engine.get_val(Aircraft.Engine.REFERENCE_SLS_THRUST, "lbf") == pytest.approx(12000.0)
    assert engine.get_val(Aircraft.Engine.SCALE_FACTOR) == pytest.approx(22200.0 / 12000.0)
    assert [v.name for v in engine.inputs] == ["MACH", "ALTITUDE", "THROTTLE"]
    assert [v.name for v in engine.outputs] == ["THRUST", "FUEL_FLOW"]
