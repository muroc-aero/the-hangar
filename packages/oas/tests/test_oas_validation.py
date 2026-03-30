"""Unit tests for OAS-specific validation checks.

Migrated from: OpenAeroStruct/oas_mcp/tests/test_validation.py (OAS-specific parts)

Import mapping applied:
  - oas_mcp.core.validation.validate_* -> hangar.oas.validation.validate_*
  - oas_mcp.core.validation.ValidationFinding -> hangar.sdk.validation.checks.ValidationFinding
  - oas_mcp.core.validation.findings_to_dict -> hangar.sdk.validation.checks.findings_to_dict
"""

from __future__ import annotations

import pytest
from hangar.oas.validation import (
    validate_aero,
    validate_aerostruct,
    validate_drag_polar,
    validate_optimization,
    validate_stability,
)
from hangar.sdk.validation.checks import (
    ValidationFinding,
    findings_to_dict,
)


# ---------------------------------------------------------------------------
# validate_aero
# ---------------------------------------------------------------------------


class TestValidateAero:
    def _good_results(self):
        return {"CL": 0.5, "CD": 0.035, "CM": -0.1, "L_over_D": 14.3, "surfaces": {}}

    def test_good_results_pass(self):
        findings = validate_aero(self._good_results(), context={"alpha": 5.0})
        agg = findings_to_dict(findings)
        assert agg["passed"] is True

    def test_negative_cd_fails(self):
        results = self._good_results()
        results["CD"] = -0.01
        findings = validate_aero(results)
        errors = [f for f in findings if not f.passed and f.severity == "error"]
        assert any(f.check_id == "physics.cd_positive" for f in errors)

    def test_cd_over_1_fails(self):
        results = self._good_results()
        results["CD"] = 1.5
        findings = validate_aero(results)
        errors = [f for f in findings if not f.passed]
        assert any(f.check_id == "physics.cd_not_too_large" for f in errors)

    def test_negative_cl_at_positive_alpha_warns(self):
        results = self._good_results()
        results["CL"] = -0.8  # unusual at positive alpha
        findings = validate_aero(results, context={"alpha": 5.0})
        warnings = [f for f in findings if not f.passed and f.severity in ("warning", "error")]
        assert any("cl_reasonable" in f.check_id for f in warnings)

    def test_negative_cl_at_negative_alpha_ok(self):
        results = self._good_results()
        results["CL"] = -0.4
        results["L_over_D"] = -11.0
        findings = validate_aero(results, context={"alpha": -5.0})
        # No error for CL check at negative alpha
        errors = [f for f in findings if not f.passed and f.severity == "error"]
        # CD is still positive, so no errors expected
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# validate_aerostruct
# ---------------------------------------------------------------------------


class TestValidateAerostruct:
    def _good_results(self):
        return {
            "CL": 0.5, "CD": 0.035, "CM": -0.1, "L_over_D": 14.3,
            "fuelburn": 90000.0, "structural_mass": 900.0,
            "L_equals_W": 0.0,
            "surfaces": {
                "wing": {"CL": 0.5, "CD": 0.035, "failure": -0.3, "max_vonmises_Pa": 100e6}
            },
        }

    def test_good_results_pass(self):
        findings = validate_aerostruct(self._good_results(), context={"alpha": 5.0, "W0": 120000})
        agg = findings_to_dict(findings)
        assert agg["passed"] is True

    def test_structural_failure_detected(self):
        results = self._good_results()
        results["surfaces"]["wing"]["failure"] = 1.5  # > 1.0 = failed
        findings = validate_aerostruct(results, context={"alpha": 5.0, "W0": 120000})
        errors = [f for f in findings if not f.passed and f.severity == "error"]
        assert any("structural_failure" in f.check_id for f in errors)

    def test_large_lew_residual_warns(self):
        results = self._good_results()
        results["L_equals_W"] = 50000.0  # large residual relative to W0
        findings = validate_aerostruct(results, context={"alpha": 5.0, "W0": 120000})
        failed = [f for f in findings if not f.passed]
        assert any("lew_residual" in f.check_id for f in failed)

    def test_negative_fuelburn_errors(self):
        results = self._good_results()
        results["fuelburn"] = -100.0
        findings = validate_aerostruct(results, context={"alpha": 5.0, "W0": 120000})
        errors = [f for f in findings if not f.passed and f.severity == "error"]
        assert any("fuelburn" in f.check_id for f in errors)

    def test_failure_below_1_passes(self):
        results = self._good_results()
        results["surfaces"]["wing"]["failure"] = 0.9  # approaching limit but not failed
        findings = validate_aerostruct(results, context={"alpha": 5.0, "W0": 120000})
        failure_checks = [f for f in findings if "structural_failure" in f.check_id]
        assert all(f.passed for f in failure_checks)


