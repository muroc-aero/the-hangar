"""Parity tests: Lane A (direct scripts) vs Lane B (omd plan pipeline).

Verifies that running the same problem through direct OpenMDAO/OAS code
and through the omd plan pipeline produces matching results.

Run with -s to see comparison tables in the terminal:

    uv run pytest packages/omd/examples/tests/test_parity.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hangar.omd.assemble import assemble_plan
from hangar.omd.run import run_plan

EXAMPLES_DIR = Path(__file__).parent.parent


def _print_comparison(
    name: str,
    lane_a: dict,
    lane_b: dict,
    keys: list[str] | None = None,
) -> None:
    """Print a side-by-side comparison of lane A and lane B results."""
    if keys is None:
        keys = sorted(set(lane_a.keys()) | set(lane_b.keys()))

    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")
    print(f"  {'Metric':<25s} {'Lane A':>14s} {'Lane B':>14s} {'Diff':>10s}")
    print(f"  {'-' * 25} {'-' * 14} {'-' * 14} {'-' * 10}")
    for k in keys:
        a = lane_a.get(k)
        b = lane_b.get(k)
        if a is None or b is None:
            a_str = f"{a}" if a is not None else "N/A"
            b_str = f"{b}" if b is not None else "N/A"
            print(f"  {k:<25s} {a_str:>14s} {b_str:>14s} {'':>10s}")
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != 0:
            pct = 100.0 * (b - a) / abs(a)
            print(f"  {k:<25s} {a:>14.6g} {b:>14.6g} {pct:>+9.4f}%")
        else:
            print(f"  {k:<25s} {str(a):>14s} {str(b):>14s}")
    print(f"{'=' * 60}\n")


class TestParaboloidParity:

    def test_analysis_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "paraboloid"))
        from paraboloid.lane_a.analysis import run as lane_a_run

        lane_a = lane_a_run()

        plan_dir = EXAMPLES_DIR / "paraboloid" / "lane_b" / "analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison("Paraboloid Analysis", lane_a, result["summary"])

        assert result["summary"]["f_xy"] == pytest.approx(lane_a["f_xy"], rel=1e-12)

    def test_optimization_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "paraboloid"))
        from paraboloid.lane_a.optimization import run as lane_a_run

        lane_a = lane_a_run()

        plan_dir = EXAMPLES_DIR / "paraboloid" / "lane_b" / "optimization"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="optimize", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison("Paraboloid Optimization", lane_a, result["summary"])

        assert result["summary"]["f_xy"] == pytest.approx(lane_a["f_xy"], rel=1e-4)


class TestOASAeroParity:

    @pytest.mark.slow
    def test_aero_analysis_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "oas_aero_rect"))
        from oas_aero_rect.lane_a.aero_analysis import run as lane_a_run

        lane_a = lane_a_run()

        plan_dir = EXAMPLES_DIR / "oas_aero_rect" / "lane_b" / "aero_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison("OAS Aero Analysis", lane_a, result["summary"],
                          keys=["CL", "CD"])

        assert result["summary"]["CL"] == pytest.approx(lane_a["CL"], rel=1e-6)
        assert result["summary"]["CD"] == pytest.approx(lane_a["CD"], rel=1e-6)


class TestOASAerostructParity:

    @pytest.mark.slow
    def test_aerostruct_analysis_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "oas_aerostruct_rect"))
        from oas_aerostruct_rect.lane_a.aerostruct_analysis import run as lane_a_run

        lane_a = lane_a_run()

        plan_dir = EXAMPLES_DIR / "oas_aerostruct_rect" / "lane_b" / "aerostruct_analysis"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison("OAS Aerostruct Analysis", lane_a, result["summary"],
                          keys=["CL", "CD"])

        assert result["summary"]["CL"] == pytest.approx(lane_a["CL"], rel=1e-6)
        assert result["summary"]["CD"] == pytest.approx(lane_a["CD"], rel=1e-6)


class TestOCPCaravanBasicParity:

    @pytest.mark.slow
    def test_basic_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_caravan_basic"))
        from ocp_caravan_basic.lane_a.basic_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = EXAMPLES_DIR / "ocp_caravan_basic" / "lane_b" / "basic_mission" / "plan.yaml"
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP Caravan Basic Mission",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPCaravanFullParity:

    @pytest.mark.slow
    def test_full_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_caravan_full"))
        from ocp_caravan_full.lane_a.full_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = EXAMPLES_DIR / "ocp_caravan_full" / "lane_b" / "full_mission" / "plan.yaml"
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP Caravan Full Mission",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPHybridTwinParity:

    @pytest.mark.slow
    def test_hybrid_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_hybrid_twin"))
        from ocp_hybrid_twin.lane_a.hybrid_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = EXAMPLES_DIR / "ocp_hybrid_twin" / "lane_b" / "hybrid_mission" / "plan.yaml"
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP Hybrid Twin Mission",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOASOCPCombinedParity:

    @pytest.mark.slow
    def test_wing_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "oas_ocp_combined"))
        from oas_ocp_combined.lane_a.wing_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = EXAMPLES_DIR / "oas_ocp_combined" / "lane_b" / "wing_mission" / "plan.yaml"
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        # Composite plans nest results under summary["components"][id]
        wing_b = result["summary"]["components"]["wing"]
        mission_b = result["summary"]["components"]["mission"]
        lane_b_flat = {
            "wing_CL": wing_b["CL"],
            "wing_CD": wing_b["CD"],
            "fuel_burn_kg": mission_b["fuel_burn_kg"],
            "OEW_kg": mission_b["OEW_kg"],
            "MTOW_kg": mission_b["MTOW_kg"],
        }

        _print_comparison(
            "OAS+OCP Combined (uncoupled)",
            lane_a,
            lane_b_flat,
            keys=["wing_CL", "wing_CD", "fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert lane_b_flat["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )
        assert lane_b_flat["wing_CL"] == pytest.approx(
            lane_a["wing_CL"], rel=1e-6,
        )
        assert lane_b_flat["wing_CD"] == pytest.approx(
            lane_a["wing_CD"], rel=1e-6,
        )


class TestOCPPyCycleCoupledParity:

    @pytest.mark.slow
    def test_coupled_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_pyc_coupled"))
        from ocp_pyc_coupled.lane_a.coupled_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = EXAMPLES_DIR / "ocp_pyc_coupled" / "lane_b" / "coupled_mission" / "plan.yaml"
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP+pyCycle Coupled Mission (turbojet surrogate)",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestPyCycleTurbojetParity:

    @pytest.mark.slow
    def test_turbojet_design_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "pyc_turbojet"))
        from pyc_turbojet.lane_a.design_analysis import run as lane_a_run

        lane_a = lane_a_run()

        plan_dir = EXAMPLES_DIR / "pyc_turbojet" / "lane_b"
        out = tmp_path / "plan.yaml"
        assemble_plan(plan_dir, output=out)
        result = run_plan(out, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "pyCycle Turbojet Design Point",
            lane_a,
            result["summary"],
            keys=["Fn", "TSFC", "OPR"],
        )

        assert result["summary"]["Fn"] == pytest.approx(lane_a["Fn"], rel=1e-6)
        assert result["summary"]["TSFC"] == pytest.approx(lane_a["TSFC"], rel=1e-6)
        assert result["summary"]["OPR"] == pytest.approx(lane_a["OPR"], rel=1e-6)


class TestOCPOASCoupledParity:

    @pytest.mark.slow
    def test_coupled_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_oas_coupled"))
        from ocp_oas_coupled.lane_a.coupled_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = EXAMPLES_DIR / "ocp_oas_coupled" / "lane_b" / "coupled_mission" / "plan.yaml"
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP+OAS Coupled Mission (VLM drag slot)",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPOASDirectCoupledParity:

    @pytest.mark.slow
    def test_direct_coupled_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_oas_direct"))
        from ocp_oas_direct.lane_a.direct_coupled_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = (
            EXAMPLES_DIR / "ocp_oas_direct" / "lane_b"
            / "direct_coupled_mission" / "plan.yaml"
        )
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP+OAS Direct-Coupled Mission (VLM-direct drag slot)",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )


class TestOCPThreeToolParity:

    @pytest.mark.slow
    def test_coupled_mission_parity(self, tmp_path):
        sys.path.insert(0, str(EXAMPLES_DIR / "ocp_three_tool"))
        from ocp_three_tool.lane_a.coupled_mission import run as lane_a_run

        lane_a = lane_a_run()

        plan_path = (
            EXAMPLES_DIR / "ocp_three_tool" / "lane_b"
            / "coupled_mission" / "plan.yaml"
        )
        result = run_plan(plan_path, mode="analysis", recording_level="minimal",
                          db_path=tmp_path / "analysis.db")

        _print_comparison(
            "OCP Three-Tool B738 Mission (VLM drag + pyCycle HBTF surrogate)",
            lane_a,
            result["summary"],
            keys=["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
        )

        assert result["status"] in ("completed", "converged")
        assert result["summary"]["fuel_burn_kg"] == pytest.approx(
            lane_a["fuel_burn_kg"], rel=1e-3,
        )
