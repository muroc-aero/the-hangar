"""Tests for the sweep and optimization tools.

The full solve paths are exercised by the golden/mission tests; these stay
fast by stubbing the problem build and pinning the tool-surface behavior:
input validation, sweep-table assembly, failure findings, and the
aircraft-data parameter routing.
"""

import pytest

import hangar.ocp.tools.sweep as sweep_mod
from hangar.ocp.state import sessions
from hangar.ocp.tools.optimization import run_optimization
from hangar.ocp.tools.sweep import run_parameter_sweep


@pytest.fixture(autouse=True)
def reset_sessions():
    sessions.reset()
    yield
    sessions.reset()


def _ready_session():
    """Make the default session pass the readiness validator."""
    session = sessions.get()
    session.aircraft_data = {
        "ac": {
            "weights": {"W_battery": {"value": 0.0, "units": "kg"}},
            "propulsion": {
                "engine": {"rating": {"value": 675, "units": "hp"}},
                "motor": {"rating": {"value": 0, "units": "hp"}},
            },
        }
    }
    session.propulsion_architecture = "turboprop"
    return session


# ---------------------------------------------------------------------------
# Input validation (no solve needed)
# ---------------------------------------------------------------------------


async def test_sweep_unknown_parameter_lists_valid():
    with pytest.raises(ValueError, match="Unknown sweep parameter.*mission_range"):
        await run_parameter_sweep(parameter="wingspan", values=[1, 2])


async def test_sweep_requires_configured_session():
    from hangar.sdk.errors import UserInputError

    with pytest.raises(UserInputError, match="No aircraft configured"):
        await run_parameter_sweep(parameter="mission_range", values=[200])


async def test_optimization_requires_design_variables():
    _ready_session()
    with pytest.raises(ValueError, match="At least one design variable"):
        await run_optimization(objective="fuel_burn")


async def test_optimization_unknown_objective_lists_valid():
    _ready_session()
    with pytest.raises(ValueError, match="Unknown objective.*fuel_burn"):
        await run_optimization(
            objective="range",
            design_variables=[{"name": "ac|weights|MTOW", "lower": 1, "upper": 2}],
        )


# ---------------------------------------------------------------------------
# Sweep assembly over a stubbed problem build
# ---------------------------------------------------------------------------


@pytest.fixture()
def stubbed_sweep(monkeypatch):
    """Stub the build/extract/finalize seams; capture what the sweep does."""
    captured = {"builds": []}

    class _FakeProb:
        def __init__(self, val):
            self._val = val

        def run_model(self):
            if self._val == 999:
                raise RuntimeError("Newton failed to converge")

    def fake_build(**kwargs):
        captured["builds"].append(kwargs)
        val = kwargs["mission_params"].get("mission_range_NM", 0)
        return _FakeProb(val), {"phases": ["cruise"]}

    def fake_extract(prob, metadata):
        return {"fuel_burn_kg": prob._val / 10.0, "profiles": {"cruise": {}}}

    async def fake_finalize(**kwargs):
        captured["finalize"] = kwargs
        return {"results": kwargs["results"],
                "findings": kwargs["findings"]}

    monkeypatch.setattr(sweep_mod, "build_mission_problem", fake_build)
    monkeypatch.setattr(sweep_mod, "extract_mission_results", fake_extract)
    monkeypatch.setattr(sweep_mod, "_finalize_analysis", fake_finalize)
    return captured


async def test_sweep_table_assembly(stubbed_sweep):
    _ready_session()
    out = await run_parameter_sweep(
        parameter="mission_range", values=[200, 400]
    )
    rows = out["results"]["sweep_results"]
    assert [r["mission_range"] for r in rows] == [200, 400]
    assert all(r["converged"] for r in rows)
    assert rows[0]["fuel_burn_kg"] == pytest.approx(20.0)
    # Nested dicts (profiles) are dropped from the per-point row.
    assert "profiles" not in rows[0]
    assert out["findings"] == []


async def test_sweep_failed_point_recorded_with_finding(stubbed_sweep):
    _ready_session()
    out = await run_parameter_sweep(
        parameter="mission_range", values=[200, 999]
    )
    rows = out["results"]["sweep_results"]
    assert rows[0]["converged"] is True
    assert rows[1]["converged"] is False
    assert "Newton" in rows[1]["error"]
    findings = out["findings"]
    assert len(findings) == 1
    assert findings[0].check_id == "numerics.sweep_convergence"
    assert "1/2" in findings[0].message


async def test_sweep_battery_weight_routes_into_aircraft_data(stubbed_sweep):
    _ready_session()
    await run_parameter_sweep(parameter="battery_weight", values=[300])
    build = stubbed_sweep["builds"][0]
    assert build["aircraft_data"]["ac"]["weights"]["W_battery"] == {
        "value": 300, "units": "kg",
    }
    # The session's own aircraft data must not be mutated by the sweep.
    assert sessions.get().aircraft_data["ac"]["weights"]["W_battery"][
        "value"
    ] == 0.0
