"""Unit tests for the physics summary module.

Migration: upstream/OpenAeroStruct/oas_mcp/tests/test_summary.py
Import mapping:
    oas_mcp.core.summary → hangar.oas.summary
"""

from __future__ import annotations

import pytest
from hangar.oas.summary import (
    _compute_delta,
    _deflection_metrics,
    _drag_breakdown,
    _sectional_metrics,
    _weight_balance,
    summarize_aero,
    summarize_aerostruct,
    summarize_drag_polar,
    summarize_optimization,
    summarize_stability,
)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestWeightBalance:
    # L_equals_W = 1 - L/W (normalized): positive = lift deficit

    def test_trimmed_small_residual(self):
        assert _weight_balance(0.0) == "trimmed"
        assert _weight_balance(0.005) == "trimmed"
        assert _weight_balance(-0.005) == "trimmed"

    def test_surplus(self):
        assert _weight_balance(-0.05) == "lift_surplus"

    def test_deficit(self):
        assert _weight_balance(0.05) == "lift_deficit"

    def test_none(self):
        assert _weight_balance(None) == "unknown"


class TestDragBreakdown:
    def test_basic_breakdown(self):
        surf = {"CDi": 0.008, "CDv": 0.002, "CDw": 0.0}
        bd = _drag_breakdown(surf)
        assert bd["CDi"] == pytest.approx(80.0)
        assert bd["CDv"] == pytest.approx(20.0)
        assert bd["CDw"] == pytest.approx(0.0)

    def test_zero_total_returns_empty(self):
        assert _drag_breakdown({"CDi": 0.0, "CDv": 0.0, "CDw": 0.0}) == {}

    def test_missing_keys(self):
        bd = _drag_breakdown({"CDi": 0.01})
        assert bd["CDi"] == pytest.approx(100.0)


class TestSectionalMetrics:
    def test_basic_metrics(self):
        # cl_vals[0] = tip, cl_vals[-1] = root (OAS convention)
        standard_detail = {
            "sectional_data": {
                "wing": {"Cl": [0.3, 0.35, 0.4]}  # tip=0.3, root=0.4
            }
        }
        m = _sectional_metrics(standard_detail, "wing")
        assert m["cl_tip"] == pytest.approx(0.3)
        assert m["cl_root"] == pytest.approx(0.4)
        assert m["cl_ratio_tip_root"] == pytest.approx(0.75, abs=0.01)

    def test_missing_surface(self):
        m = _sectional_metrics({"sectional_data": {}}, "nonexistent")
        assert m == {}

    def test_empty_standard_detail(self):
        m = _sectional_metrics(None, "wing")
        assert m == {}

    def test_insufficient_cl_vals(self):
        standard_detail = {"sectional_data": {"wing": {"Cl": [0.4]}}}
        m = _sectional_metrics(standard_detail, "wing")
        assert m == {}


class TestComputeDelta:
    def test_basic_delta(self):
        current = {"CL": 0.5, "CD": 0.02}
        previous = {"CL": 0.45, "CD": 0.022}
        delta = _compute_delta(current, previous, ["CL", "CD"])
        assert delta["CL"] == pytest.approx(0.05, abs=1e-5)
        assert delta["CD"] == pytest.approx(-0.002, abs=1e-5)

    def test_none_previous_returns_none(self):
        assert _compute_delta({"CL": 0.5}, None, ["CL"]) is None

    def test_missing_key_skipped(self):
        delta = _compute_delta({"CL": 0.5}, {"CL": 0.4, "CD": 0.02}, ["CL", "CD"])
        assert "CL" in delta
        assert "CD" not in delta  # CD missing from current

    def test_empty_result_returns_none(self):
        delta = _compute_delta({}, {"CL": 0.5}, ["CL"])
        assert delta is None


# ---------------------------------------------------------------------------
# Entry-point tests
# ---------------------------------------------------------------------------


