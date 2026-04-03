"""Tests for the paraboloid factory."""

from __future__ import annotations

import pytest

from hangar.omd.factories.paraboloid import build_paraboloid


def test_paraboloid_analysis():
    """f(1, 2) = (1-3)^2 + 1*2 + (2+4)^2 - 3 = 4 + 2 + 36 - 3 = 39."""
    prob, metadata = build_paraboloid({}, {"x": 1.0, "y": 2.0})

    assert metadata["point_name"] == "paraboloid"
    assert "paraboloid.f_xy" in metadata["output_names"]

    prob.setup()
    prob.set_val("x", 1.0)
    prob.set_val("y", 2.0)
    prob.run_model()

    f = float(prob.get_val("f_xy")[0])
    assert f == pytest.approx(39.0, rel=1e-10)


def test_paraboloid_at_origin():
    """f(0, 0) = (0-3)^2 + 0 + (0+4)^2 - 3 = 9 + 16 - 3 = 22."""
    prob, _ = build_paraboloid({}, {})
    prob.setup()
    prob.run_model()

    f = float(prob.get_val("f_xy")[0])
    assert f == pytest.approx(22.0, rel=1e-10)


def test_paraboloid_optimization():
    """Optimize to analytic minimum: x=20/3, y=-22/3, f=-82/3."""
    import openmdao.api as om

    prob, _ = build_paraboloid({}, {})

    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["disp"] = False

    prob.model.add_design_var("x", lower=-50, upper=50)
    prob.model.add_design_var("y", lower=-50, upper=50)
    prob.model.add_objective("f_xy")

    prob.setup()
    prob.run_driver()

    x = float(prob.get_val("x")[0])
    y = float(prob.get_val("y")[0])
    f = float(prob.get_val("f_xy")[0])

    assert x == pytest.approx(20.0 / 3.0, rel=1e-4)
    assert y == pytest.approx(-22.0 / 3.0, rel=1e-4)
    assert f == pytest.approx(-82.0 / 3.0, rel=1e-4)


def test_paraboloid_partials():
    """Verify analytic partials pass check_partials."""
    prob, _ = build_paraboloid({}, {"x": 3.0, "y": -2.0})
    prob.setup()
    prob.set_val("x", 3.0)
    prob.set_val("y", -2.0)
    prob.run_model()

    data = prob.check_partials(out_stream=None, compact_print=True)
    for comp_name, comp_data in data.items():
        for (of, wrt), deriv_data in comp_data.items():
            rel_err = deriv_data["rel error"]
            # Handle both old dict format and new _ErrorData tuple format
            if hasattr(rel_err, "forward"):
                err = rel_err.forward
            else:
                err = rel_err.get("magnitude", rel_err)
            assert err < 1e-6
