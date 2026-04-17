"""Tests for the ``omd-cli plan`` authoring subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from hangar.omd.cli import cli


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "oas_aerostruct_enriched"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def initialized_plan(tmp_path: Path, runner: CliRunner) -> Path:
    d = tmp_path / "plan"
    result = runner.invoke(
        cli,
        ["plan", "init", str(d), "--id", "demo", "--name", "Demo"],
    )
    assert result.exit_code == 0, result.output
    return d


@pytest.fixture
def plan_with_component(
    initialized_plan: Path,
    runner: CliRunner,
    tmp_path: Path,
) -> Path:
    result = runner.invoke(
        cli,
        [
            "plan", "add-component",
            str(initialized_plan),
            "--id", "wing",
            "--type", "oas/AerostructPoint",
            "--config-file", str(FIXTURE_ROOT / "components" / "wing.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    return initialized_plan


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def test_plan_init_non_interactive(tmp_path: Path, runner: CliRunner):
    d = tmp_path / "plan"
    result = runner.invoke(
        cli,
        ["plan", "init", str(d), "--id", "demo", "--name", "Demo"],
    )
    assert result.exit_code == 0, result.output
    meta = yaml.safe_load((d / "metadata.yaml").read_text())
    assert meta["id"] == "demo"


def test_plan_init_missing_required_flags_errors(
    tmp_path: Path, runner: CliRunner,
):
    result = runner.invoke(cli, ["plan", "init", str(tmp_path / "x")])
    assert result.exit_code == 1
    assert "required" in result.output.lower()


def test_plan_init_interactive(tmp_path: Path, runner: CliRunner):
    d = tmp_path / "plan"
    result = runner.invoke(
        cli,
        ["plan", "init", str(d), "--interactive"],
        input="demo\nDemo\n\n",
    )
    assert result.exit_code == 0, result.output
    meta = yaml.safe_load((d / "metadata.yaml").read_text())
    assert meta["id"] == "demo"
    assert meta["name"] == "Demo"


# ---------------------------------------------------------------------------
# add-component
# ---------------------------------------------------------------------------

def test_plan_add_component_from_config_file(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-component",
            str(initialized_plan),
            "--id", "wing",
            "--type", "oas/AerostructPoint",
            "--config-file", str(FIXTURE_ROOT / "components" / "wing.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(
        (initialized_plan / "components" / "wing.yaml").read_text()
    )
    assert data["id"] == "wing"


def test_plan_add_component_missing_config_file_errors(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-component",
            str(initialized_plan),
            "--id", "wing",
            "--type", "oas/AerostructPoint",
        ],
    )
    assert result.exit_code == 1
    assert "config-file" in result.output.lower()


# ---------------------------------------------------------------------------
# add-requirement
# ---------------------------------------------------------------------------

def test_plan_add_requirement_non_interactive(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-requirement", str(initialized_plan),
            "--id", "R1", "--text", "Minimize mass",
            "--priority", "primary",
        ],
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(
        (initialized_plan / "requirements.yaml").read_text()
    )
    assert data[0]["id"] == "R1"
    assert data[0]["priority"] == "primary"


# ---------------------------------------------------------------------------
# add-dv / set-objective
# ---------------------------------------------------------------------------

def test_plan_add_dv_non_interactive(
    plan_with_component: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-dv", str(plan_with_component),
            "--name", "twist_cp",
            "--lower", "-10",
            "--upper", "15",
        ],
    )
    assert result.exit_code == 0, result.output
    opt = yaml.safe_load(
        (plan_with_component / "optimization.yaml").read_text()
    )
    assert opt["design_variables"][0] == {
        "name": "twist_cp", "lower": -10.0, "upper": 15.0,
    }


def test_plan_add_dv_unknown_name_errors_with_allowed_list(
    plan_with_component: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-dv", str(plan_with_component),
            "--name", "bogus_dv",
            "--lower", "0", "--upper", "1",
        ],
    )
    assert result.exit_code == 1
    assert "twist_cp" in result.output


def test_plan_set_objective_non_interactive(
    plan_with_component: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "set-objective", str(plan_with_component),
            "--name", "structural_mass", "--scaler", "0.0001",
        ],
    )
    assert result.exit_code == 0, result.output
    opt = yaml.safe_load(
        (plan_with_component / "optimization.yaml").read_text()
    )
    assert opt["objective"] == {"name": "structural_mass", "scaler": 0.0001}


# ---------------------------------------------------------------------------
# add-decision
# ---------------------------------------------------------------------------

def test_plan_add_decision_offlist_stage_warns(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-decision", str(initialized_plan),
            "--stage", "invented",
            "--decision", "Picked invented stage",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower()
    data = yaml.safe_load(
        (initialized_plan / "decisions.yaml").read_text()
    )
    assert data[0]["stage"] == "invented"


def test_plan_add_decision_onlist_stage_no_warn(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "add-decision", str(initialized_plan),
            "--stage", "dv_setup",
            "--decision", "Reasonable choice",
            "--rationale", "because",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "warning" not in result.output.lower()


# ---------------------------------------------------------------------------
# set-operating-point / set-solver / set-analysis-strategy
# ---------------------------------------------------------------------------

def test_plan_set_operating_point_non_interactive(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "set-operating-point", str(initialized_plan),
            "--mach", "0.84", "--alpha", "5.0",
            "--re", "1000000", "--rho", "0.38",
            "--velocity", "248.0",
        ],
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(
        (initialized_plan / "operating_points.yaml").read_text()
    )
    assert data["Mach_number"] == 0.84
    assert data["alpha"] == 5.0


def test_plan_set_solver_non_interactive(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "set-solver", str(initialized_plan),
            "--nonlinear", "NewtonSolver",
            "--linear", "DirectSolver",
            "--nonlinear-maxiter", "20",
        ],
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((initialized_plan / "solvers.yaml").read_text())
    assert data["nonlinear"]["type"] == "NewtonSolver"
    assert data["nonlinear"]["options"]["maxiter"] == 20


def test_plan_set_analysis_strategy_non_interactive(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        [
            "plan", "set-analysis-strategy",
            str(initialized_plan),
            "--phases", "3",
        ],
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(
        (initialized_plan / "analysis_plan.yaml").read_text()
    )
    assert [p["id"] for p in data["phases"]] == ["p1", "p2", "p3"]


# ---------------------------------------------------------------------------
# Interactive flows
# ---------------------------------------------------------------------------

def test_interactive_add_dv_shows_allowed_names(
    plan_with_component: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        ["plan", "add-dv", str(plan_with_component), "--interactive"],
        input="twist_cp\n-10\n15\nConservative envelope\n",
    )
    assert result.exit_code == 0, result.output
    assert "Allowed DV short names" in result.output
    assert "twist_cp" in result.output


def test_interactive_add_dv_without_components_warns_not_validated(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        ["plan", "add-dv", str(initialized_plan), "--interactive"],
        input="any_name\n-1\n1\nbecause\n",
    )
    assert result.exit_code == 0, result.output
    assert "No components declared" in result.output


def test_interactive_refuses_empty_rationale(
    plan_with_component: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        ["plan", "add-dv", str(plan_with_component), "--interactive"],
        input="twist_cp\n-10\n15\n\n",  # empty rationale
    )
    assert result.exit_code == 1
    assert "rationale" in result.output.lower()


def test_interactive_add_decision_lists_stages(
    initialized_plan: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        ["plan", "add-decision", str(initialized_plan), "--interactive"],
        input="dv_setup\nConservative bounds\nStudy kickoff\n\n",
    )
    assert result.exit_code == 0, result.output
    assert "Recommended stages" in result.output
    assert "dv_setup" in result.output


def test_interactive_set_objective_echoes_allowed_names(
    plan_with_component: Path,
    runner: CliRunner,
):
    result = runner.invoke(
        cli,
        ["plan", "set-objective", str(plan_with_component), "--interactive"],
        input="structural_mass\n\nPrimary goal\n",
    )
    assert result.exit_code == 0, result.output
    assert "Allowed objective names" in result.output


def test_interactive_add_requirement_captures_rationale(
    initialized_plan: Path,
    runner: CliRunner,
):
    # Inputs: id, text, type (blank), priority (blank), rationale
    result = runner.invoke(
        cli,
        ["plan", "add-requirement", str(initialized_plan), "--interactive"],
        input="R1\nMinimize mass\n\n\nPrimary goal\n",
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(
        (initialized_plan / "requirements.yaml").read_text()
    )
    assert data[0]["id"] == "R1"
    decisions = yaml.safe_load(
        (initialized_plan / "decisions.yaml").read_text()
    )
    assert decisions[0]["rationale"] == "Primary goal"


# ---------------------------------------------------------------------------
# End-to-end: build a plan from scratch and assemble it
# ---------------------------------------------------------------------------

def test_e2e_build_plan_and_assemble(tmp_path: Path, runner: CliRunner):
    """Author a plan via CLI subcommands, then assemble + review it."""
    plan = tmp_path / "e2e"

    def _run(*args: str, input: str | None = None):
        result = runner.invoke(cli, list(args), input=input)
        assert result.exit_code == 0, (
            f"Command {args} failed: {result.output}"
        )
        return result

    _run("plan", "init", str(plan), "--id", "e2e", "--name", "E2E study")
    _run(
        "plan", "add-component", str(plan),
        "--id", "wing", "--type", "oas/AerostructPoint",
        "--config-file", str(FIXTURE_ROOT / "components" / "wing.yaml"),
        "--rationale", "Baseline wing config",
    )
    _run(
        "plan", "add-requirement", str(plan),
        "--id", "R1", "--text", "Minimize structural mass",
        "--priority", "primary",
        "--rationale", "Primary study goal",
    )
    _run(
        "plan", "set-operating-point", str(plan),
        "--mach", "0.84", "--alpha", "5.0",
        "--velocity", "248.0", "--re", "1000000", "--rho", "0.38",
        "--rationale", "Cruise design point",
    )
    _run(
        "plan", "set-solver", str(plan),
        "--nonlinear", "NewtonSolver",
        "--linear", "DirectSolver",
        "--nonlinear-maxiter", "20",
        "--rationale", "Standard aerostruct choice",
    )
    _run(
        "plan", "add-dv", str(plan),
        "--name", "twist_cp", "--lower", "-10", "--upper", "15",
        "--rationale", "Conservative twist envelope",
    )
    _run(
        "plan", "set-objective", str(plan),
        "--name", "structural_mass", "--scaler", "0.0001",
        "--rationale", "Primary study goal",
    )
    _run(
        "plan", "add-decision", str(plan),
        "--stage", "optimizer_selection",
        "--decision", "SLSQP with maxiter 200",
        "--rationale", "Inequality constraints + continuous DVs",
    )
    _run("plan", "set-analysis-strategy", str(plan), "--phases", "2",
         "--rationale", "Baseline verify then optimize")

    # Assemble — must succeed with no validation errors.
    assemble_result = runner.invoke(cli, ["assemble", str(plan)])
    assert assemble_result.exit_code == 0, assemble_result.output
    assert "Assembled plan v1" in assemble_result.output
    assert (plan / "plan.yaml").exists()

    # Validate the assembled plan against the full schema.
    from hangar.omd.plan_schema import validate_plan
    plan_dict = yaml.safe_load((plan / "plan.yaml").read_text())
    errors = validate_plan(plan_dict)
    assert errors == [], f"assembled plan failed schema: {errors}"

    # Review — should emit no ERROR findings (WARN/MISSING are fine).
    review_result = runner.invoke(
        cli, ["plan", "review", str(plan), "--format", "json"],
    )
    assert review_result.exit_code == 0, review_result.output
    import json as _json
    review_payload = _json.loads(review_result.output)
    findings = review_payload.get("findings", [])
    errors_only = [f for f in findings if f.get("severity") == "ERROR"]
    assert errors_only == [], (
        f"plan review reported ERRORs: {errors_only}"
    )

    # Decisions file should contain entries from each captured rationale
    # plus the one hand-authored add-decision.
    decisions = yaml.safe_load((plan / "decisions.yaml").read_text())
    stages = {d["stage"] for d in decisions}
    assert "dv_setup" in stages
    assert "objective_selection" in stages
    assert "optimizer_selection" in stages  # from add-decision
    assert "operating_point_selection" in stages