class TestSummarizeAero:
    def _make_results(self, CL=0.5, CD=0.025, alpha=5.0):
        return {
            "CL": CL,
            "CD": CD,
            "CM": -0.05,
            "L_over_D": CL / CD,
            "surfaces": {
                "wing": {"CL": CL, "CDi": 0.018, "CDv": 0.007, "CDw": 0.0}
            },
        }

    def test_returns_required_keys(self):
        summary = summarize_aero(self._make_results(), context={"alpha": 5.0})
        assert "narrative" in summary
        assert "derived_metrics" in summary
        assert "flags" in summary
        assert "delta" in summary

    def test_narrative_contains_cl(self):
        summary = summarize_aero(self._make_results(CL=0.45), context={"alpha": 5.0})
        assert "CL=0.450" in summary["narrative"]
        assert "\u03b1=5.0\u00b0" in summary["narrative"]

    def test_drag_breakdown_in_derived(self):
        summary = summarize_aero(self._make_results(), context={"alpha": 5.0})
        assert "drag_breakdown_pct" in summary["derived_metrics"]
        bd = summary["derived_metrics"]["drag_breakdown_pct"]
        assert bd["CDi"] + bd["CDv"] + bd["CDw"] == pytest.approx(100.0, abs=0.1)

    def test_induced_drag_flag(self):
        # CDi dominates (>70%)
        results = self._make_results()
        summary = summarize_aero(results, context={"alpha": 5.0})
        assert "induced_drag_dominant" in summary["flags"]

    def test_delta_with_previous(self):
        prev = {"CL": 0.45, "CD": 0.026, "L_over_D": 17.3, "CM": -0.05}
        summary = summarize_aero(
            self._make_results(CL=0.5, CD=0.025), context={"alpha": 5.0}, previous=prev
        )
        assert summary["delta"] is not None
        assert summary["delta"]["CL"] == pytest.approx(0.05, abs=1e-5)

    def test_no_delta_without_previous(self):
        summary = summarize_aero(self._make_results(), context={"alpha": 5.0})
        assert summary["delta"] is None

    def test_tip_loaded_flag(self):
        standard_detail = {
            "sectional_data": {"wing": {"Cl": [0.5, 0.4, 0.3]}}  # tip=0.5, root=0.3
        }
        summary = summarize_aero(
            self._make_results(), standard_detail=standard_detail, context={"alpha": 5.0}
        )
        assert "tip_loaded" in summary["flags"]

    def test_tip_unloaded_flag(self):
        standard_detail = {
            "sectional_data": {"wing": {"Cl": [0.2, 0.35, 0.5]}}  # tip=0.2, root=0.5
        }
        summary = summarize_aero(
            self._make_results(), standard_detail=standard_detail, context={"alpha": 5.0}
        )
        assert "tip_unloaded" in summary["flags"]


