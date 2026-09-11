"""A pyCycle deck must be physically admissible, not merely non-negative.

``generate_deck`` keeps any point with ``thrust > 0 and fuel > 0``. An
off-design solve that wandered to a spurious root passes that test, and
Kriging -- which normalizes by the training standard deviation -- lets one
runaway point flatten every real point into noise. These tests run on deck
arrays, so they cost milliseconds even though producing a real deck costs
~20 minutes.
"""

from __future__ import annotations

import numpy as np
import pytest

from hangar.omd.diagnostics import check_deck, physically_converged
from hangar.omd.diagnostics.deck_quality import commanded_t4
from hangar.omd.pyc.surrogate import (
    DEFAULT_HBTF_GRID,
    clear_deck_cache,
    deck_cache_key,
)

DESIGN_FN = 5900.0
DESIGN_T4 = 2857.0


def _clean_deck() -> dict:
    """A small, wholly admissible HBTF-shaped deck."""
    alt = np.array([0.0, 0.0, 0.0, 35000.0, 35000.0, 35000.0])
    MN = np.array([0.2, 0.2, 0.2, 0.8, 0.8, 0.8])
    thr = np.array([0.3, 0.7, 1.0, 0.3, 0.7, 1.0])
    return {
        "alt_ft": alt,
        "MN": MN,
        "throttle": thr,
        # Monotone in throttle on each (alt, MN) line, sane magnitudes.
        "thrust_lbf": np.array([3400.0, 7000.0, 11600.0,
                                1800.0, 3900.0, 5900.0]),
        "fuel_flow_lbm_s": np.array([0.69, 1.15, 2.23, 0.29, 0.72, 1.11]),
        "T4_degR": commanded_t4(thr, DESIGN_T4),
        "converged": np.ones(6, dtype=bool),
    }


def test_clean_deck_is_admissible():
    report = check_deck(_clean_deck(), DESIGN_FN, DESIGN_T4)
    assert report.findings == [], report.summary()
    assert report.physics_ok.all()


def test_runaway_thrust_is_rejected():
    """The failure mode that poisons the fit: a 10-order-of-magnitude point.

    A diverged HBTF off-design solve at the 40,000 ft grid edge returned
    6.6e10 lbf with positive fuel flow, so the shipped ``thrust > 0`` test
    kept it.
    """
    deck = _clean_deck()
    deck["thrust_lbf"][4] = 6.563e10
    report = check_deck(deck, DESIGN_FN, DESIGN_T4)

    assert not report.physics_ok[4]
    assert list(report.rejected) == [4]
    assert any(f.check == "thrust_range" for f in report.findings)


def test_point_that_missed_commanded_t4_is_rejected():
    """A point can converge to a root that ignores the T4 it was given."""
    deck = _clean_deck()
    deck["T4_degR"][1] = 1915.8            # commanded ~2540 degR
    report = check_deck(deck, DESIGN_FN, DESIGN_T4)

    assert not report.physics_ok[1]
    assert any(f.check == "t4_held" for f in report.findings)


def test_frozen_line_is_rejected():
    """An OD solve unresponsive to throttle yields one value at every setting."""
    deck = _clean_deck()
    deck["thrust_lbf"][3:] = 8584.3
    deck["T4_degR"][3:] = 2394.5
    report = check_deck(deck, DESIGN_FN, DESIGN_T4)

    assert not report.physics_ok[3:].any()
    assert any(f.check in ("t4_held", "coverage") for f in report.findings)


def test_non_monotonic_line_is_reported():
    deck = _clean_deck()
    deck["thrust_lbf"][1] = 2000.0   # below the throttle=0.3 point
    report = check_deck(deck, DESIGN_FN, DESIGN_T4)
    assert any(f.check == "monotonic" for f in report.findings)


def test_nan_is_rejected():
    deck = _clean_deck()
    deck["thrust_lbf"][2] = np.nan
    assert not physically_converged(deck, DESIGN_FN, DESIGN_T4)[2]


# --- deck cache -------------------------------------------------------------


