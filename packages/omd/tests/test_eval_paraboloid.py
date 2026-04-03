"""Evaluation tests: Paraboloid (Evals 1, 2, 3).

Eval 1: Analysis smoke test -- full pipeline end-to-end.
Eval 2: Optimization -- DVs + optimizer + convergence.
Eval 3: Export -- standalone script reproduces result.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan
from hangar.omd.export import export_plan_to_script

pytestmark = [pytest.mark.eval]

FIXTURES = Path(__file__).parent / "fixtures"


class TestParaboloidAnalysis:
    """Eval 1: f(1, 2) = 39.0."""

    def test_analysis_pipeline(self, tmp_path):
        plan_dir = FIXTURES / "paraboloid_analysis"
        out = tmp_path / "plan.yaml"
        result = assemble_plan(plan_dir, output=out)
        assert result["errors"] == []

        run_result = run_plan(out, mode="analysis",
                              recording_level="minimal",
                              db_path=tmp_path / "analysis.db")

        assert run_result["status"] == "completed"
        assert run_result["errors"] == []
        assert run_result["summary"]["f_xy"] == pytest.approx(39.0, rel=1e-10)

    @pytest.mark.golden_physics
    def test_paraboloid_minimum_bound(self, tmp_path):
        """f(x, y) >= -82/3 for all (x, y) -- the global minimum."""
        plan_dir = FIXTURES / "paraboloid_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis",
                          recording_level="minimal",
                          db_path=tmp_path / "analysis.db")
        assert result["summary"]["f_xy"] >= -82.0 / 3.0 - 1e-10


class TestParaboloidOptimization:
    """Eval 2: Optimal at x=20/3, y=-22/3, f=-82/3."""

    def test_optimization_converges(self, tmp_path):
        plan_dir = FIXTURES / "paraboloid_optimization"
        out = tmp_path / "plan.yaml"
        result = assemble_plan(plan_dir, output=out)
        assert result["errors"] == []

        run_result = run_plan(out, mode="optimize",
                              recording_level="driver",
                              db_path=tmp_path / "analysis.db")

        assert run_result["status"] in ("converged", "completed")
        assert run_result["errors"] == []
        assert run_result["summary"]["f_xy"] == pytest.approx(
            -82.0 / 3.0, rel=0.01
        )


class TestParaboloidExport:
    """Eval 3: Exported script produces same result."""

    def test_export_compiles(self, tmp_path):
        plan_dir = FIXTURES / "paraboloid_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)

        script = tmp_path / "standalone.py"
        export_plan_to_script(out, script)

        assert script.exists()
        ast.parse(script.read_text())

    def test_export_runs_and_matches(self, tmp_path):
        plan_dir = FIXTURES / "paraboloid_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)

        script = tmp_path / "standalone.py"
        export_plan_to_script(out, script)

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "39.0" in result.stdout or "f_xy" in result.stdout
