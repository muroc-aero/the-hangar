"""Every BalanceComp in an assembled plan must be reachable by a solver.

These tests need no converged physics and no training stages: they assemble
the model, call ``final_setup()``, and walk the tree. A three-tool mission
that takes ~70 minutes to run end to end is audited here in under a second,
which is the point -- the defect this catches is invisible at the end of a
long run because ``NonlinearBlockGS`` reports success on a model it never
solved.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

from hangar.omd.diagnostics import find_unsolved_implicit, format_unsolved
from hangar.omd.factories.ocp.builder import build_ocp_basic_mission


@pytest.fixture
def stub_deck(monkeypatch):
    """Replace the ~20-minute pyCycle off-design sweep with 8 fake points.

    Structural coverage does not depend on the deck's contents, only on the
    shape of the model the slot builds.
    """
    import hangar.omd.pyc.surrogate as surrogate

    n = 8
    r = np.linspace(0.0, 1.0, n)
    deck = {
        "alt_ft": r * 40000.0,
        "MN": 0.2 + r * 0.65,
        "throttle": 0.3 + r * 0.7,
        "thrust_lbf": 2000.0 + r * 8000.0,
        "fuel_flow_lbm_s": 0.4 + r * 1.6,
        "T4_degR": 1800.0 + r * 1057.0,
        "converged": np.ones(n, dtype=bool),
    }
    monkeypatch.setattr(
        surrogate, "generate_deck",
        lambda **kw: {k: v.copy() for k, v in deck.items()},
    )
    return deck


@pytest.fixture
def stub_vlm(monkeypatch):
    """Replace the OAS VLM training grid with constant CL/CD."""
    from openconcept.aerodynamics.openaerostruct import drag_polar

    def cheap(self, inputs, outputs):
        outputs["CL_train"][:] = 0.5
        outputs["CD_train"][:] = 0.02

    monkeypatch.setattr(drag_polar.VLMDataGen, "compute", cheap)


THREE_TOOL_SLOTS = {
    "drag": {
        "provider": "oas/vlm",
        "config": {"num_x": 2, "num_y": 7, "num_twist": 4},
    },
    "propulsion": {
        "provider": "pyc/surrogate",
        "config": {
            "archetype": "hbtf", "design_alt": 35000.0, "design_MN": 0.8,
            "design_Fn": 5900.0, "design_T4": 2857.0,
            "engine_params": {"thermo_method": "TABULAR"},
        },
    },
}

MISSION_PARAMS = {
    "cruise_altitude_ft": 35000.0, "mission_range_NM": 1500.0,
    "climb_vs_ftmin": 2000.0, "climb_Ueas_kn": 250.0,
    "cruise_Ueas_kn": 256.0, "descent_vs_ftmin": 1500.0,
    "descent_Ueas_kn": 250.0,
}


def _build(solver_settings):
    """Assemble the three-tool plan exactly as lane_b/coupled_mission does."""
    prob, _meta = build_ocp_basic_mission(
        {
            "aircraft_template": "b738",
            "architecture": "twin_turbofan",
            "num_nodes": 3,
            "mission_params": MISSION_PARAMS,
            "slots": THREE_TOOL_SLOTS,
            "solver_settings": solver_settings,
        },
        operating_points={},
    )
    return prob


def test_newton_reaches_every_balance(stub_deck, stub_vlm):
    """The Newton setting solves all nine balances in a three-tool mission."""
    prob = _build({"solver_type": "newton", "maxiter": 30,
                   "atol": 1e-8, "rtol": 1e-8})
    unsolved = find_unsolved_implicit(prob)
    assert unsolved == [], format_unsolved(unsolved)


def test_nlbgs_leaves_every_balance_unsolved(stub_deck, stub_vlm):
    """NLBGS reaches no balance at all -- the defect this module exists for.

    ``NonlinearBlockGS`` only calls each subsystem's ``_solve_nonlinear``.
    ``BalanceComp`` defines none, and OpenConcept's mission groups carry no
    solvers of their own, so throttle, alpha, and phase duration all keep
    their initial values while the run reports success. This test pins the
    behaviour so that switching the three-tool plan to NLBGS again cannot
    pass silently.
    """
    prob = _build({"solver_type": "nlbgs", "maxiter": 200,
                   "atol": 1e-8, "rtol": 1e-8})
    unsolved = find_unsolved_implicit(prob)
    paths = {u.path for u in unsolved}

    assert unsolved, "expected NLBGS to leave balances unsolved"
    for phase in ("climb", "cruise", "descent"):
        assert f"analysis.{phase}.steadyflt" in paths          # throttle
        assert f"analysis.{phase}.acmodel.drag.alpha_bal" in paths
        assert any(p.startswith(f"analysis.{phase}.") and p.endswith("dt")
                   for p in paths)                              # duration


def test_audit_is_cheap(stub_deck, stub_vlm):
    """A model with no implicit components reports nothing."""
    p = om.Problem(reports=False)
    p.model.add_subsystem("c", om.ExecComp("y=2*x"), promotes=["*"])
    p.setup(check=False)
    assert find_unsolved_implicit(p) == []


def test_own_solver_counts_as_covered():
    """A balance carrying its own Newton is not reported."""
    p = om.Problem(reports=False)
    g = p.model.add_subsystem("g", om.Group())
    g.add_subsystem("bal", om.BalanceComp("x", lhs_name="lhs", rhs_name="rhs"))
    g.add_subsystem("f", om.ExecComp("lhs=x*x"))
    g.connect("bal.x", "f.x")
    g.connect("f.lhs", "bal.lhs")
    g.nonlinear_solver = om.NewtonSolver(solve_subsystems=False, iprint=0)
    g.linear_solver = om.DirectSolver()
    p.setup(check=False)
    assert find_unsolved_implicit(p) == []