def test_deck_cache_key_is_order_insensitive():
    a = deck_cache_key("hbtf", {"alt": 35000.0, "MN": 0.8},
                       {"thermo_method": "TABULAR"}, DEFAULT_HBTF_GRID)
    b = deck_cache_key("hbtf", {"MN": 0.8, "alt": 35000.0},
                       {"thermo_method": "TABULAR"}, dict(DEFAULT_HBTF_GRID))
    assert a == b


def test_deck_cache_key_separates_configurations():
    base = deck_cache_key("hbtf", {"alt": 35000.0}, {}, None)
    assert base != deck_cache_key("hbtf", {"alt": 30000.0}, {}, None)
    assert base != deck_cache_key("turbojet", {"alt": 35000.0}, {}, None)
    assert base != deck_cache_key("hbtf", {"alt": 35000.0},
                                  {"thermo_method": "CEA"}, None)


def test_surrogate_group_generates_one_deck_per_configuration(monkeypatch):
    """An OCP mission builds the propulsion slot once per flight phase.

    Without the cache each phase pays the full off-design sweep and fits its
    own surrogate from what should be identical data.
    """
    import openmdao.api as om

    import hangar.omd.pyc.surrogate as surrogate

    clear_deck_cache()
    calls = []
    n = 8
    r = np.linspace(0.0, 1.0, n)
    deck = {
        "alt_ft": r * 40000.0, "MN": 0.2 + r * 0.65, "throttle": 0.3 + r * 0.7,
        "thrust_lbf": 2000.0 + r * 8000.0, "fuel_flow_lbm_s": 0.4 + r * 1.6,
        "T4_degR": 1800.0 + r * 1057.0, "converged": np.ones(n, dtype=bool),
    }

    def counted(**kwargs):
        calls.append(kwargs)
        return {k: v.copy() for k, v in deck.items()}

    monkeypatch.setattr(surrogate, "generate_deck", counted)

    def build(design_alt=35000.0):
        g = surrogate.PyCycleSurrogateGroup(
            nn=3, archetype="hbtf", design_alt=design_alt, design_MN=0.8,
            design_Fn=DESIGN_FN, design_T4=DESIGN_T4,
            engine_params={"thermo_method": "TABULAR"})
        p = om.Problem(reports=False)
        p.model.add_subsystem("prop", g)
        p.setup(check=False)
        return p

    for _ in range(3):                    # climb, cruise, descent
        build()
    assert len(calls) == 1, "identical slot configs should share one deck"

    build(design_alt=30000.0)             # a genuinely different engine
    assert len(calls) == 2

    clear_deck_cache()
    build()
    assert len(calls) == 3


@pytest.mark.slow
def test_real_hbtf_deck_is_admissible(tmp_path):
    """End-to-end guard on the real thing (~20 min); skipped by default.

    Run with ``-m slow``. Set ``HANGAR_HBTF_DECK`` to a saved ``.npz`` to
    check a deck you already have instead of generating one.
    """
    import os

    from hangar.omd.pyc.surrogate import generate_deck, load_deck

    saved = os.environ.get("HANGAR_HBTF_DECK")
    if saved:
        deck = load_deck(saved)
    else:
        deck = generate_deck(
            archetype="hbtf",
            design_conditions={"alt": 35000.0, "MN": 0.8,
                               "Fn_target": DESIGN_FN, "T4_target": DESIGN_T4},
            engine_params={"thermo_method": "TABULAR"},
        )
    report = check_deck(deck, DESIGN_FN, DESIGN_T4)
    assert len(report.rejected) == 0, report.summary()


# --- command_held (used by both deck paths) ---------------------------------


def test_command_held_accepts_a_point_that_reached_its_target():
    from hangar.omd.diagnostics import command_held

    assert command_held([5900.0], [5900.0]).all()
    assert command_held([2857.0], [2857.0]).all()


def test_command_held_rejects_a_point_that_settled_elsewhere():
    """The turbojet OD balances FAR to Fn_target; the HBTF is given a T4."""
    from hangar.omd.diagnostics import command_held

    assert not command_held([4200.0], [5900.0]).any()   # missed commanded Fn
    assert not command_held([2394.5], [2857.0]).any()   # missed commanded T4
    assert not command_held([np.nan], [5900.0]).any()
