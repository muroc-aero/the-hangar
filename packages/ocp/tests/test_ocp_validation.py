"""Tests for physics validation checks."""

from hangar.ocp.validation import (
    validate_mission_results,
    validate_aircraft_config,
    validate_optimization_results,
)


class TestValidateMissionResults:
    def test_good_results(self):
        results = {
            "fuel_burn_kg": 172.3,
            "OEW_kg": 2267.0,
            "MTOW_kg": 3970.0,
            "TOFL_ft": 1859.0,
        }
        findings = validate_mission_results(results)
        assert all(f.passed for f in findings)

    def test_negative_fuel_burn(self):
        results = {"fuel_burn_kg": -10.0}
        findings = validate_mission_results(results)
        fuel_finding = [f for f in findings if f.check_id == "physics.fuel_burn_positive"]
        assert len(fuel_finding) == 1
        assert not fuel_finding[0].passed

    def test_oew_greater_than_mtow(self):
        results = {"OEW_kg": 5000.0, "MTOW_kg": 3970.0}
        findings = validate_mission_results(results)
        oew_finding = [f for f in findings if f.check_id == "physics.oew_less_than_mtow"]
        assert len(oew_finding) == 1
        assert not oew_finding[0].passed

    def test_battery_soc_negative(self):
        results = {"battery_SOC_final": -0.05}
        findings = validate_mission_results(results)
        soc_finding = [f for f in findings if f.check_id == "physics.battery_soc_nonnegative"]
        assert len(soc_finding) == 1
        assert not soc_finding[0].passed

    def test_battery_soc_positive(self):
        results = {"battery_SOC_final": 0.15}
        findings = validate_mission_results(results)
        soc_finding = [f for f in findings if f.check_id == "physics.battery_soc_nonnegative"]
        assert len(soc_finding) == 1
        assert soc_finding[0].passed


class TestValidateAircraftConfig:
    def test_reasonable_config(self):
        data = {
            "ac": {
                "weights": {"MTOW": {"value": 3970, "units": "kg"}},
                "geom": {"wing": {"S_ref": {"value": 26.0, "units": "m**2"}}},
            },
        }
        findings = validate_aircraft_config(data, "turboprop")
        assert all(f.passed for f in findings)


class TestValidateOptimizationResults:
    def test_converged(self):
        results = {"optimization_successful": True, "num_iterations": 50}
        findings = validate_optimization_results(results)
        conv = [f for f in findings if f.check_id == "numerics.opt_converged"]
        assert len(conv) == 1
        assert conv[0].passed

    def test_not_converged(self):
        results = {"optimization_successful": False, "num_iterations": 200}
        findings = validate_optimization_results(results)
        conv = [f for f in findings if f.check_id == "numerics.opt_converged"]
        assert not conv[0].passed

    def test_suspicious_convergence(self):
        results = {"optimization_successful": True, "num_iterations": 1}
        findings = validate_optimization_results(results)
        sus = [f for f in findings if f.check_id == "numerics.suspicious_convergence"]
        assert len(sus) == 1
        assert not sus[0].passed