class TestSummarizeAerostruct:
    def _make_results(self, failure=-0.3, lew=0.0, struct_mass=500.0,
                      tip_deflection=0.15, cg=None, fuel_vol=None):
        surf = {
            "CL": 0.5, "CDi": 0.018, "CDv": 0.007, "CDw": 0.0,
            "failure": failure, "max_vonmises_Pa": 120e6,
        }
        if tip_deflection is not None:
            surf["tip_deflection_m"] = tip_deflection
        if fuel_vol is not None:
            surf["total_fuel_volume_m3"] = fuel_vol
        results = {
            "CL": 0.5,
            "CD": 0.025,
            "CM": -0.05,
            "L_over_D": 20.0,
            "L_equals_W": lew,
            "structural_mass": struct_mass,
            "fuelburn": 5000.0,
            "surfaces": {"wing": surf},
        }
        if cg is not None:
            results["cg"] = cg
        return results

    def _make_standard_detail(self, semi_span=5.0):
        """Standard detail with mesh snapshot for deflection % span calc."""
        return {
            "sectional_data": {"wing": {"Cl": [0.3, 0.35, 0.4]}},
            "mesh_snapshot": {
                "wing": {
                    "leading_edge": [[-5.0, -semi_span, 0.0], [0.0, 0.0, 0.0]],
                    "trailing_edge": [[-5.0, -semi_span, 0.0], [1.0, 0.0, 0.0]],
                    "nx": 2, "ny": 2,
                }
            },
        }

    def test_returns_required_keys(self):
        summary = summarize_aerostruct(self._make_results(), context={"alpha": 5.0})
        for key in ("narrative", "derived_metrics", "flags", "delta"):
            assert key in summary

    def test_structural_margin(self):
        # failure = stress/allowable - 1, so -0.3 means 30% margin to allowable
        summary = summarize_aerostruct(self._make_results(failure=-0.3))
        assert "structural_margin_pct" in summary["derived_metrics"]
        assert summary["derived_metrics"]["structural_margin_pct"] == pytest.approx(30.0)

    def test_failure_flag(self):
        # Regression: 0.2 is 20% over allowable; the old > 1.0 threshold called it safe
        summary = summarize_aerostruct(self._make_results(failure=0.2))
        assert "structural_failure" in summary["flags"]
        assert "FAILS" in summary["narrative"]

    def test_near_yield_flag(self):
        summary = summarize_aerostruct(self._make_results(failure=-0.1))
        assert "near_yield" in summary["flags"]

    def test_weight_balance_trimmed(self):
        summary = summarize_aerostruct(self._make_results(lew=0.001))
        assert summary["derived_metrics"]["weight_balance"] == "trimmed"

    def test_weight_balance_deficit(self):
        # L_equals_W = 1 - L/W: positive residual means lift falls short of weight
        summary = summarize_aerostruct(self._make_results(lew=0.05))
        assert summary["derived_metrics"]["weight_balance"] == "lift_deficit"
        assert "lift_deficit" in summary["flags"]

    def test_weight_balance_surplus(self):
        summary = summarize_aerostruct(self._make_results(lew=-0.05))
        assert summary["derived_metrics"]["weight_balance"] == "lift_surplus"
        assert "lift_surplus" in summary["flags"]

    def test_structural_mass_fraction(self):
        summary = summarize_aerostruct(
            self._make_results(struct_mass=500.0), context={"alpha": 5.0, "W0": 10000.0}
        )
        assert "structural_mass_fraction_pct" in summary["derived_metrics"]
        assert summary["derived_metrics"]["structural_mass_fraction_pct"] == pytest.approx(5.0)

    def test_tip_deflection_in_derived(self):
        sd = self._make_standard_detail(semi_span=5.0)
        summary = summarize_aerostruct(
            self._make_results(tip_deflection=0.15), standard_detail=sd, context={"alpha": 5.0}
        )
        assert summary["derived_metrics"]["tip_deflection_m"] == pytest.approx(0.15, abs=0.01)
        assert summary["derived_metrics"]["tip_deflection_pct_span"] == pytest.approx(3.0, abs=0.1)

    def test_deflection_narrative(self):
        sd = self._make_standard_detail()
        summary = summarize_aerostruct(
            self._make_results(tip_deflection=0.15), standard_detail=sd, context={"alpha": 5.0}
        )
        assert "deflects" in summary["narrative"]
        assert "upward" in summary["narrative"]

    def test_downward_deflection_narrative(self):
        sd = self._make_standard_detail()
        summary = summarize_aerostruct(
            self._make_results(tip_deflection=-0.1), standard_detail=sd, context={"alpha": 5.0}
        )
        assert "downward" in summary["narrative"]

    def test_high_deflection_flag(self):
        sd = self._make_standard_detail(semi_span=5.0)
        # 1.0m out of 5.0m = 20% > 15% threshold
        summary = summarize_aerostruct(
            self._make_results(tip_deflection=1.0), standard_detail=sd, context={"alpha": 5.0}
        )
        assert "high_deflection" in summary["flags"]

    def test_no_high_deflection_flag_below_threshold(self):
        sd = self._make_standard_detail(semi_span=5.0)
        # 0.15m out of 5.0m = 3% < 15%
        summary = summarize_aerostruct(
            self._make_results(tip_deflection=0.15), standard_detail=sd, context={"alpha": 5.0}
        )
        assert "high_deflection" not in summary["flags"]

    def test_cg_x_in_derived(self):
        summary = summarize_aerostruct(
            self._make_results(cg=[10.5, 0.0, 0.5]), context={"alpha": 5.0}
        )
        assert summary["derived_metrics"]["cg_x_m"] == pytest.approx(10.5)

    def test_no_cg_when_absent(self):
        summary = summarize_aerostruct(
            self._make_results(cg=None), context={"alpha": 5.0}
        )
        assert "cg_x_m" not in summary["derived_metrics"]

    def test_fuel_volume_in_derived(self):
        summary = summarize_aerostruct(
            self._make_results(fuel_vol=0.05), context={"alpha": 5.0}
        )
        assert summary["derived_metrics"]["total_fuel_volume_m3"] == pytest.approx(0.05)

    def test_no_tip_deflection_when_absent(self):
        summary = summarize_aerostruct(
            self._make_results(tip_deflection=None), context={"alpha": 5.0}
        )
        assert "tip_deflection_m" not in summary["derived_metrics"]
        assert "deflects" not in summary["narrative"]


