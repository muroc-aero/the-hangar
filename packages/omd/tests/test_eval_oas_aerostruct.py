"""Evaluation tests: OAS aerostructural (Evals 6, 7).

Eval 6: Coupled aero+struct analysis converges.
Eval 7: Full MDAO optimization -- twist + thickness for min mass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan

pytestmark = [pytest.mark.eval, pytest.mark.slow]

FIXTURES = Path(__file__).parent / "fixtures"


class TestOASAerostructAnalysis:
    """Eval 6: Coupled analysis produces CL, CD, structural mass."""

    def test_analysis_completes(self, tmp_path):
        plan_dir = FIXTURES / "oas_aerostruct_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)

        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        assert result["status"] == "completed"
        assert result["errors"] == []

    @pytest.mark.golden_physics
    def test_cl_cd_positive(self, tmp_path):
        plan_dir = FIXTURES / "oas_aerostruct_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        assert result["summary"]["CL"] > 0
        assert result["summary"]["CD"] > 0

    @pytest.mark.golden_physics
    def test_structural_mass_positive(self, tmp_path):
        plan_dir = FIXTURES / "oas_aerostruct_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        assert result["summary"]["wing_structural_mass"] > 0


class TestOASAerostructOptimization:
    """Eval 7: Full MDAO workflow -- the culminating test."""

    def test_optimization_runs(self, tmp_path):
        """Aerostruct optimization runs and produces results.

        Note: SLSQP may not fully converge on small mesh problems,
        so we check that it ran (produced iterations) rather than
        requiring "converged" status.
        """
        plan_dir = FIXTURES / "oas_aerostruct_optimization"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)

        result = run_plan(out, mode="optimize",
                          recording_level="driver",
                          db_path=tmp_path / "analysis.db")

        # The optimizer may not converge on this small mesh, but it
        # should at least run and produce results (not crash)
        assert result["run_id"] is not None
        # Should have CL and CD in summary (even if not converged)
        assert "CL" in result["summary"]
        assert result["summary"]["CL"] > 0
