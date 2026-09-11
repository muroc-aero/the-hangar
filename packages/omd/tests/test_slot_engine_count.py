"""A propulsion slot models one engine; the mission must fly all of them.

OpenConcept's CFM56 path wraps ``propmodel`` in a ``doubler`` ExecComp for a
twin. Every pyCycle slot provider returns single-engine thrust and fuel flow,
so the slot path needs equivalent scaling -- without it a ``twin_turbofan``
flies on half its thrust, the steady-flight throttle balance has no solution,
and Newton cannot converge.

These run against the assembled model with stubbed training stages, so they
cost about a second.
"""

from __future__ import annotations

import numpy as np
import pytest

from hangar.omd.factories.ocp.builder import build_ocp_basic_mission

MISSION_PARAMS = {
    "cruise_altitude_ft": 35000.0, "mission_range_NM": 1500.0,
    "climb_vs_ftmin": 2000.0, "climb_Ueas_kn": 250.0,
    "cruise_Ueas_kn": 256.0, "descent_vs_ftmin": 1500.0,
    "descent_Ueas_kn": 250.0,
}

PYC_SLOT = {
    "provider": "pyc/surrogate",
    "config": {
        "archetype": "hbtf", "design_alt": 35000.0, "design_MN": 0.8,
        "design_Fn": 5900.0, "design_T4": 2857.0,
        "engine_params": {"thermo_method": "TABULAR"},
    },
}


def _build(slots, architecture="twin_turbofan"):
    prob, _meta = build_ocp_basic_mission(
        {
            "aircraft_template": "b738",
            "architecture": architecture,
            "num_nodes": 3,
            "mission_params": MISSION_PARAMS,
            "slots": slots,
            "solver_settings": {"solver_type": "newton", "maxiter": 1},
        },
        operating_points={},
    )
    prob.final_setup()
    return prob


def _phase_names(prob, phase="cruise"):
    grp = prob.model._get_subsystem(f"analysis.{phase}.acmodel")
    return [s.name for s in grp._subsystems_myproc]


def test_twin_gets_an_engine_count_multiplier(stub_deck, stub_vlm):
    prob = _build({"propulsion": PYC_SLOT})
    assert "n_engines" in _phase_names(prob)


def test_multiplier_scales_thrust_and_fuel_flow(stub_deck, stub_vlm):
    """Installed thrust is exactly num_engines x the per-engine value."""
    prob = _build({"propulsion": PYC_SLOT})
    comp = prob.model._get_subsystem("analysis.cruise.acmodel.n_engines")
    per_engine = np.array([12.0, 14.0, 16.0])
    fuel_per_engine = np.array([0.3, 0.4, 0.5])
    # Drive the comp's own inputs: propmodel feeds them in a real run, and
    # this test is about the scaling, not the connection.
    comp._inputs["thrust_per_engine"] = per_engine
    comp._inputs["fuel_flow_per_engine"] = fuel_per_engine
    comp.run_solve_nonlinear()

    assert comp._outputs["thrust"] == pytest.approx(2.0 * per_engine)
    assert comp._outputs["fuel_flow"] == pytest.approx(2.0 * fuel_per_engine)


def test_multiplier_is_wired_between_propmodel_and_the_mission(stub_deck,
                                                               stub_vlm):
    """propmodel feeds the multiplier, and the multiplier feeds the mission."""
    prob = _build({"propulsion": PYC_SLOT})
    src = prob.model.get_source

    # propmodel -> multiplier
    assert src("analysis.cruise.acmodel.n_engines.thrust_per_engine") == (
        "analysis.cruise.acmodel.propmodel.surrogate.thrust")

    # multiplier -> what the mission actually consumes: the steady-flight
    # acceleration balance and the fuel integrator both see installed values.
    assert src("analysis.cruise.haccel.thrust") == (
        "analysis.cruise.acmodel.n_engines.thrust")
    assert src("analysis.cruise.acmodel.intfuel.fuel_flow") == (
        "analysis.cruise.acmodel.n_engines.fuel_flow")


def test_single_engine_architecture_adds_no_multiplier(stub_deck, stub_vlm):
    """A turboprop has num_engines == 1; nothing to scale."""
    prob = _build({"propulsion": PYC_SLOT}, architecture="turboprop")
    assert "n_engines" not in _phase_names(prob)


def test_engine_count_can_be_overridden(stub_deck, stub_vlm):
    """A provider that already models the whole installation opts out."""
    slot = {"provider": "pyc/surrogate",
            "config": {**PYC_SLOT["config"], "engine_count": 1}}
    prob = _build({"propulsion": slot})
    assert "n_engines" not in _phase_names(prob)


def test_multiplier_applies_to_every_phase(stub_deck, stub_vlm):
    prob = _build({"propulsion": PYC_SLOT})
    for phase in ("climb", "cruise", "descent"):
        assert "n_engines" in _phase_names(prob, phase), phase
