"""Golden tests: verify OCP produces same results as direct OpenConcept API."""

import copy
import pytest

from hangar.ocp.builders import build_mission_problem
from hangar.ocp.config.aircraft_templates import AIRCRAFT_TEMPLATES
from hangar.ocp.results import extract_mission_results


@pytest.fixture
def caravan_data():
    return copy.deepcopy(AIRCRAFT_TEMPLATES["caravan"]["data"])


@pytest.mark.slow
@pytest.mark.golden_physics
def test_caravan_fuel_burn_matches_reference(caravan_data):
    """Caravan fuel burn via OCP must match direct OpenConcept API."""
    import contextlib
    import io

    # Run via OCP builders
    prob, metadata = build_mission_problem(
        aircraft_data=caravan_data,
        architecture="turboprop",
        mission_type="full",
        mission_params={},
        num_nodes=11,
        solver_settings={},
    )

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        prob.run_model()

    results = extract_mission_results(prob, metadata)
    ocp_fuel = results["fuel_burn_kg"]

    # Run reference OpenConcept example
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from openconcept.examples.Caravan import run_caravan_analysis
        prob_ref = run_caravan_analysis()

    ref_fuel = float(prob_ref.get_val("descent.fuel_used_final", units="kg")[0])

    # Fuel burn must match within 0.1%
    assert abs(ocp_fuel - ref_fuel) / ref_fuel < 0.001, (
        f"Fuel burn mismatch: OCP={ocp_fuel:.4f} vs ref={ref_fuel:.4f}"
    )


@pytest.mark.slow
@pytest.mark.golden_physics
def test_caravan_basic_mission():
    """Caravan basic (no takeoff) mission runs without error."""
    data = copy.deepcopy(AIRCRAFT_TEMPLATES["caravan"]["data"])

    import contextlib
    import io

    prob, metadata = build_mission_problem(
        aircraft_data=data,
        architecture="turboprop",
        mission_type="basic",
        mission_params={},
        num_nodes=11,
        solver_settings={},
    )

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        prob.run_model()

    results = extract_mission_results(prob, metadata)
    assert results["fuel_burn_kg"] > 0
    assert results["OEW_kg"] > 0
    assert "TOFL_ft" not in results  # basic mission has no takeoff
