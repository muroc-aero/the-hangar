"""Click CLI for hangar-range-safety."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml


@click.group()
def cli() -> None:
    """range-safety -- plan validation and post-run assertions."""


@cli.command("validate")
@click.argument("plan_path", type=click.Path(exists=True))
@click.option(
    "--catalog-dir",
    type=click.Path(exists=True),
    default=None,
    help="Path to the component catalog directory.",
)
def validate_cmd(plan_path: str, catalog_dir: str | None) -> None:
    """Validate an assembled plan against structural, traceability, and heuristic checks.

    PLAN_PATH is the path to an assembled plan.yaml file.
    """
    plan_file = Path(plan_path)
    with open(plan_file) as f:
        plan = yaml.safe_load(f)

    if not isinstance(plan, dict):
        click.echo(json.dumps({"status": "fail", "error": "Plan must be a YAML mapping"}))
        sys.exit(1)

    cat_path = Path(catalog_dir) if catalog_dir else None

    from hangar.range_safety.validators.structural import validate_structural
    from hangar.range_safety.validators.traceability import validate_traceability
    from hangar.range_safety.validators.heuristics import validate_heuristics

    findings: list[dict] = []
    findings.extend(validate_structural(plan, catalog_dir=cat_path))
    findings.extend(validate_traceability(plan))
    findings.extend(validate_heuristics(plan, catalog_dir=cat_path))

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    status = "fail" if errors else ("warn" if warnings else "pass")

    result = {
        "status": status,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": findings,
    }

    click.echo(json.dumps(result, indent=2))
    if errors:
        sys.exit(1)


@cli.command("assert")
@click.argument("run_id")
@click.option(
    "--plan",
    "plan_path",
    type=click.Path(exists=True),
    required=True,
    help="Path to the plan.yaml used for this run.",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    help="Path to the analysis database.",
)
def assert_cmd(run_id: str, plan_path: str, db: str | None) -> None:
    """Run post-execution assertions on a completed run.

    Checks convergence and constraint satisfaction for RUN_ID.
    """
    plan_file = Path(plan_path)
    with open(plan_file) as f:
        plan = yaml.safe_load(f)

    db_path = Path(db) if db else None

    from hangar.range_safety.assertions.convergence import assert_convergence
    from hangar.range_safety.assertions.constraints import assert_constraints

    convergence = assert_convergence(run_id, db_path=db_path)
    constraint_result = assert_constraints(run_id, plan, db_path=db_path)

    all_passed = convergence["passed"] and constraint_result["passed"]

    result = {
        "status": "pass" if all_passed else "fail",
        "convergence": convergence,
        "constraints": constraint_result,
    }

    click.echo(json.dumps(result, indent=2))
    if not all_passed:
        sys.exit(1)


def main() -> None:
    """Entry point for range-safety CLI."""
    cli()