class TestDeflectionMetrics:
    def test_basic_deflection(self):
        results = {"surfaces": {"wing": {"tip_deflection_m": 0.2}}}
        sd = {
            "mesh_snapshot": {
                "wing": {"leading_edge": [[0, -5, 0], [0, 0, 0]]}
            }
        }
        m = _deflection_metrics(results, sd, "wing")
        assert m["tip_deflection_m"] == pytest.approx(0.2, abs=0.01)
        assert m["tip_deflection_pct_span"] == pytest.approx(4.0, abs=0.1)

    def test_no_deflection_returns_empty(self):
        results = {"surfaces": {"wing": {}}}
        m = _deflection_metrics(results, None, "wing")
        assert m == {}

    def test_no_mesh_skips_pct_span(self):
        results = {"surfaces": {"wing": {"tip_deflection_m": 0.1}}}
        m = _deflection_metrics(results, None, "wing")
        assert "tip_deflection_m" in m
        assert "tip_deflection_pct_span" not in m


class TestSummarizeDragPolar:
    def _make_results(self):
        alphas = list(range(-5, 16))
        CLs = [0.08 * (a + 2) for a in alphas]  # zero lift at alpha=-2
        CDs = [0.005 + 0.004 * CL ** 2 for CL in CLs]
        LoDs = [cl / cd for cl, cd in zip(CLs, CDs)]
        best_idx = max(range(len(LoDs)), key=lambda i: LoDs[i])
        return {
            "alpha_deg": [float(a) for a in alphas],
            "CL": CLs,
            "CD": CDs,
            "CM": [0.0] * len(alphas),
            "L_over_D": LoDs,
            "best_L_over_D": {
                "alpha_deg": float(alphas[best_idx]),
                "CL": CLs[best_idx],
                "CD": CDs[best_idx],
                "L_over_D": LoDs[best_idx],
            },
        }

    def test_returns_required_keys(self):
        summary = summarize_drag_polar(self._make_results())
        for key in ("narrative", "derived_metrics", "flags", "delta"):
            assert key in summary

    def test_cd_min_present(self):
        summary = summarize_drag_polar(self._make_results())
        assert "cd_min" in summary["derived_metrics"]
        assert summary["derived_metrics"]["cd_min"] > 0

    def test_alpha_at_zero_cl(self):
        summary = summarize_drag_polar(self._make_results())
        assert "alpha_at_zero_cl" in summary["derived_metrics"]
        assert abs(summary["derived_metrics"]["alpha_at_zero_cl"] - (-2.0)) < 0.5

    def test_cl_alpha_approx(self):
        summary = summarize_drag_polar(self._make_results())
        assert "cl_alpha_approx" in summary["derived_metrics"]
        assert summary["derived_metrics"]["cl_alpha_approx"] == pytest.approx(0.08, abs=0.01)

    def test_narrative_contains_best_ld(self):
        summary = summarize_drag_polar(self._make_results())
        assert "Best L/D" in summary["narrative"]

    def test_delta_with_previous(self):
        results = self._make_results()
        prev_results = dict(results)
        prev_results["best_L_over_D"] = dict(results["best_L_over_D"])
        prev_results["best_L_over_D"]["L_over_D"] = results["best_L_over_D"]["L_over_D"] - 2.0
        summary = summarize_drag_polar(results, previous=prev_results)
        assert summary["delta"] is not None
        assert summary["delta"]["best_L_over_D"] == pytest.approx(2.0, abs=0.1)


