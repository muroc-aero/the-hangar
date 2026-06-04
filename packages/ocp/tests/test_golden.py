"""Golden tests: verify OCP produces same results as direct OpenConcept API."""

import contextlib
import copy
import io

import numpy as np
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


@pytest.mark.slow
@pytest.mark.golden_physics
def test_kingair_twin_matches_reference():
    """King Air C90GT (twin turboprop) via OCP must match direct OpenConcept API.

    Regression for two twin-engine wiring bugs:
      * OEW must sum BOTH engines (engines_weight), not one.
      * the balanced-field takeoff must see propulsor_active (engine-out),
        which requires the flag to be promoted into the propulsion model.

    The reference example (KingAirC90GT.py) calibrates with structural_fudge
    =1.67, takeoff throttle =0.75, and prop rpm =1900; we apply the same on the
    built problem so the comparison isolates the model wiring, not the inputs.
    """
    data = copy.deepcopy(AIRCRAFT_TEMPLATES["kingair"]["data"])

    prob, metadata = build_mission_problem(
        aircraft_data=data,
        architecture="twin_turboprop",
        mission_type="full",
        mission_params={
            "cruise_altitude_ft": 29000.0,
            "mission_range_NM": 1000.0,
            "climb_vs_ftmin": 1500.0,
            "climb_Ueas_kn": 124.0,
            "cruise_Ueas_kn": 170.0,
            "descent_vs_ftmin": -600.0,
            "descent_Ueas_kn": 140.0,
            "payload_lb": 1000.0,
        },
        num_nodes=11,
        solver_settings={},
    )

    nn = metadata["num_nodes"]
    for phase in metadata["phases"]:
        with contextlib.suppress(Exception):
            prob.set_val(f"{phase}.OEW.structural_fudge", 1.67)
        prob.set_val(f"{phase}.proprpm", np.ones(nn) * 1900, units="rpm")
    for phase in ("v0v1", "v1vr", "rotate"):
        prob.set_val(f"{phase}.throttle", np.ones(nn) * 0.75)

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        prob.run_model()

    results = extract_mission_results(prob, metadata)

    # Run reference OpenConcept example (uses the same calibration internally).
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from openconcept.examples.KingAirC90GT import run_kingair_analysis
        prob_ref = run_kingair_analysis()

    ref_oew = float(prob_ref.get_val("climb.OEW", units="kg")[0])
    ref_fuel = float(prob_ref.get_val("descent.fuel_used_final", units="kg")[0])
    ref_tofl = float(prob_ref.get_val("rotate.range_final", units="ft")[0])

    assert abs(results["OEW_kg"] - ref_oew) / ref_oew < 0.001, (
        f"OEW mismatch: OCP={results['OEW_kg']:.2f} vs ref={ref_oew:.2f}"
    )
    assert abs(results["fuel_burn_kg"] - ref_fuel) / ref_fuel < 0.01, (
        f"Fuel mismatch: OCP={results['fuel_burn_kg']:.2f} vs ref={ref_fuel:.2f}"
    )
    assert abs(results["TOFL_ft"] - ref_tofl) / ref_tofl < 0.01, (
        f"TOFL mismatch: OCP={results['TOFL_ft']:.2f} vs ref={ref_tofl:.2f}"
    )
