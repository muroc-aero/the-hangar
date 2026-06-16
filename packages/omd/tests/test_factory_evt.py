"""Tests for the evt (evtolpy) factories.

``evt/Sizing`` and ``evt/Mission`` build the **native** OpenMDAO formulation
(``hangar.omd.evt``): idiomatic components with complex-step partials and a real
MTOW-closure solver. The headline checks are (1) parity with direct evtolpy and
(2) that analytic gradients flow through the sizing loop -- the capability the
black box lacked. ``evt/SizingFD`` keeps the gradient-free black box and must
still reproduce evtolpy bit-for-bit.
"""

from __future__ import annotations

import openmdao.api as om
import pytest

pytest.importorskip("evtol")

from hangar.evt import builders, results  # noqa: E402
from hangar.evt.config.defaults import get_template  # noqa: E402
from hangar.omd.factories.evt import (  # noqa: E402
    build_evt_mission,
    build_evt_sizing,
    build_evt_sizing_fd,
)
from hangar.omd.run import _extract_summary  # noqa: E402

# Native sizing converges tighter than evtolpy's loose |delta| < 1e-3 kg stop, so
# the sized MTOW agrees to ~1e-6 rather than bit-for-bit. Energy/mass/geometry
# (read pre-sizing or per-evaluation) match to floating point. 1e-5 is the
# established convention for sized MTOW across the evt parity suites.
_MTOW_RTOL = 1e-5
_EXACT = dict(rel=0.0, abs=1e-9)


def _run(prob, meta):
    """Set up + run a native evt problem the way the materializer does."""
    prob.setup(force_alloc_complex=bool(meta.get("force_alloc_complex")))
    for name, val in meta.get("initial_values", {}).items():
        prob.set_val(name, val)
    prob.run_model()
    return prob


def test_metadata_shape():
    _, meta = build_evt_sizing({"template": "test_all"}, {})
    assert meta["component_family"] == "evt"
    assert meta["evt_mode"] == "sizing"
    assert meta["native"] is True
    assert meta["force_alloc_complex"] is True
    assert "sized_mtow_kg" in meta["output_names"]
    # every config key is exposed as a resolvable DV/objective short name
    assert "batt_spec_energy_w_h_p_kg" in meta["var_paths"]
    assert "wingspan_m" in meta["var_paths"]
    assert meta["var_paths"]["sized_mtow_kg"] == "sized_mtow_kg"


def test_sizing_parity_with_direct_evtolpy():
    """Native sized MTOW matches evtolpy's _iterate_mtow to the sizing tolerance."""
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    _run(prob, meta)
    got = float(prob.get_val("sized_mtow_kg")[0])

    ac = builders.build_aircraft(get_template("test_all"))
    want = results.run_mtow_iteration(ac)["sized_mtow_kg"]

    assert got == pytest.approx(want, rel=_MTOW_RTOL)
    assert float(prob.get_val("converged")[0]) == 1.0


def test_sizing_masses_match_direct_evtolpy():
    """Sized component masses + empty/battery match evtolpy (per-evaluation, tight)."""
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    _run(prob, meta)

    ac = builders.build_aircraft(get_template("test_all"))
    sized = results.run_mtow_iteration(ac)
    # masses are evaluated at the converged MTOW; native converges slightly
    # tighter, so compare at the sizing tolerance.
    assert float(prob.get_val("empty_mass_kg")[0]) == pytest.approx(
        sized["totals"]["empty_mass_kg"], rel=_MTOW_RTOL)
    assert float(prob.get_val("battery_mass_kg")[0]) == pytest.approx(
        sized["totals"]["battery_mass_kg"], rel=_MTOW_RTOL)


def test_sizing_fd_blackbox_is_bit_exact():
    """The evt/SizingFD black box still reproduces evtolpy bit-for-bit."""
    prob, meta = build_evt_sizing_fd({"template": "test_all"}, {})
    prob.setup()
    for name, val in meta.get("initial_values", {}).items():
        prob.set_val(name, val)
    prob.run_model()

    ac = builders.build_aircraft(get_template("test_all"))
    want = results.run_mtow_iteration(ac)["sized_mtow_kg"]
    assert float(prob.get_val("sized_mtow_kg")[0]) == pytest.approx(want, **_EXACT)