class TestSummarizeStability:
    def test_stable_flag(self):
        results = {"static_margin": 0.1, "CL_alpha": 0.1, "stability": "statically stable"}
        summary = summarize_stability(results)
        assert "stable" in summary["flags"]
        assert "narrative" in summary
        assert "0.100" in summary["narrative"]

    def test_unstable_flag(self):
        results = {"static_margin": -0.05, "CL_alpha": 0.1, "stability": "statically unstable"}
        summary = summarize_stability(results)
        assert "unstable" in summary["flags"]

    def test_marginally_stable(self):
        results = {"static_margin": 0.03, "CL_alpha": 0.1, "stability": "marginally stable"}
        summary = summarize_stability(results)
        assert "marginally_stable" in summary["flags"]

    def test_delta_vs_previous(self):
        curr = {"static_margin": 0.12, "CL_alpha": 0.11}
        prev = {"static_margin": 0.10, "CL_alpha": 0.10}
        summary = summarize_stability(curr, previous=prev)
        assert summary["delta"]["static_margin"] == pytest.approx(0.02, abs=1e-5)

    def test_missing_static_margin(self):
        summary = summarize_stability({"CL_alpha": 0.1})
        assert "narrative" in summary
        assert summary["flags"] == []


class TestSummarizeOptimization:
    def _make_results(self, success=True, n_iters=10, failure=-0.2):
        obj_start = 0.025
        obj_final = 0.020
        return {
            "success": success,
            "optimized_design_variables": {"twist": [1.0, 2.0, 3.0], "alpha": [5.5]},
            "final_results": {
                "CL": 0.5, "CD": obj_final,
                "surfaces": {"wing": {"failure": failure}},
            },
            "optimization_history": {
                "initial_dvs": {"twist": [0.0, 0.0, 0.0], "alpha": [5.0]},
                "objective_values": [obj_start] + [
                    obj_start - (obj_start - obj_final) * i / (n_iters - 1)
                    for i in range(1, n_iters)
                ],
                "dv_history": {},
            },
        }

    def test_returns_required_keys(self):
        summary = summarize_optimization(self._make_results())
        for key in ("narrative", "derived_metrics", "flags", "delta"):
            assert key in summary

    def test_objective_improvement(self):
        summary = summarize_optimization(self._make_results())
        assert "objective_improvement_pct" in summary["derived_metrics"]
        assert summary["derived_metrics"]["objective_improvement_pct"] == pytest.approx(20.0, abs=1.0)

    def test_num_iterations(self):
        summary = summarize_optimization(self._make_results(n_iters=10))
        assert summary["derived_metrics"]["num_iterations"] == 10

    def test_converged_narrative(self):
        summary = summarize_optimization(self._make_results(success=True))
        assert "converged" in summary["narrative"].lower()

    def test_not_converged_flag(self):
        summary = summarize_optimization(self._make_results(success=False))
        assert "not_converged" in summary["flags"]
        assert "not converge" in summary["narrative"].lower()

    def test_dv_max_changes(self):
        summary = summarize_optimization(self._make_results())
        assert "dv_max_changes" in summary["derived_metrics"]
        assert "twist" in summary["derived_metrics"]["dv_max_changes"]
        assert summary["derived_metrics"]["dv_max_changes"]["twist"] == pytest.approx(3.0)

    def test_delta_always_none(self):
        summary = summarize_optimization(self._make_results())
        assert summary["delta"] is None

    def test_structural_failure_in_opt_flag(self):
        # failure = stress/allowable - 1: 0.2 is 20% over allowable
        summary = summarize_optimization(self._make_results(failure=0.2))
        assert "structural_failure_in_opt" in summary["flags"]
        assert "structural failure" in summary["narrative"].lower()

    def test_no_failure_flag_when_safe(self):
        summary = summarize_optimization(self._make_results(failure=-0.2))
        assert "structural_failure_in_opt" not in summary["flags"]
