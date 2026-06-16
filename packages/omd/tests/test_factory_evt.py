"""Tests for the evt (evtolpy) factories.

evt is a black-box factory wrapping the gradient-free evtolpy sizing library.
The headline check is parity: the factory must reproduce direct evtolpy exactly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("evtol")

from hangar.evt import builders, results  # noqa: E402
from hangar.evt.config.defaults import get_template  # noqa: E402
from hangar.omd.factories.evt import build_evt_mission, build_evt_sizing  # noqa: E402
from hangar.omd.run import _extract_summary  # noqa: E402


def _run(prob):
    prob.setup()
    prob.run_model()
    return prob


def test_metadata_shape():
    _, meta = build_evt_sizing({"template": "test_all"}, {})
    assert meta["component_family"] == "evt"
    assert meta["evt_mode"] == "sizing"
    assert "sized_mtow_kg" in meta["output_names"]
    # exposed default inputs are resolvable as DV/objective short names
    assert "batt_spec_energy_w_h_p_kg" in meta["var_paths"]
    assert meta["var_paths"]["sized_mtow_kg"] == "sized_mtow_kg"


def test_sizing_parity_with_direct_evtolpy():
    """sized MTOW from the factory must equal evtolpy's _iterate_mtow exactly."""
    prob, _ = build_evt_sizing({"template": "test_all"}, {})
    _run(prob)
    got = float(prob.get_val("sized_mtow_kg")[0])

    ac = builders.build_aircraft(get_template("test_all"))
    want = results.run_mtow_iteration(ac)["sized_mtow_kg"]

    assert got == pytest.approx(want, rel=0.0, abs=1e-9)
    assert float(prob.get_val("converged")[0]) == 1.0


@pytest.mark.slow  # full sizing run (~15s; evtolpy recomputes everything per iter)
def test_energy_read_at_as_configured_mtow():
    """Energy/peak power are reported pre-sizing (paper + evtolpy convention)."""
    prob, _ = build_evt_sizing({"template": "test_all"}, {})
    _run(prob)

    ac = builders.build_aircraft(get_template("test_all"))
    mission = results.extract_mission_results(ac)  # no sizing
    want_energy = mission["totals"]["total_mission_energy_kw_hr"]
    want_peak = max(mission["avg_electric_power_kw"].values())

    assert float(prob.get_val("total_mission_energy_kw_hr")[0]) == pytest.approx(
        want_energy, rel=0.0, abs=1e-9
    )
    assert float(prob.get_val("peak_power_kw")[0]) == pytest.approx(
        want_peak, rel=0.0, abs=1e-9
    )


def test_mission_mode_matches_extract():
    prob, _ = build_evt_mission({"template": "test_all"}, {})
    _run(prob)

    ac = builders.build_aircraft(get_template("test_all"))
    mission = results.extract_mission_results(ac)

    # mission mode does not size: sized == as-configured MTOW
    assert float(prob.get_val("sized_mtow_kg")[0]) == pytest.approx(
        mission["max_takeoff_mass_kg"], rel=0.0, abs=1e-9
    )
    assert float(prob.get_val("empty_mass_kg")[0]) == pytest.approx(
        mission["totals"]["empty_mass_kg"], rel=0.0, abs=1e-9
    )


@pytest.mark.slow  # full sizing run
def test_summary_carries_labeled_tables():
    prob, meta = build_evt_sizing({"template": "test_all"}, {})
    _run(prob)
    summary = _extract_summary(prob, meta, "analysis")
    assert len(summary["energy_kw_hr"]) == len(results.SEGMENT_KEYS)
    assert "cruise" in summary["energy_kw_hr"]
    assert summary["mass_breakdown_kg"]["wing_mass_kg"] > 0.0


def test_operating_point_override_routes_to_section():
    """An operating point keyed by an evtolpy config key reaches the aircraft.

    Uses mission mode (no sizing loop) so the check is fast and not subject to
    the MTOW-divergence the test_all template hits under a large cruise change.
    """
    base = get_template("test_all")
    base_cruise = base["mission"]["cruise_s"]
    prob, _ = build_evt_mission({"template": "test_all"}, {"cruise_s": base_cruise * 2})
    _run(prob)
    longer = float(prob.get_val("total_mission_energy_kw_hr")[0])

    prob0, _ = build_evt_mission({"template": "test_all"}, {})
    _run(prob0)
    baseline = float(prob0.get_val("total_mission_energy_kw_hr")[0])
    assert longer > baseline  # a longer cruise burns more energy


@pytest.mark.slow
def test_optimization_smoke_fd():
    """FD optimization over a DV runs and moves the design.

    Lowering battery specific energy raises battery mass and sized MTOW, so
    minimizing sized MTOW drives the DV to its upper bound.
    """
    import openmdao.api as om

    prob, _ = build_evt_sizing({"template": "test_all"}, {})
    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["maxiter"] = 2  # evtolpy sizing is ~15s/eval; keep it short
    prob.driver.options["disp"] = False

    prob.model.add_design_var("batt_spec_energy_w_h_p_kg", lower=200.0, upper=400.0)
    prob.model.add_objective("sized_mtow_kg")
    prob.setup()
    prob.set_val("batt_spec_energy_w_h_p_kg", 232.5)
    prob.run_model()
    mtow0 = float(prob.get_val("sized_mtow_kg")[0])

    prob.run_driver()
    mtow1 = float(prob.get_val("sized_mtow_kg")[0])
    dv = float(prob.get_val("batt_spec_energy_w_h_p_kg")[0])

    assert mtow1 <= mtow0 + 1e-6      # objective did not get worse
    assert dv > 232.5                  # DV moved toward the upper bound