# ---------------------------------------------------------------------------
# validate_drag_polar
# ---------------------------------------------------------------------------


class TestValidateDragPolar:
    def _good_polar(self):
        return {
            "alpha_deg": [-5.0, 0.0, 5.0, 10.0],
            "CL": [-0.2, 0.0, 0.4, 0.8],
            "CD": [0.03, 0.025, 0.035, 0.06],
            "L_over_D": [None, 0.0, 11.4, 13.3],
            "best_L_over_D": {"alpha_deg": 10.0, "CL": 0.8, "CD": 0.06, "L_over_D": 13.3},
        }

    def test_good_polar_passes(self):
        findings = validate_drag_polar(self._good_polar())
        assert all(f.passed for f in findings if f.check_id == "physics.cd_positive_polar")

    def test_negative_cd_in_polar_fails(self):
        polar = self._good_polar()
        polar["CD"][0] = -0.01
        findings = validate_drag_polar(polar)
        failed = [f for f in findings if not f.passed]
        assert any("cd_positive_polar" in f.check_id for f in failed)

    def test_non_monotone_cl_warns(self):
        polar = self._good_polar()
        polar["CL"] = [0.0, 0.5, 0.3, 0.8]  # dips at index 2
        findings = validate_drag_polar(polar)
        failed = [f for f in findings if not f.passed]
        assert any("cl_monotonic" in f.check_id for f in failed)


# ---------------------------------------------------------------------------
# validate_stability
# ---------------------------------------------------------------------------


class TestValidateStability:
    def test_positive_cl_alpha_is_info(self):
        findings = validate_stability({"CL_alpha": 0.11, "static_margin": 0.1})
        cl_alpha_checks = [f for f in findings if "cl_alpha" in f.check_id]
        assert all(f.severity == "info" for f in cl_alpha_checks)

    def test_static_margin_normal_range_passes(self):
        for sm in [0.1, 0.2, 0.3]:
            findings = validate_stability({"CL_alpha": 0.1, "static_margin": sm})
            sm_checks = [f for f in findings if "static_margin" in f.check_id]
            assert all(f.passed for f in sm_checks)
            assert all(f.severity == "info" for f in sm_checks)

    def test_static_margin_dangerous_values_warn(self):
        for sm in [-0.1, 0.0, 0.03, 0.5]:
            findings = validate_stability({"CL_alpha": 0.1, "static_margin": sm})
            sm_checks = [f for f in findings if "static_margin" in f.check_id]
            assert all(not f.passed for f in sm_checks)
            assert all(f.severity == "warning" for f in sm_checks)


# ---------------------------------------------------------------------------
# validate_optimization
# ---------------------------------------------------------------------------


class TestValidateOptimization:
    def test_converged_optimization_passes(self):
        results = {
            "success": True,
            "final_results": {"CL": 0.5, "CD": 0.03},
            "optimized_design_variables": {},
        }
        findings = validate_optimization(results)
        conv_checks = [f for f in findings if "optimizer_converged" in f.check_id]
        assert all(f.passed for f in conv_checks)

    def test_failed_optimization_errors(self):
        results = {
            "success": False,
            "final_results": {"CL": 0.2, "CD": 0.05},
        }
        findings = validate_optimization(results)
        failed = [f for f in findings if not f.passed and f.severity == "error"]
        assert any("optimizer_converged" in f.check_id for f in failed)