def test_analytic_gradients_through_sizing_loop():
    """Total derivatives through the MTOW-closure loop are analytic (vs FD).

    This is the whole point of the native model: the black box could only FD the
    entire fixed-point loop per DV.
    """
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    _run(prob, meta)
    import numpy as np

    data = prob.check_totals(
        of=["sized_mtow_kg", "total_mission_energy_kw_hr"],
        wrt=["wingspan_m", "batt_spec_energy_w_h_p_kg", "cruise_s"],
        method="fd", out_stream=None,
    )
    for key, m in data.items():
        analytic = float(np.ravel(m["J_rev"])[0])
        fd = float(np.ravel(m["J_fd"])[0])
        assert analytic == pytest.approx(fd, rel=1e-4, abs=1e-6), key


def test_energy_read_at_as_configured_mtow():
    """Energy/peak power are reported pre-sizing (paper + evtolpy convention)."""
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    _run(prob, meta)

    ac = builders.build_aircraft(get_template("test_all"))
    mission = results.extract_mission_results(ac)  # no sizing
    want_energy = mission["totals"]["total_mission_energy_kw_hr"]
    want_peak = max(mission["avg_electric_power_kw"].values())

    assert float(prob.get_val("total_mission_energy_kw_hr")[0]) == pytest.approx(
        want_energy, **_EXACT)
    assert float(prob.get_val("peak_power_kw")[0]) == pytest.approx(
        want_peak, **_EXACT)


def test_mission_mode_matches_extract():
    prob, meta = build_evt_mission({"template": "test_all"}, {})
    _run(prob, meta)

    ac = builders.build_aircraft(get_template("test_all"))
    mission = results.extract_mission_results(ac)

    # mission mode does not size: sized == as-configured MTOW, masses there too
    assert float(prob.get_val("sized_mtow_kg")[0]) == pytest.approx(
        mission["max_takeoff_mass_kg"], **_EXACT)
    assert float(prob.get_val("empty_mass_kg")[0]) == pytest.approx(
        mission["totals"]["empty_mass_kg"], **_EXACT)


def test_summary_carries_labeled_tables():
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    _run(prob, meta)
    summary = _extract_summary(prob, meta, "analysis")
    assert len(summary["energy_kw_hr"]) == len(results.SEGMENT_KEYS)
    assert "cruise" in summary["energy_kw_hr"]
    assert summary["mass_breakdown_kg"]["wing_mass_kg"] > 0.0


def test_operating_point_override_routes_to_section():
    """An operating point keyed by an evtolpy config key reaches the aircraft."""
    base = get_template("test_all")
    base_cruise = base["mission"]["cruise_s"]
    prob, meta = build_evt_mission(
        {"template": "test_all"}, {"cruise_s": base_cruise * 2})
    _run(prob, meta)
    longer = float(prob.get_val("total_mission_energy_kw_hr")[0])

    prob0, meta0 = build_evt_mission({"template": "test_all"}, {})
    _run(prob0, meta0)
    baseline = float(prob0.get_val("total_mission_energy_kw_hr")[0])
    assert longer > baseline  # a longer cruise burns more energy


def test_optimization_smoke_analytic():
    """Gradient optimization over a DV runs on analytic derivatives and moves the design.

    Lowering battery specific energy raises battery mass and sized MTOW, so
    minimizing sized MTOW drives the DV to its upper bound.
    """
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["maxiter"] = 10
    prob.driver.options["disp"] = False

    prob.model.add_design_var("batt_spec_energy_w_h_p_kg", lower=200.0, upper=400.0)
    prob.model.add_objective("sized_mtow_kg")
    prob.setup(force_alloc_complex=True)
    for name, val in meta.get("initial_values", {}).items():
        prob.set_val(name, val)
    prob.set_val("batt_spec_energy_w_h_p_kg", 232.5)
    prob.run_model()
    mtow0 = float(prob.get_val("sized_mtow_kg")[0])

    prob.run_driver()
    mtow1 = float(prob.get_val("sized_mtow_kg")[0])
    dv = float(prob.get_val("batt_spec_energy_w_h_p_kg")[0])

    assert mtow1 <= mtow0 + 1e-6   # objective did not get worse
    assert dv > 232.5              # DV moved toward the upper bound
