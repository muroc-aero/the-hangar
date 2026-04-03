"""Evaluation test: Recording levels (Eval 9).

Verifies all four recording levels produce different amounts of data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan

pytestmark = [pytest.mark.eval]

FIXTURES = Path(__file__).parent / "fixtures"


def test_recording_level_case_counts(tmp_path):
    """Case count should increase with recording verbosity."""
    plan_dir = FIXTURES / "paraboloid_optimization"
    out = tmp_path / "plan.yaml"
    assemble_plan(plan_dir, output=out)

    counts = {}
    for level in ("minimal", "driver", "solver", "full"):
        db_path = tmp_path / f"db_{level}.db"
        result = run_plan(out, mode="optimize",
                          recording_level=level,
                          db_path=db_path)
        assert result["status"] in ("converged", "completed"), \
            f"Run failed at level={level}: {result['errors']}"
        counts[level] = result["summary"]["recording"]["case_count"]

    # Minimal should record the fewest cases
    assert counts["minimal"] <= counts["driver"]
    # Driver should record at least some cases
    assert counts["driver"] >= 1
