"""A mission node outside the engine's envelope has no throttle solution.

The three-tool B738 spent a long time looking like a solver problem when it
was a mission-definition problem: a constant 2000 ft/min climb to FL350
demands 75 kN at top of climb against 52 kN available, so the throttle
balance had no root. These checks answer that from the deck in milliseconds.
"""

from __future__ import annotations

import numpy as np
import pytest

from hangar.omd.diagnostics import (
    NodeMargin,
    format_margins,
    max_thrust_surface,
    required_thrust_kN,
)

# Two (alt, MN) lines with a clear thrust lapse: ~11,600 lbf at sea level,
# ~5,900 lbf at 35,000 ft -- the shape of the HBTF deck.
DECK = {
    "alt_ft": np.array([0.0, 0.0, 0.0, 35000.0, 35000.0, 35000.0]),
    "MN": np.array([0.2, 0.2, 0.2, 0.8, 0.8, 0.8]),
    "throttle": np.array([0.3, 0.7, 1.0, 0.3, 0.7, 1.0]),
    "thrust_lbf": np.array([3400.0, 7000.0, 11600.0, 1800.0, 3900.0, 5900.0]),
    "fuel_flow_lbm_s": np.array([0.69, 1.15, 2.23, 0.29, 0.72, 1.11]),
    "T4_degR": np.array([2117.1, 2539.9, 2857.0, 2117.1, 2539.9, 2857.0]),
    "converged": np.ones(6, dtype=bool),
}


def test_surface_uses_the_max_throttle_point_of_each_line():
    surface = max_thrust_surface(DECK, n_engines=1)
    assert surface(0.0, 0.2) == pytest.approx(11600.0 * 4.44822e-3)
    assert surface(35000.0, 0.8) == pytest.approx(5900.0 * 4.44822e-3)


def test_engine_count_scales_the_envelope():
    one = max_thrust_surface(DECK, n_engines=1)(35000.0, 0.8)
    two = max_thrust_surface(DECK, n_engines=2)(35000.0, 0.8)
    assert two == pytest.approx(2.0 * one)


def test_surface_ignores_inadmissible_points():
    """A runaway point must not inflate the apparent ceiling."""
    poisoned = {k: v.copy() for k, v in DECK.items()}
    poisoned["thrust_lbf"][5] = 6.563e10
    poisoned["converged"][5] = False          # the deck filter rejected it
    surface = max_thrust_surface(poisoned, n_engines=1)
    # Falls back to the next-highest admissible throttle on that line.
    assert surface(35000.0, 0.8) == pytest.approx(3900.0 * 4.44822e-3)


def test_required_thrust_includes_the_climb_angle_term():
    """Level flight needs drag; climbing needs drag plus a weight component."""
    level = required_thrust_kN(drag_kN=[40.0], weight_kg=[73000.0],
                               vs_ms=[0.0], Utrue_ms=[221.0])
    assert level[0] == pytest.approx(40.0)

    climbing = required_thrust_kN(drag_kN=[40.0], weight_kg=[73000.0],
                                  vs_ms=[10.16], Utrue_ms=[221.0])
    assert climbing[0] > level[0]
    assert climbing[0] == pytest.approx(
        40.0 + 73000.0 * 9.80665 * (10.16 / 221.0) / 1000.0)


def test_descent_can_demand_negative_thrust():
    """Steeper than the drag polar allows: no throttle setting works."""
    req = required_thrust_kN(drag_kN=[36.9], weight_kg=[73000.0],
                             vs_ms=[-7.62], Utrue_ms=[128.6])
    assert req[0] < 0


def test_margin_verdicts():
    feasible = NodeMargin("cruise", 0, 35000.0, 0.8, 43.9, 51.9)
    assert feasible.feasible
    assert feasible.margin_kN == pytest.approx(8.0)

    over = NodeMargin("climb", 2, 35000.0, 0.78, 75.2, 51.9)
    assert not over.feasible

    negative = NodeMargin("descent", 2, 0.0, 0.38, -3.1, 110.6)
    assert not negative.feasible, "negative demand has no root either"

    msg = format_margins([feasible, over, negative])
    assert "2/3" in msg
    assert "negative thrust" in msg


def test_all_feasible_reads_clean():
    msg = format_margins([NodeMargin("cruise", 0, 35000.0, 0.8, 43.9, 51.9)])
    assert "all 1 mission nodes" in msg
