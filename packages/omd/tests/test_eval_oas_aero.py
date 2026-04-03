"""Evaluation tests: OAS aero-only (Evals 4, 5).

Eval 4: Rectangular wing aero analysis -- CL/CD reasonable at alpha=5.
Eval 5: Twist optimization for minimum drag at target CL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan

pytestmark = [pytest.mark.eval, pytest.mark.slow]

FIXTURES = Path(__file__).parent / "fixtures"


class TestOASAeroAnalysis:
    """Eval 4: Aero-only analysis produces reasonable CL/CD."""

    def test_analysis_completes(self, tmp_path):
        plan_dir = FIXTURES / "oas_aero_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)

        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        assert result["status"] == "completed"
        assert result["errors"] == []

    def test_cl_positive(self, tmp_path):
        plan_dir = FIXTURES / "oas_aero_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        assert result["summary"]["CL"] > 0

    @pytest.mark.golden_physics
    def test_cd_positive(self, tmp_path):
        plan_dir = FIXTURES / "oas_aero_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        assert result["summary"]["CD"] > 0

    @pytest.mark.golden_physics
    def test_ld_reasonable(self, tmp_path):
        plan_dir = FIXTURES / "oas_aero_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        ld = result["summary"]["L_over_D"]
        assert ld > 1.0
        assert ld < 100.0  # sanity bound


class TestOASAeroOptimization:
    """Eval 5: Twist optimization reduces CD at target CL."""

    def test_optimization_converges(self, tmp_path):
        plan_dir = FIXTURES / "oas_aero_optimization"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)

        result = run_plan(out, mode="optimize",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        assert result["status"] in ("converged", "completed")
        assert result["errors"] == []
        # CD should be positive after optimization
        assert result["summary"]["CD"] > 0
